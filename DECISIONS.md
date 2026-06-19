# Architecture Design Decisions

Resolved before implementation begins. Reference these in interviews.

---

## 1. Evaluation scope: 50 tasks, stratified

Run a fixed 50 tasks from SWE-bench Lite across all three configurations (same 50 for A, B, C).

**Stratification:**
- ~15 Django
- ~10 Sympy
- ~8 Matplotlib
- ~8 Scikit-learn
- ~9 other repos

Within each repo: mix of easy and hard tasks. Selection criteria documented in README.

**Why defensible:** the delta between configs is the finding, not the absolute resolve rate. 50 tasks is enough for comparison. Document selection criteria so any reviewer gets a methodological answer.

---

## 2. `no_regression` is a rate, not binary

```python
no_regression = passing_tests_after / passing_tests_before
```

Full fix_score formula:

```python
fix_score = (0.5 * test_pass_rate) + (0.3 * no_regression) + (0.2 * code_quality)
```

**Why rate:** binary is too harsh and loses information. A patch that breaks 1 of 10 existing tests scores 0.9, not 0. Critic can still approve at fix_score >= 0.6. Also gives a richer distribution to analyse — not just 0s and 1s.

---

## 3. PR Agent runs in demo mode only — dual mode via env flag

```python
EVAL_MODE=true   # skips PR Agent, writes patch to predictions/{instance_id}.diff
EVAL_MODE=false  # runs full pipeline including PR Agent (real GitHub PR)
```

SWE-bench evaluates patches, not PRs. In eval mode, after Critic approves, write patch in SWE-bench expected format. PR Agent only activates in demo mode.

**Why this matters:** shows understanding of the difference between benchmark evaluation and real-world deployment. Worth mentioning in interviews.

---

## 4. `route_after_explorer` triggers on two conditions

1. A listed file literally does not exist in the repo (hard error)
2. Explorer read the files but returns `confidence: "low"` — files don't seem relevant to the issue

Explorer returns a structured output:

```python
class ExplorerOutput(TypedDict):
    file_contents: dict[str, str]
    confidence: str   # "high" | "low"
    reason: str       # explanation if confidence is low
```

**Why broaden beyond file-not-found:** the subtler failure mode — Explorer reads the wrong files successfully — is more common than hard errors. Catching it becomes an interesting finding in the failure analysis.

---

## 6. Test execution requires Docker — LLM semantic scoring used as fallback

SWE-bench tasks target historical `base_commit` checkouts. At those old commits, repos have incompatibilities with current package versions (`np.unicode_` removed in NumPy 1.24+, old dask APIs, etc.). Running `pytest` natively on Windows fails to collect tests for most repos, returning 0 passed / 0 failed.

**What this means for scoring:**

The original formula:
```python
fix_score = (0.5 * test_pass_rate) + (0.3 * no_regression) + (0.2 * code_quality)
```

When 0 tests collect, `test_pass_rate = 0` and `no_regression = 1.0` (divide-by-zero guard), locking every patch at 0.5 regardless of quality.

**Decision: LLM semantic scoring fallback**

When 0 tests collect, substitute an LLM patch review score (0.0–1.0) in place of `test_pass_rate`:
```python
if tests_ran:
    fix_score = (0.5 * test_pass_rate) + (0.3 * no_regression) + (0.2 * code_quality)
else:
    fix_score = (0.8 * llm_score_patch(state)) + (0.2 * code_quality)
```

**Why not Docker:** This is a portfolio project. The official SWE-bench evaluation harness uses Docker per-task images with exact environments and is how leaderboard scores are computed. For production use, the right architecture is: our pipeline generates `.diff` files → official harness scores them in Docker. The LLM semantic score serves as a retry signal during generation; it is not the ground truth eval metric.

**What to say in interviews:** "We use LLM semantic scoring as an internal retry signal because proper test execution at old base_commits requires Docker. The official SWE-bench harness handles ground truth evaluation. This separation of concerns — patch generation vs. patch evaluation — is how all production SWE-bench systems work."

---

## 7. MCP integration: expose pipeline as MCP server, keep GitHub tools as PyGithub

The pipeline is exposed as an MCP server (`src/mcp_server.py`) so Claude Desktop and other MCP-aware clients can call `fix_github_issue(url)` as a tool. This is additive — the existing webhook (`src/webhook.py`) and CLI (`main.py`) are unchanged.

**What was migrated to MCP (`src/github_mcp_server.py`):**
- `search_codebase` — called once by Planner, no caching needed, silent fallback on failure
- `create_pr` — called once by PR Agent, low frequency, no caching needed

**What stayed as direct PyGithub:**
- `read_file` and `get_repo_structure` — called 4–8 times per task in the Explorer hot loop; need the PyGithub `_repo_cache` to avoid rate limits

**How consumption works:** `github_tools.py` uses `mcp.client.stdio.stdio_client` + `ClientSession` to spawn `src/github_mcp_server.py` as a subprocess and call its tools via the MCP protocol. In production, swap `src/github_mcp_server.py` for the official `github/github-mcp-server` binary — no changes needed in the consumer.

**Why build a local MCP server instead of using the official one:**
Node.js is not available in this environment; the official GitHub MCP server requires npx. The local Python server demonstrates the same MCP client-server protocol and is a drop-in replacement.

**What to say in interviews:** "I exposed the pipeline as an MCP server so any MCP-aware client can call it as a tool. I chose not to replace the GitHub API calls with the GitHub MCP server because my Explorer reads 4–8 files per task and needs the PyGithub caching layer to avoid rate limits. MCP is best for lower-frequency, externally-facing operations."

---

## 8. quick_mode: skip pytest for MCP/demo use

MCP tool calls in Claude Desktop have a ~60s timeout. The full pipeline takes 1–2 minutes (5 agents + pytest with 30s timeout). To make the demo work within the timeout, added a `quick_mode` flag to `AgentState`.

When `quick_mode=True`, the Critic skips the pytest baseline + post-patch runs and jumps directly to the existing LLM semantic scoring fallback (already present for historical base_commit environments where tests can't collect). Fix score formula in quick_mode: `0.8 * llm_semantic_score + 0.2 * code_quality`. Pipeline runtime drops to ~30–40s.

**What was NOT changed:** `eval_mode`, `run_eval.py`, the scoring formula for normal runs, CODER_MAX_RETRIES. The benchmark results (Config B: 42%) remain valid — quick_mode is only used by the MCP server.

**Implemented solution:** async job pattern — `fix_github_issue` starts the pipeline in a background thread and returns a job ID immediately (< 1s). A second tool `get_repair_status(job_id)` polls for the result. Client polls every 30s until status is `done` or `error`. No timeout possible — the client controls polling cadence.

---

## 5. Explorer reads iteratively with a structured budget

LLM decides what to read next at each iteration (upfront planning fails — can't predict import chains before reading).

**Structure:**
```
Iteration 1: Read files Planner identified
Iteration 2: LLM decides — follow imports? read tests? read config?
Iteration 3: LLM decides again
Hard stop:   max 8 files OR max 3 iterations, whichever comes first
```

At each iteration LLM receives: issue text + files read so far + "what do you need next, or are you ready?" Early exit if LLM says ready. If limit hit, Explorer exits and sets `confidence: "low"`.

**Why hard stop is critical:** without it, eval tasks spiral into 20+ file reads and timeout. The 8-file limit is also the primary lever for fixing context overflow failures in Week 3.
