import argparse
import json
from src.graph import build_graph
from src.state import initial_state


def main():
    parser = argparse.ArgumentParser(description="Autonomous SWE-Agent")
    parser.add_argument("--issue-url",    required=True,  help="GitHub issue URL")
    parser.add_argument("--issue-body",   required=True,  help="Issue body text")
    parser.add_argument("--instance-id",  required=True,  help="SWE-bench instance ID or any unique run ID")
    parser.add_argument("--eval",         action="store_true", help="Eval mode: skip PR, write patch to file")
    args = parser.parse_args()

    graph = build_graph()

    state = initial_state(
        issue_url=args.issue_url,
        issue_body=args.issue_body,
        instance_id=args.instance_id,
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
