from src.state import AgentState


def coder(state: AgentState) -> AgentState:
    print("[coder] stub — generating patch")
    state["patch"] = "--- a/src/example.py\n+++ b/src/example.py\n@@ -1 +1 @@\n-# placeholder\n+# fixed"
    state["retry_count"] = state.get("retry_count", 0)
    state["trace"].append({"agent": "coder", "status": "stub"})
    return state
