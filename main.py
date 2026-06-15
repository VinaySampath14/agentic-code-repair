import argparse
import json
import logging
import os
import subprocess
from src.graph import build_graph
from src.state import initial_state
from src.logger import setup_logging

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


def _derive_instance_id(issue_url: str) -> str:
    parts = issue_url.rstrip("/").split("/")
    owner, repo, number = parts[3], parts[4], parts[6]
    return f"{owner}__{repo}-{number}"


def main():
    parser = argparse.ArgumentParser(description="Autonomous SWE-Agent")
    parser.add_argument("--issue-url",    required=True,  help="GitHub issue URL")
    parser.add_argument("--issue-body",   required=False, default=None, help="Issue body text (fetched from GitHub if omitted)")
    parser.add_argument("--instance-id",  required=False, default=None, help="SWE-bench instance ID (derived from URL if omitted)")
    parser.add_argument("--base-commit",  required=False, default=None, help="Git commit to checkout before patching")
    parser.add_argument("--eval",         action="store_true", help="Eval mode: skip PR, write patch to file")
    args = parser.parse_args()

    issue_body = args.issue_body or _fetch_issue_body(args.issue_url)
    instance_id = args.instance_id or _derive_instance_id(args.issue_url)

    if args.base_commit:
        _checkout_base_commit(args.issue_url, args.base_commit)

    graph = build_graph()

    state = initial_state(
        issue_url=args.issue_url,
        issue_body=issue_body,
        instance_id=instance_id,
        eval_mode=args.eval,
    )

    print(f"Issue  : {args.issue_url}")
    print(f"Mode   : {'eval' if args.eval else 'live'}\n")

    final = graph.invoke(state)

    print("\n--- Result ---")
    print(f"core_problem   : {final['core_problem']}")
    print(f"broken_file    : {final['broken_file']}")
    print(f"fix_score      : {final['fix_score']}")
    print(f"pr_url         : {final['pr_url']}")
    print(f"error          : {final['error']}")
    print(f"\nTrace ({len(final['trace'])} steps):")
    for step in final["trace"]:
        print(f"  {step['agent']:15} confidence={step.get('confidence', '-'):6} llm_calls={step.get('llm_calls', 0)}")


if __name__ == "__main__":
    main()
