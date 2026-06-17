# Project Structure

```
agentic-code-repair/
|
+-- src/
|   +-- agents/
|   |   +-- planner_agent.py       reads repo structure + issue, identifies affected files
|   |   +-- explorer_agent.py      iterative file reader, finds broken_file + broken_function
|   |   +-- coder_agent.py         generates patch with self-correction loop (<=3 attempts)
|   |   +-- critic_agent.py        runs tests, scores patch 0-1, gates retry/approve/fail
|   |   +-- pr_agent.py            pushes branch + opens PR (live) or writes .diff (eval)
|   |
|   +-- tools/
|   |   +-- github_tools.py        PyGithub wrappers: read_file, repo structure, create_pr
|   |   +-- test_tools.py          pytest runner with repo-aware fast test selection
|   |   +-- shell_tools.py         subprocess runner, import extractor
|   |   +-- patch_tools.py         patch application, diff parsing
|   |
|   +-- graph.py                   LangGraph workflow (5 nodes, conditional routing)
|   +-- state.py                   AgentState TypedDict (44 fields)
|   +-- config.py                  env-based config (model mode, thresholds, API keys)
|   +-- tracing.py                 Langfuse integration shim
|   +-- logger.py                  file-rotating logger, silences noisy libs
|   +-- webhook.py                 FastAPI server for GitHub issue webhook
|
+-- prompts/
|   +-- planner.txt
|   +-- explorer.txt
|   +-- coder.txt
|   +-- critic.txt
|   +-- critic_semantic.txt        separate root-cause check before approval
|   +-- pr_agent.txt
|
+-- evals/
|   +-- predictions/               .diff files written in eval mode (one per task)
|   +-- results.json               aggregated scores for all 50 tasks
|
+-- tests/
|   +-- test_agents_smoke.py
|   +-- test_tools.py
|
+-- main.py                        Config B entry point (multi-agent)
+-- main_single.py                 Config A entry point (single-agent baseline)
+-- run_eval.py                    batch eval harness for SWE-bench Lite
+-- conftest.py
+-- requirements.txt
+-- .env.template
```
