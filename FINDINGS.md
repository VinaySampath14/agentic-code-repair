# Findings — Agentic Code Repair

## Failure observed — run 1
Task: psf__requests-1734
Fix score: 1.0 (false positive)
Category: Test blindness + wrong file

What happened:
  Coder patched models.py (path handling) instead of
  sessions.py (merge_setting). The patch is a no-op —
  dead code inside `if not path:` that never executes.
  258 tests passed because none test verify=False
  session-level behaviour.

Two conditions created the false positive:
  1. Coder edited the wrong file entirely
  2. No issue-specific test in the fast suite

Root cause chain:
  Explorer read models.py, utils.py, adapters.py
  → missed sessions.py entirely
  → Coder had no sessions.py context
  → patched what it could see, not what was broken
  → Critic had no semantic check, only test check
  → false positive slipped through

Proposed fix (week 3):
  Add semantic check in Critic — separate LLM call:
  "Does this patch address the root cause in the issue?"
  Returns yes/no + reason. If no, treat as retry
  regardless of fix_score.
  This catches wrong-file patches even when tests pass.
  STATUS: Implemented.

---

## Batch eval — runs 2–5 (psf/requests, SWE-bench Lite)

Tasks: psf__requests-1963, 2148, 2317, 2674
Pipeline: semantic check active, auto issue-body fetch

Results:

  psf__requests-1963  score=1.0  sessions.py   LIKELY CORRECT
    Patch: req.copy() → resp.request.copy() in redirect loop.
    FAIL_TO_PASS includes test_requests_are_updated_each_time.
    Uses resp.request (actual sent request) not req (original).
    Strongest result so far.

  psf__requests-2148  score=0.9  adapters.py   PLAUSIBLE
    Patch: adds socket.error to exception tuple.
    Correct for Python 2 (socket.error not subclass of OSError).
    Harmless in Python 3.3+ (socket.error is OSError alias).
    FAIL_TO_PASS includes test_iter_content_handles_socket_error.

  psf__requests-2317  score=0.891  compat.py   RISKY
    Patch: builtin_str = str → def builtin_str(s): ...
    Changes type alias to function. Breaks isinstance(x, builtin_str).
    Score below 1.0 suggests regression. Likely false positive.

  psf__requests-2674  score=0.891  n/a         PIPELINE BUG
    Explorer/Planner returned broken_file="n/a".
    Coder crashed: FileNotFoundError on repos/psf__requests/n/a.
    Critic then ran on unpatched repo, scored 0.891 (all tests pass).
    Two bugs triggered: coder crash + critic false positive on empty patch.

New failure modes identified:

  Failure 2 — broken_file="n/a"
    Explorer could not identify the file. LLM returned literal "n/a".
    Coder tried to open it as a path and crashed.
    Fix: guard in coder — treat n/a/none/unknown as hard fail immediately.
    STATUS: Implemented.

  Failure 3 — critic scores empty patch as 0.891
    When coder fails and produces no patch, critic still runs tests.
    Unpatched repo passes all 258 tests → high fix_score (false positive).
    Fix: critic checks for empty patch field, scores 0.0 without running tests.
    STATUS: Implemented.

Running tallies (5 tasks):
  Completed without error : 4/5
  Approved (score >= 0.6) : 4/5
  Confirmed false positives: 2 (1734, 2317)
  Likely correct          : 2 (1963, 2148)
  Hard pipeline failures  : 1 (2674)

---

## Batch eval — runs 6–8 (psf/requests, SWE-bench Lite)

Tasks: psf__requests-2674 (retry), 3362, 863

  psf__requests-2674  score=0.90  exceptions.py  NEEDS VERIFY
    Previously crashed on broken_file="n/a". Guard now working.
    Patched Timeout.__init__ in exceptions.py.
    File% unknown until gold patch path confirmed.

  psf__requests-3362  score=0.00  (no patch)     PIPELINE FAILURE
    Coder: "old_code not found in file" on all 3 attempts.
    LLM hallucinated old_code that doesn't exist verbatim in file.
    Self-correction loop exhausted without a single successful match.
    Empty patch guard correctly scored 0.00 (no false positive).

  psf__requests-863   score=1.00  models.py      LIKELY CORRECT
    Patched register_hook to handle list of hooks.
    Plausible for a hooks-merging bug in PreparedRequest.

New failure mode identified:

  Failure 4 — old_code not found (verbatim mismatch)
    LLM generates old_code that is close but not verbatim.
    All 3 self-correction attempts fail.
    Coder produces no patch. Critic correctly scores 0.00.
    Root cause: LLM paraphrases or reformats code instead of
    copying it exactly from the file contents we provide.
    Potential fix: include line numbers in the file excerpt shown
    to the Coder, and instruct it to copy the block exactly as-is.

Metric fix:
  File% was always 0% due to path prefix mismatch.
  Our patches: src/requests/models.py
  Gold patches: requests/models.py
  Fixed patch_similarity() to strip src/, lib/, source/ prefixes
  before comparing. File% now meaningful.

Running tallies (8 tasks):
  Completed without error : 6/8
  Approved (score >= 0.6) : 6/8
  Confirmed false positives: 2 (1734, 2317)
  Likely correct          : 3 (1963, 2148, 863)
  Hard pipeline failures  : 2 (2674 crash fixed; 3362 verbatim fail)
  Needs verification      : 1 (2674 retry)
