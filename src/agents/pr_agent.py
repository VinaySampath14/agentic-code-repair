from src.state import AgentState
from src.config import EVAL_MODE


def pr_agent(state: AgentState) -> AgentState:
    if EVAL_MODE:
        print("[pr_agent] eval mode — skipping PR creation")
        state["trace"].append({"agent": "pr_agent", "status": "skipped_eval_mode"})
        return state

    print("[pr_agent] stub — creating draft PR")
    state["pr_url"] = "https://github.com/stub/repo/pull/1"
    state["trace"].append({"agent": "pr_agent", "status": "stub", "pr_url": state["pr_url"]})
    return state
