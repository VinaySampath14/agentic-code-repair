# Findings -- Agentic Code Repair

## Failure observed -- run 1
Task: psf__requests-1734
Fix score: 1.0 (false positive)
Category: Test blindness + wrong file

What happened:
  Coder patched models.py (path handling) instead of
  sessions.py (merge_setting). The patch is a no-op --
  dead code inside `if not path:` that never executes.
  258 tests passed because none test verify=False
  session-level behaviour.

Two conditions created the false positive:
  1. Coder edited the wrong file entirely
  2. No issue-specific test in the fast suite

Root cause chain:
  Explorer read models.py, utils.py, adapters.py
  -> missed sessions.py entirely
  -> Coder had no sessions.py context
  -> patched what it could see, not what was broken
  -> Critic had no semantic check, only test check
  -> false positive slipped through

Fix: Semantic check added to Critic -- separate LLM call:
  "Does this patch address the root cause in the issue?"
  Returns yes/no + reason. If no, treat as retry.
  STATUS: Implemented.

---

## Batch eval -- runs 2-5 (psf/requests, SWE-bench Lite)

Tasks: psf__requests-1963, 2148, 2317, 2674
Pipeline: semantic check active, auto issue-body fetch

Results:

  psf__requests-1963  score=1.0  sessions.py   LIKELY CORRECT
    Patch: req.copy() -> resp.request.copy() in redirect loop.
    FAIL_TO_PASS includes test_requests_are_updated_each_time.

  psf__requests-2148  score=0.9  adapters.py   PLAUSIBLE
    Patch: adds socket.error to exception tuple.
    Correct for Python 2 (socket.error not subclass of OSError).

  psf__requests-2317  score=0.891  compat.py   RISKY
    Patch: builtin_str = str -> def builtin_str(s): ...
    Changes type alias to function. Breaks isinstance(x, builtin_str).
    Likely false positive.

  psf__requests-2674  score=0.891  n/a         PIPELINE BUG
    Explorer/Planner returned broken_file="n/a".
    Coder crashed: FileNotFoundError on repos/psf__requests/n/a.
    Critic then ran on unpatched repo, scored 0.891 (false positive).

Failure modes identified:

  Failure 2 -- broken_file="n/a"
    Fix: guard in coder -- treat n/a/none/unknown as hard fail.
    STATUS: Implemented.

  Failure 3 -- critic scores empty patch as 0.891
    Fix: critic checks for empty patch, scores 0.0 immediately.
    STATUS: Implemented.

---

## Batch eval -- runs 6-8 (psf/requests, SWE-bench Lite)

Tasks: psf__requests-2674 (retry), 3362, 863

  psf__requests-2674  score=0.90  exceptions.py  LIKELY CORRECT
  psf__requests-3362  score=0.00  (no patch)     PIPELINE FAILURE
  psf__requests-863   score=1.00  models.py      LIKELY CORRECT

Failure mode identified:

  Failure 4 -- old_code not found (verbatim mismatch)
    LLM generates old_code that is close but not verbatim.
    All 3 self-correction attempts fail. No patch produced.
    Fix: show nearest matching block in retry prompt.
         Remove inline line numbers (were causing indentation errors).
    STATUS: Implemented.

Metric fix:
  File% was always 0% due to path prefix mismatch.
  Fixed patch_similarity() to strip src/, lib/, source/ prefixes.
  STATUS: Fixed.

---

## Batch eval -- pylint-dev/pylint (6 tasks)

Tasks run with MODEL_MODE=mini (gpt-4o-mini), base_commit checkout.

  pylint-dev__pylint-5859  score=1.0   checkers/misc.py     APPROVED
    Fixed notes regex to handle punctuation-only tags.
    Semantic check caught bad first attempt, second passed.
    50 baseline tests ran and passed.

  pylint-dev__pylint-6506  score=1.0   config/config_initialization.py  APPROVED
    Fixed unrecognized option to raise SystemExit instead of traceback.
    Patch applied on first attempt. All tests passed.

  pylint-dev__pylint-7080  score=1.0   checkers/base_checker.py  APPROVED
    Fixed --recursive=y ignoring ignore-paths.
    Patch applied on first attempt. All tests passed.

  pylint-dev__pylint-7114  score=0.0   lint/pylinter.py     FAILED
    LLM targeted code that does not exist at base_commit.
    old_code not found on all attempts. No patch produced.

  pylint-dev__pylint-7228  score=0.5   config/arguments_manager.py  FAILED
    Patches applied but baseline=0 tests at older base_commit.
    Test infra not compatible with older pylint version deps.
    Score stuck at 0.5 (no_regression=1.0 + code_quality=1.0,
    but test_pass_rate=0.0 because 0 tests collected).

  pylint-dev__pylint-7993  score=0.5   message/message.py   FAILED
    Same as 7228 -- patches apply but baseline=0 tests.

New failure modes identified:

  Failure 5 -- Explorer identifies wrong file/function
    LLM targets non-existent code. Fix requires better Explorer
    (e.g. grep-based file scanning rather than pure LLM guess).

  Failure 6 -- Test infra breaks at older base commits
    Fast test files exist at HEAD but not at all base_commits.
    Installing deps for each historical commit is not feasible.
    Mitigation: accept that fix_score may undercount for old commits.

---

## Infrastructure fixes applied (session 2)

  1. PyGitHub was not installed -- added to requirements.
  2. Unicode chars (---, ->, >=) in run_eval.py crashed on Windows CP1252.
     Fixed: replaced all non-ASCII with ASCII equivalents.
  3. _FAST_TEST_FILES was psf/requests-only. Made repo-aware dict.
     Added pylint fast tests: test_pragma_parser, test_numversion,
     test_similar, test_func (50 tests, ~5s total).
  4. astroid not installed for pylint repo -- pip install astroid isort tomlkit.
  5. base_commit checkout: run_eval.py now passes --base-commit to main.py.
     main.py checks out the exact commit before patching.
  6. Local scan fallback in Explorer: when planner paths all fail,
     scans .py files in local clone and asks LLM to pick the right one.
  7. Removed inline line numbers from coder file view.
     Line numbers caused LLM to miscount indentation when copying old_code.
  8. Nearest-block hint in correction prompt: when old_code not found,
     shows the closest matching block from the actual file.

---

## Running totals (12 tasks across 2 repos)

  psf/requests  (7 tasks): 5 approved (>=0.6), avg score ~0.95
  pylint        (6 tasks): 3 approved (>=0.6), avg score ~0.67
  Overall       (12 tasks): 8 approved (>=0.6), avg score ~0.81

  Dominant failure: old_code not found (4/12 tasks affected)
  Second failure: test infra at historical commits (2/12 tasks)
