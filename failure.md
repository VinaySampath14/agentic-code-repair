# Failures and fixes

## Run 1 -- psf__requests-1734

**Score:** 1.0 (false positive)
**Category:** wrong file + test blindness

Coder patched `models.py` (path handling) instead of `sessions.py` (merge_setting). The patch was dead code inside an `if not path:` branch that never executes. 258 tests passed because none of them test `verify=False` session-level behaviour.

How it happened:
- Explorer read `models.py`, `utils.py`, `adapters.py` — missed `sessions.py` entirely
- Coder only saw the wrong files so patched what it could
- Critic had no semantic check at this point, only checked test counts
- False positive slipped through

**Fix:** Added a semantic check to Critic — separate LLM call asking "does this patch address the root cause in the issue?" before approval. If no, treat as retry. *(Implemented)*

---

## Runs 2-5 -- psf/requests (4 tasks)

Pipeline now had the semantic check active.

```
psf__requests-1963  score=1.0  sessions.py   LIKELY CORRECT
  req.copy() -> resp.request.copy() in redirect loop
  FAIL_TO_PASS includes test_requests_are_updated_each_time

psf__requests-2148  score=0.9  adapters.py   PLAUSIBLE
  adds socket.error to exception tuple
  correct for Python 2 (socket.error not a subclass of OSError there)

psf__requests-2317  score=0.891  compat.py   RISKY
  changes builtin_str = str to def builtin_str(s): ...
  type alias -> function breaks isinstance(x, builtin_str)
  likely false positive

psf__requests-2674  score=0.891  n/a         PIPELINE BUG
  Explorer/Planner returned broken_file="n/a"
  Coder crashed: FileNotFoundError on repos/psf__requests/n/a
  Critic then ran on unpatched repo and scored 0.891
```

**Fix 1:** Coder now treats `n/a`, `none`, `unknown` as hard fail — exits early instead of trying to open the file. *(Implemented)*

**Fix 2:** Critic checks for empty patch before scoring — returns 0.0 immediately if nothing was applied. *(Implemented)*

---

## Runs 6-8 -- psf/requests (3 tasks)

```
psf__requests-2674  score=0.90  exceptions.py  LIKELY CORRECT (retry)
psf__requests-3362  score=0.00  (no patch)     PIPELINE FAILURE
psf__requests-863   score=1.00  models.py      LIKELY CORRECT
```

**Failure mode:** LLM generates `old_code` that is close but not verbatim. All 3 self-correction attempts fail because the string match never hits.

**Fix:** When `old_code` not found, show the nearest matching block from the actual file in the retry prompt. Also removed inline line numbers from the file view — they were causing LLM to miscount indentation when copying back `old_code`. *(Implemented)*

Also fixed `patch_similarity()` — file% was always 0% because of path prefix mismatch. Now strips `src/`, `lib/`, `source/` before comparing.

---

## Pylint batch -- 6 tasks (gpt-4o-mini, base_commit checkout)

```
pylint-dev__pylint-5859  score=1.0   checkers/misc.py                APPROVED
  fixed notes regex to handle punctuation-only tags
  semantic check caught bad first attempt, second passed

pylint-dev__pylint-6506  score=1.0   config/config_initialization.py  APPROVED
  fixed unrecognized option to raise SystemExit instead of traceback

pylint-dev__pylint-7080  score=1.0   checkers/base_checker.py         APPROVED
  fixed --recursive=y ignoring ignore-paths

pylint-dev__pylint-7114  score=0.0   lint/pylinter.py                 FAILED
  LLM targeted code that doesn't exist at base_commit
  old_code not found on all 3 attempts

pylint-dev__pylint-7228  score=0.5   config/arguments_manager.py      FAILED
  patch applied but baseline=0 tests at old base_commit
  score stuck at 0.5 (no_regression=1.0, code_quality=1.0, test_pass_rate=0.0)

pylint-dev__pylint-7993  score=0.5   message/message.py               FAILED
  same issue as 7228
```

**Failure mode 5:** Explorer identifies the wrong file/function — LLM targets code that doesn't exist at that commit. Would need grep-based file scanning rather than pure LLM guess to fix properly.

**Failure mode 6:** Test infra breaks at older base commits. Fast test files exist at HEAD but not at every historical commit. Installing per-commit deps isn't feasible — accepted this as a known limitation.

---

## Infrastructure fixes (session 2)

Things that broke while running evals on Windows:

1. PyGitHub wasn't in requirements — added it
2. Unicode chars (`---`, `->`, `>=`) in `run_eval.py` crashed on Windows CP1252 — replaced all non-ASCII with ASCII
3. `_FAST_TEST_FILES` was psf/requests-only — made it a repo-aware dict, added pylint fast tests (~50 tests, ~5s)
4. `astroid` not installed for pylint repo — `pip install astroid isort tomlkit`
5. `run_eval.py` now passes `--base-commit` to `main.py`, which checks out the exact commit before patching
6. Local scan fallback in Explorer: when all Planner paths fail, scans `.py` files in local clone and asks LLM to pick
7. Removed inline line numbers from Coder's file view — caused indentation mismatches when LLM copied old_code
8. Added nearest-block hint to correction prompt — when old_code not found, show closest matching block from the actual file

---

## Running totals (12 tasks, 2 repos)

```
psf/requests  (7 tasks):  5 approved (>=0.6), avg score ~0.95
pylint        (6 tasks):  3 approved (>=0.6), avg score ~0.67
overall      (12 tasks):  8 approved (>=0.6), avg score ~0.81

dominant failure:   old_code not found (4/12 tasks)
second failure:     test infra at historical commits (2/12 tasks)
```
