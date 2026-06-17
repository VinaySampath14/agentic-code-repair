# Design Decisions

## Evaluation scope: 50 tasks, stratified

Fixed 50 tasks from SWE-bench Lite, same set across all three configs. Stratified by repo:

- ~15 Django
- ~10 Sympy
- ~8 Matplotlib
- ~8 Scikit-learn
- ~9 other repos

Mix of easy and hard tasks within each repo. The comparison between configs is what matters — 50 tasks is enough to see a real delta without running forever.

---

## `no_regression` is a rate, not binary

```python
no_regression = passing_tests_after / passing_tests_before

fix_score = (0.5 * test_pass_rate) + (0.3 * no_regression) + (0.2 * code_quality)
```

Binary regression (broke any test = 0) is too blunt. A patch that breaks 1 of 10 existing tests scores 0.9 here instead of 0. Also gives a richer distribution to look at — not just pass/fail.

---

## PR Agent has two modes

```
EVAL_MODE=true   -> skips PR Agent, writes patch to predictions/{instance_id}.diff
EVAL_MODE=false  -> runs full pipeline, opens a real GitHub PR
```

SWE-bench evaluates `.diff` files, not PRs. In eval mode the Critic still scores the patch and the full pipeline runs — it just doesn't go to GitHub at the end. Ground-truth evaluation runs through the official SWE-bench Docker harness on the final `.diff` files.

---

## Explorer reruns on two conditions, not one

1. A file Planner listed doesn't exist in the repo (hard 404)
2. Explorer read the files but returned `confidence: low`

The second case is the more interesting one. Explorer successfully reading the wrong files is more common than a hard file-not-found error. Without catching it, Coder just patches whatever it can see rather than what's actually broken. This showed up early in eval as a false positive (patched models.py when sessions.py was the issue).

---

## Explorer reads files iteratively, not all at once

LLM decides what to read next after each iteration. Upfront planning fails because you can't predict import chains before reading anything.

```
Iteration 1: read everything Planner flagged
Iteration 2: LLM decides -- follow imports? read tests? read config?
Iteration 3: LLM decides again
Hard stop:   max 8 files OR max 3 iterations
```

The 8-file cap is the main control for preventing context overflow and eval timeouts. Without it tasks spiralled to 20+ file reads.

---

## LLM semantic scoring when tests can't run

SWE-bench tasks use historical `base_commit` checkouts. At old commits, package incompatibilities (`np.unicode_` removed in NumPy 1.24+, old dask APIs, etc.) cause pytest to collect 0 tests on Windows without Docker.

When that happens, the default formula locks every patch at 0.5 regardless of quality (`test_pass_rate=0`, `no_regression=1.0` from the divide-by-zero guard). So instead:

```python
fix_score = (0.8 * llm_score_patch(state)) + (0.2 * code_quality)
```

This is an internal retry signal — not a ground-truth metric. The official SWE-bench Docker harness handles ground truth on the final `.diff` files. This separation is how all production SWE-bench systems work.
