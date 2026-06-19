import argparse
import json
import logging
import os
import subprocess
import mlflow
from src.graph import build_graph
from src.state import initial_state
from src.logger import setup_logging
from src.config import MLFLOW_TRACKING_URI

logger = logging.getLogger(__name__)

setup_logging("INFO")


def _fetch_issue_body(issue_url: str) -> str:
    from src.tools.github_tools import _get_repo
    parts = issue_url.rstrip("/").split("/")
    repo_full_name = f"{parts[3]}/{parts[4]}"
    issue_number = int(parts[6])
    repo = _get_repo(repo_full_name)
    issue = repo.get_issue(issue_number)
    return issue.body or ""


def _checkout_base_commit(issue_url: str, base_commit: str) -> None:
    parts = issue_url.rstrip("/").split("/")
    repo_path = os.path.join("repos", f"{parts[3]}__{parts[4]}")
    if not os.path.isdir(repo_path):
        return
    result = subprocess.run(
        f"git checkout {base_commit}",
        shell=True, cwd=repo_path, capture_output=True, text=True,
    )
    if result.returncode == 0:
        logger.info(f"checked out base_commit {base_commit} in {repo_path}")
    else:
        logger.warning(f"git checkout {base_commit} failed: {result.stderr.strip()}")


def _log_to_mlflow(state: dict, instance_id: str) -> None:
    try:
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment("swe-agent-eval")
        test_results = state.get("test_results", {})
        with mlflow.start_run(run_name=instance_id):
            mlflow.log_param("instance_id", instance_id)
            mlflow.log_param("repo",        instance_id.split("__")[0] if "__" in instance_id else "")
            mlflow.log_param("broken_file", state.get("broken_file", ""))
            mlflow.log_metric("fix_score",    state.get("fix_score", 0.0))
            mlflow.log_metric("tests_passed", test_results.get("tests_passed", 0))
            mlflow.log_metric("tests_failed", test_results.get("tests_failed", 0))
            mlflow.log_metric("resolve",      1.0 if state.get("fix_score", 0) >= 0.6 else 0.0)
            run_id = mlflow.active_run().info.run_id
        logger.info(f"MLflow run logged: {run_id}")
        print(f"mlflow_run_id  : {run_id}")
    except Exception as e:
        logger.warning(f"MLflow logging failed (non-fatal): {e}")


def _write_prediction(state: dict) -> str:
    """Write patch to evals/predictions/<instance_id>.diff — empty file if no patch."""
    predictions_dir = os.path.join("evals", "predictions")
    os.makedirs(predictions_dir, exist_ok=True)
    path = os.path.join(predictions_dir, f"{state['instance_id']}.diff")
    patch = state.get("patch", "") or ""
    with open(path, "w", encoding="utf-8") as f:
        f.write(patch)
    logger.info(f"prediction written -> {path} ({len(patch)} chars)")
    return path


def _derive_instance_id(issue_url: str) -> str:
    parts = issue_url.rstrip("/").split("/")
    owner, repo, number = parts[3], parts[4], parts[6]
    return f"{owner}__{repo}-{number}"


def main():
    parser = argparse.ArgumentParser(description="Autonomous SWE-Agent")
    parser.add_argument("--issue-url",    required=True,  help="GitHub issue URL")
    parser.add_argument("--issue-body",   required=False, default=None, help="Issue body text (fetched from GitHub if omitted)")
    parser.add_argument("--instance-id",  required=False, default=None, help="SWE-bench instance ID (derived from URL if omitted)")
    parser.add_argument("--base-commit",   required=False, default=None, help="Git commit to checkout before patching")
    parser.add_argument("--eval",          action="store_true", help="Eval mode: skip PR, write patch to file")
    parser.add_argument("--fail-to-pass",  required=False, default=None, help="JSON list of test IDs that must pass after fix")
    args = parser.parse_args()

    issue_body = args.issue_body or _fetch_issue_body(args.issue_url)
    instance_id = args.instance_id or _derive_instance_id(args.issue_url)

    fail_to_pass = []
    if args.fail_to_pass:
        try:
            fail_to_pass = json.loads(args.fail_to_pass)
        except json.JSONDecodeError:
            logger.warning("could not parse --fail-to-pass JSON, ignoring")

    if args.base_commit:
        _checkout_base_commit(args.issue_url, args.base_commit)

    graph = build_graph()

    state = initial_state(
        issue_url=args.issue_url,
        issue_body=issue_body,
        instance_id=instance_id,
        eval_mode=args.eval,
        fail_to_pass=fail_to_pass,
    )

    print(f"Issue  : {args.issue_url}")
    print(f"Mode   : {'eval' if args.eval else 'live'}\n")

    final = graph.invoke(state)

    # In eval mode, always write a prediction file (even on failure / empty patch)
    if args.eval:
        _write_prediction(final)

    _log_to_mlflow(final, instance_id)

    print("\n--- Result ---")
    print(f"core_problem   : {final['core_problem']}")
    print(f"broken_file    : {final['broken_file']}")
    print(f"fix_score      : {final['fix_score']}")
    print(f"explorer_confidence: {final.get('explorer_confidence', 'n/a')}")
    print(f"retry_count    : {final.get('retry_count', 0) + 1}")
    print(f"pr_url         : {final['pr_url']}")
    print(f"error          : {final['error']}")
    print(f"len(trace)     : {len(final['trace'])}")
    print(f"\nTrace ({len(final['trace'])} steps):")
    for step in final["trace"]:
        print(f"  {step['agent']:15} confidence={step.get('confidence', '-'):6} llm_calls={step.get('llm_calls', 0)}")


if __name__ == "__main__":
    main()
