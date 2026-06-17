"""
run_eval.py -- Run the pipeline against SWE-bench Lite tasks and report results.

Usage:
    python run_eval.py                              # 5 tasks from psf/requests
    python run_eval.py --n 10                       # 10 tasks from psf/requests
    python run_eval.py --repo django/django --n 3   # from a different repo
    python run_eval.py --tasks psf__requests-1734,psf__requests-1789
"""

import argparse
import json
import os
import subprocess
import sys
import time

# Windows consoles default to CP1252; MLflow emits emoji — force UTF-8 throughout.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PREDICTIONS_DIR = os.path.join("evals", "predictions")
RESULTS_PATH    = os.path.join("evals", "results.json")


# Repos confirmed working — used when --repos flag is passed
WORKING_REPOS = [
    "psf/requests",          # 3/6 approved, avg 0.68 — best performer
    "astropy/astropy",       # 4/4 coder success
    "mwaskom/seaborn",       # 3/3 coder success
    "pylint-dev/pylint",     # ~2/4 coder success
    "pallets/flask",         # 1/2 coder success
    "django/django",         # large pool, mixed success
]


def load_tasks(n: int, repo: str, task_ids: list[str] | None, force: bool = False, repos: list[str] | None = None) -> list[dict]:
    from datasets import load_dataset
    print("Loading SWE-bench Lite dataset from HuggingFace...")
    ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    tasks = list(ds)

    if task_ids:
        tasks = [t for t in tasks if t["instance_id"] in task_ids]
    elif repos:
        tasks = [t for t in tasks if t["repo"] in repos]
        # Interleave by repo for spread
        by_repo: dict[str, list] = {}
        for t in tasks:
            by_repo.setdefault(t["repo"], []).append(t)
        interleaved: list[dict] = []
        while any(by_repo.values()):
            for r in list(by_repo.keys()):
                if by_repo[r]:
                    interleaved.append(by_repo[r].pop(0))
                if not by_repo[r]:
                    del by_repo[r]
        tasks = interleaved
    else:
        tasks = [t for t in tasks if t["repo"] == repo]

    # Skip tasks that already have a prediction (unless --force)
    if not force:
        existing = {
            f.replace(".diff", "")
            for f in os.listdir(PREDICTIONS_DIR)
            if f.endswith(".diff")
        }
        tasks = [t for t in tasks if t["instance_id"] not in existing]

    return tasks[:n]


def run_task(task: dict) -> dict:
    instance_id       = task["instance_id"]
    repo              = task["repo"]
    problem_statement = task["problem_statement"]

    # Derive a usable issue URL -- repo identity is what matters for cloning
    number    = instance_id.split("-")[-1]
    issue_url = f"https://github.com/{repo}/issues/{number}"

    print(f"\n{'='*60}")
    print(f"Task    : {instance_id}")
    print(f"Repo    : {repo}")
    print(f"{'='*60}")

    base_commit = task.get("base_commit", "")
    fail_to_pass = task.get("FAIL_TO_PASS", "[]")
    cmd = [
        sys.executable, "main.py",
        "--issue-url",    issue_url,
        "--issue-body",   problem_statement,
        "--instance-id",  instance_id,
        "--eval",
        "--fail-to-pass", fail_to_pass if isinstance(fail_to_pass, str) else json.dumps(fail_to_pass),
    ]
    if base_commit:
        cmd += ["--base-commit", base_commit]

    start = time.time()
    proc  = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    elapsed = round(time.time() - start, 1)

    # Echo output so the user can follow along
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)

    parsed = _parse_stdout(proc.stdout)
    parsed["instance_id"] = instance_id
    parsed["repo"]        = repo
    parsed["elapsed_s"]   = elapsed
    parsed["gold_patch"]  = task.get("patch", "")
    parsed["fail_to_pass"] = task.get("FAIL_TO_PASS", "[]")
    return parsed


def _parse_stdout(output: str | None) -> dict:
    result = {"fix_score": 0.0, "error": None, "broken_file": "", "pr_url": ""}
    for line in (output or "").splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if key == "fix_score":
            try:
                result["fix_score"] = float(val)
            except ValueError:
                pass
        elif key == "error":
            result["error"] = None if val == "None" else val
        elif key == "broken_file":
            result["broken_file"] = val
        elif key == "pr_url":
            result["pr_url"] = val
    return result


