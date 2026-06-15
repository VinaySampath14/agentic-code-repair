from src.graph import build_graph
from src.state import AgentState

ISSUE_URL = "https://github.com/pallets/flask/issues/1"

def main():
    graph = build_graph()

    initial_state: AgentState = {
        "issue_url": ISSUE_URL,
        "issue_body": "",
        "affected_files": [],
        "file_contents": {},
        "patch": "",
        "test_results": {},
        "fix_score": 0.0,
        "pr_url": "",
        "trace": [],
        "retry_count": 0,
        "error": None,
    }

    print(f"Running agent on: {ISSUE_URL}\n")
    final_state = graph.invoke(initial_state)

    print("\n--- Final State ---")
    print(f"Affected files : {final_state['affected_files']}")
    print(f"Fix score      : {final_state['fix_score']}")
    print(f"PR URL         : {final_state['pr_url']}")
    print(f"Trace          : {final_state['trace']}")

if __name__ == "__main__":
    main()
