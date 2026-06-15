from src.state import AgentState
from src.config import FIX_SCORE_THRESHOLD, CODER_MAX_RETRIES


def critic(state: AgentState) -> AgentState:
    print("[critic] stub — evaluating patch")
    state["test_results"] = {"passed": 5, "failed": 0, "errors": 0}
    state["fix_score"] = 0.9
    state["trace"].append({"agent": "critic", "status": "stub", "fix_score": state["fix_score"]})
    return state


def route_after_critic(state: AgentState) -> str:
    if state["fix_score"] >= FIX_SCORE_THRESHOLD:
        return "proceed"
    if state["retry_count"] < CODER_MAX_RETRIES:
        return "retry"
    return "fail"
