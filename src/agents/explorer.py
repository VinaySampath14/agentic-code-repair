from src.state import AgentState


def explorer(state: AgentState) -> AgentState:
    print("[explorer] stub — reading files")
    state["file_contents"] = {"src/example.py": "# placeholder content"}
    state["trace"].append({"agent": "explorer", "status": "stub", "confidence": "high"})
    return state


def route_after_explorer(state: AgentState) -> str:
    last = next((t for t in reversed(state["trace"]) if t["agent"] == "explorer"), None)
    if last and last.get("confidence") == "low":
        return "replan"
    return "proceed"
