# Agentic Code Repair

Give it a GitHub issue URL, it opens a draft PR. No other input needed.

Built as a portfolio project for M.Sc. Digital Engineering at Bauhaus-Universität Weimar. Evaluated on [SWE-bench Lite](https://github.com/princeton-nlp/SWE-bench).

---

## Results

| Config | Model | Approved | Avg Score |
|--------|-------|----------|-----------|
| A — single-agent baseline | GPT-4o | 4% (2/50) | 0.21 |
| B — multi-agent pipeline | GPT-4o | 42% (21/50) | 0.46 |
| C — multi-agent (local) | Qwen2.5-Coder-32B | in progress | — |

Same 50 SWE-bench Lite tasks across all three configs. Config C is running on Bauhaus HPC via vLLM + SLURM.

---

## How it works

```
GitHub Issue
     │
     ▼
┌─────────────┐
│   Planner   │  reads repo structure, identifies files to look at
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Explorer  │  reads source files iteratively, finds what's broken
└──────┬──────┘
       │ (replan <=2x if confidence low)
       ▼
┌─────────────┐
│    Coder    │  generates patch (old_code -> new_code), self-corrects <=3x
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Critic    │  runs tests, scores 0-1, decides approve / retry / fail
└──────┬──────┘
       │ (retry <=3x if score < 0.6)
       ▼
┌─────────────┐
│  PR Agent   │  pushes branch, opens draft PR
└─────────────┘
```

### Scoring

```
# when tests run:
fix_score = 0.5 * test_pass_rate + 0.3 * no_regression + 0.2 * code_quality

# when tests can't run (incompatible env at old base_commit):
fix_score = 0.8 * llm_semantic_score + 0.2 * code_quality
```

Patches above 0.6 go through a semantic root-cause check before approval.

---

## Demo

> Open a GitHub issue -> pipeline fires automatically -> draft PR appears

<!-- replace with GIF after recording -->
![demo](docs/demo.gif)

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
