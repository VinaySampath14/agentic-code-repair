# Agentic Code Repair

Give it a GitHub issue URL. It reads the codebase, finds the broken code, writes a patch, runs the tests, and opens a draft PR — no human input beyond the issue.

Evaluated on [SWE-bench Lite](https://github.com/princeton-nlp/SWE-bench) — 50 real bugs across Django, Sympy, scikit-learn, and 8 other OSS repos.

---

## Results

| Config | Model | Approved | Avg Score |
|--------|-------|----------|-----------|
| A — single-agent baseline | GPT-4o | 4% (2/50) | 0.21 |
| B — multi-agent pipeline | GPT-4o | 42% (21/50) | 0.46 |
| C — multi-agent (local) | Qwen2.5-Coder-32B | in progress | — |

Same 50 tasks across all configs. Config C is running on Bauhaus HPC via vLLM + SLURM — results will be added when complete.

---

## Demo

> Open a GitHub issue -> pipeline fires automatically -> draft PR appears

<!-- replace with GIF after recording -->
![demo](docs/demo.gif)

---

## How it works

```mermaid
flowchart TD
    Issue([GitHub Issue URL])

    Issue --> Planner

    Planner["Planner
    GitHub API · code search
    identifies affected files"]

    Explorer["Explorer
    read_file · local clone scan
    finds broken_file + broken_function"]

    Coder["Coder
    git apply · patch_tools
    generates and applies patch"]

    Critic["Critic
    pytest · ruff
    scores patch 0-1"]

    PR["PR Agent
    git push · GitHub API
    opens draft PR"]

    Planner --> Explorer
    Explorer --> Coder
    Coder --> Critic
    Critic --> PR

    Explorer -. "low confidence — replan up to 2x" .-> Planner
    Critic -. "score < 0.6 — retry up to 3x" .-> Coder
```

### Scoring

The Critic scores every patch before deciding to approve, retry, or fail:

```
fix_score = 0.5 * test_pass_rate
          + 0.3 * no_regression        (rate, not binary)
          + 0.2 * code_quality
```

At historical `base_commit` checkpoints, package incompatibilities often cause pytest to collect 0 tests. In that case the formula switches to:

```
fix_score = 0.8 * llm_semantic_score
          + 0.2 * code_quality
```

Patches that reach 0.6 go through one more check — a separate LLM call that asks whether the patch actually addresses the root cause in the issue. If not, it retries.

---

## Setup

Copy `.env.template` to `.env` and fill in:

```
GITHUB_WEBHOOK_SECRET=...
GITHUB_TOKEN=...
OPENAI_API_KEY=...
```

Start the server and expose it:

```bash
uvicorn src.webhook:app --host 0.0.0.0 --port 8000
ngrok http 8000
```

Add the ngrok URL as a GitHub webhook — payload URL `https://<ngrok-id>.ngrok-free.app/webhook`, content type `application/json`, secret matching `GITHUB_WEBHOOK_SECRET`, events: Issues only.

Open a new issue and the pipeline runs in the background. Results go to `logs/webhook_results.jsonl`.

---

## Running evals

```bash
# multi-agent, 50 tasks
python run_eval.py --n 50 --working

# single-agent baseline
python run_eval.py --config a --n 50 --working

# specific tasks
python run_eval.py --tasks psf__requests-1734,psf__requests-1789
```

---

## Tech stack

| Layer | What |
|-------|------|
| Orchestration | LangGraph |
| LLM | GPT-4o / GPT-4o-mini / Qwen2.5-Coder-32B |
| Local inference | vLLM on SLURM (Bauhaus HPC) |
| GitHub | PyGithub |
| Observability | MLflow (metrics), Langfuse (LLM traces) |
| Web server | FastAPI + uvicorn |
| Linter | Ruff |
| Eval | SWE-bench Lite |

---

## Tests

```bash
pytest tests/test_agents_smoke.py -v
```

9 tests: agent imports, critic scoring edge cases, tracing shim.

---

## Docs

- [structure.md](structure.md) — file layout
- [decision.md](decision.md) — why things are built the way they are
- [failure.md](failure.md) — what broke during eval and how it got fixed
