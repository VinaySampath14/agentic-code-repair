# Agentic Code Repair

An autonomous 5-agent pipeline that reads a GitHub issue and opens a draft PR — no human in the loop.

Built and evaluated on [SWE-bench Lite](https://github.com/princeton-nlp/SWE-bench) as a portfolio project for M.Sc. Digital Engineering at Bauhaus-Universität Weimar.

---

## Demo

> Open a GitHub issue → agents fire automatically → draft PR appears on GitHub

<!-- Replace with your GIF after recording -->
![demo](docs/demo.gif)

---

## Results

| Config | Model | Approval Rate | Avg Score |
|--------|-------|--------------|-----------|
| A — Single-agent baseline | GPT-4o | 4% (2/50) | 0.21 |
| B — Multi-agent pipeline | GPT-4o | 42% (21/50) | 0.46 |
| C — Multi-agent (local) | Qwen2.5-Coder-32B | *in progress* | — |

**10x improvement** from multi-agent coordination over single-agent baseline on the same 50 SWE-bench Lite tasks.

Config C is currently running on Bauhaus-Universität Weimar HPC cluster via vLLM + SLURM, benchmarking open-source Qwen2.5-Coder-32B against GPT-4o at zero inference cost.

---

## Architecture

```
GitHub Issue
     │
     ▼
┌─────────────┐
│   Planner   │  Reads repo structure → identifies affected files
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Explorer  │  Reads source files iteratively → finds broken_file + broken_function
└──────┬──────┘
       │ (replan loop ≤2x if confidence=low)
       ▼
┌─────────────┐
│    Coder    │  Generates patch (old_code → new_code) with self-correction ≤3x
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Critic    │  Runs tests, scores patch 0–1, gates retry loop
└──────┬──────┘
       │ (retry loop ≤3x if score < 0.6)
       ▼
┌─────────────┐
│  PR Agent   │  Pushes branch, opens draft PR on GitHub
└─────────────┘
```

### Scoring Formula

```
# When tests run:
fix_score = 0.5 × test_pass_rate + 0.3 × no_regression + 0.2 × code_quality

# When tests can't run (old base_commit env incompatibility):
fix_score = 0.8 × llm_semantic_score + 0.2 × code_quality
```

Patches scoring ≥ 0.6 after a semantic root-cause check are approved.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | LangGraph |
| LLM | GPT-4o / GPT-4o-mini / Qwen2.5-Coder-32B |
| Local Inference | vLLM on SLURM (Bauhaus HPC) |
| GitHub API | PyGithub |
| Observability | MLflow (metrics), Langfuse (LLM tracing) |
| Web Demo | FastAPI + uvicorn |
| Code Quality | Ruff (linter), pytest |
| Evaluation | SWE-bench Lite (HuggingFace) |

---

## Autonomous Demo Setup

The webhook server triggers the full pipeline whenever a GitHub issue is opened.

**1. Add to `.env`:**
```
GITHUB_WEBHOOK_SECRET=your_secret_here
GITHUB_TOKEN=your_github_token
OPENAI_API_KEY=your_openai_key
```

**2. Start the server:**
```bash
uvicorn src.webhook:app --host 0.0.0.0 --port 8000
```

**3. Expose to GitHub:**
```bash
ngrok http 8000
```

**4. Add webhook in GitHub repo settings:**
- Payload URL: `https://<ngrok-id>.ngrok-free.app/webhook`
- Content type: `application/json`
- Secret: same value as `GITHUB_WEBHOOK_SECRET`
- Events: Issues only

Open a new issue → pipeline fires in the background → draft PR appears automatically.

Results written to `logs/webhook_results.jsonl`.

---

## Running Evaluations

```bash
# Multi-agent (Config B) — 50 tasks
python run_eval.py --n 50 --working

# Single-agent baseline (Config A) — same 50 tasks
python run_eval.py --config a --n 50 --working

# Specific tasks
python run_eval.py --tasks psf__requests-1734,psf__requests-1789
```

---

## Project Structure

```
├── src/
│   ├── agents/
│   │   ├── planner_agent.py
│   │   ├── explorer_agent.py
│   │   ├── coder_agent.py
│   │   ├── critic_agent.py
│   │   └── pr_agent.py
│   ├── tools/
│   │   ├── github_tools.py
│   │   ├── test_tools.py
│   │   ├── shell_tools.py
│   │   └── patch_tools.py
│   ├── graph.py
│   ├── state.py
│   ├── config.py
│   ├── tracing.py
│   ├── logger.py
│   └── webhook.py
├── prompts/              # LLM prompt templates (one per agent)
├── evals/
│   ├── predictions/      # Generated patches (.diff files)
│   └── results.json      # Eval results with scores
├── tests/
│   └── test_agents_smoke.py
├── main.py               # Config B entry point (multi-agent)
├── main_single.py        # Config A entry point (single-agent)
├── run_eval.py           # Evaluation harness
├── DECISIONS.md          # Architecture decisions with rationale
└── scripts/
    └── start_demo.sh
```

---

## Smoke Tests

```bash
pytest tests/test_agents_smoke.py -v
```

9 tests covering agent imports, critic scoring edge cases, and tracing shim.

---

## Key Design Decisions

See [DECISIONS.md](DECISIONS.md) for full rationale. Highlights:

- **Explorer replan loop** triggers on `confidence=low` OR unreadable files — not just missing files
- **LLM semantic scoring fallback** used when 0 tests collect at old `base_commit` (common with NumPy 1.24+ API removals in historical repos)
- **Critic semantic check** prevents false positives — LLM validates patch addresses root cause before approval
- **Eval mode** skips PR Agent and writes to `predictions/` for SWE-bench compatibility
