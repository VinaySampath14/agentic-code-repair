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