def patch_similarity(pred_path: str, gold_patch: str) -> float:
    """Fraction of gold-patched files also touched by prediction (path-prefix agnostic)."""
    if not os.path.exists(pred_path) or not gold_patch:
        return 0.0

    _PREFIX_STRIP = ("src/", "lib/", "source/")

    def normalise(path: str) -> str:
        for prefix in _PREFIX_STRIP:
            if path.startswith(prefix):
                return path[len(prefix):]
        return path

    def files_in_patch(text: str) -> set[str]:
        return {
            normalise(line[6:])  # strip "--- a/" then normalise
            for line in text.splitlines()
            if line.startswith("--- a/")
        }

    with open(pred_path) as f:
        pred_text = f.read()

    pred_files = files_in_patch(pred_text)
    gold_files = files_in_patch(gold_patch)
    if not gold_files:
        return 0.0
    return len(pred_files & gold_files) / len(gold_files)


def save_results(results: list[dict]) -> None:
    """Upsert results into results.json — safe to call after every task."""
    os.makedirs("evals", exist_ok=True)
    existing = []
    if os.path.exists(RESULTS_PATH):
        with open(RESULTS_PATH) as f:
            existing = json.load(f)
    by_id = {r["instance_id"]: r for r in existing}
    for r in results:
        by_id[r["instance_id"]] = {k: v for k, v in r.items() if k != "gold_patch"}
    with open(RESULTS_PATH, "w") as f:
        json.dump(list(by_id.values()), f, indent=2)


def print_summary(results: list[dict]) -> None:
    print(f"\n{'='*75}")
    print(f"{'EVAL SUMMARY':^75}")
    print(f"{'='*75}")
    header = f"{'Instance':<35} {'Score':>5}  {'File%':>5}  {'Time':>6}  Error"
    print(header)
    print("-" * 75)

    for r in results:
        pred_path = os.path.join(PREDICTIONS_DIR, f"{r['instance_id']}.diff")
        file_pct  = patch_similarity(pred_path, r.get("gold_patch", ""))
        error     = (r["error"] or "")[:18] if r["error"] else "-"
        print(
            f"{r['instance_id']:<35} {r['fix_score']:>5.2f}  "
            f"{file_pct:>4.0%}   {r['elapsed_s']:>5}s  {error}"
        )

    scores   = [r["fix_score"] for r in results]
    approved = sum(1 for r in results if r["fix_score"] >= 0.6 and not r["error"])
    avg      = sum(scores) / len(scores) if scores else 0.0
    print("-" * 75)
    print(
        f"Tasks: {len(results)}  |  Approved (score>=0.6): {approved}/{len(results)}  "
        f"|  Avg score: {avg:.3f}"
    )
    print("=" * 75)
    save_results(results)
    print(f"\nResults saved -> {RESULTS_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Eval runner for SWE-bench Lite")
    parser.add_argument("--n",        type=int, default=5,              help="Max tasks to run")
    parser.add_argument("--repo",     type=str, default="psf/requests", help="Filter by single repo")
    parser.add_argument("--tasks",    type=str, default=None,           help="Comma-separated instance IDs")
    parser.add_argument("--force",    action="store_true",              help="Re-run even if prediction already exists")
    parser.add_argument("--working",  action="store_true",              help="Use only confirmed-working repos (WORKING_REPOS list)")
    args = parser.parse_args()

    os.makedirs(PREDICTIONS_DIR, exist_ok=True)

    task_ids = [t.strip() for t in args.tasks.split(",")] if args.tasks else None
    repos    = WORKING_REPOS if args.working else None
    repo     = None if (task_ids or repos) else args.repo

    tasks = load_tasks(args.n, repo=repo, task_ids=task_ids, force=args.force, repos=repos)
    if not tasks:
        print("No tasks to run -- all already predicted or no matches found.")
        print_summary(results)
        return

    print(f"Running {len(tasks)} task(s)...\n")

    results = []
    for i, task in enumerate(tasks):
        if i > 0:
            time.sleep(15)  # avoid TPM rate limit between tasks
        try:
            results.append(run_task(task))
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT: {task['instance_id']}")
            results.append({
                "instance_id": task["instance_id"],
                "repo":        task["repo"],
                "fix_score":   0.0,
                "error":       "timeout (600s)",
                "elapsed_s":   600,
                "gold_patch":  task.get("patch", ""),
            })
        except Exception as e:
            print(f"ERROR: {task['instance_id']} -- {e}")
            results.append({
                "instance_id": task["instance_id"],
                "repo":        task["repo"],
                "fix_score":   0.0,
                "error":       str(e),
                "elapsed_s":   0,
                "gold_patch":  task.get("patch", ""),
            })
        # Save after every task so interrupts don't lose progress
        save_results(results)

    print_summary(results)


if __name__ == "__main__":
    main()
