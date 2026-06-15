from src.state import AgentState


def planner(state: AgentState) -> AgentState:
    print("[planner] stub — identifying affected files")
    state["affected_files"] = ["src/example.py"]
    state["trace"].append({"agent": "planner", "status": "stub"})
    return state
