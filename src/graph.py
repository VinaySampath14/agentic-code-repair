from langgraph.graph import StateGraph, START, END

from src.state import AgentState
from src.agents.planner_agent  import planner_agent
from src.agents.explorer_agent import explorer_agent
from src.agents.coder_agent    import coder_agent
from src.agents.critic_agent   import critic_agent
from src.agents.pr_agent       import pr_agent


def route_after_explorer(state: AgentState) -> str:
    # Errors always proceed — never replan on error (causes infinite loop)
    if state.get("error"):
        return "proceed"
    trace = state.get("trace", [])
    # Count empty explorer runs — if any, files aren't readable, proceed anyway
    empty_explorer_runs = sum(
        1 for t in trace
        if t.get("agent") == "explorer" and len(t.get("files_read", [])) == 0
    )
    if empty_explorer_runs >= 1:
        return "proceed"
    # Cap total replans at 2 — beyond that, proceed with what we have
    planner_runs = sum(1 for t in trace if t.get("agent") == "planner")
    if planner_runs >= 2:
        return "proceed"
    if state.get("explorer_confidence") == "low":
        return "replan"
    return "proceed"


def route_after_critic(state: AgentState) -> str:
    if state.get("error"):
        return "fail"
    decision = state.get("test_results", {}).get("decision")
    if decision == "approve":
        return "proceed"
    if decision == "fail":
        return "fail"
    return "retry"


def increment_retry(state: AgentState) -> AgentState:
    state["retry_count"] += 1
    return state


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("planner",         planner_agent)
    graph.add_node("explorer",        explorer_agent)
    graph.add_node("coder",           coder_agent)
    graph.add_node("critic",          critic_agent)
    graph.add_node("increment_retry", increment_retry)
    graph.add_node("pr_agent",        pr_agent)

    graph.add_edge(START,             "planner")
    graph.add_edge("planner",         "explorer")

    graph.add_conditional_edges("explorer", route_after_explorer, {
        "replan":  "planner",
        "proceed": "coder",
    })

    graph.add_edge("coder", "critic")

    graph.add_conditional_edges("critic", route_after_critic, {
        "retry":   "increment_retry",
        "proceed": "pr_agent",
        "fail":    END,
    })

    graph.add_edge("increment_retry", "coder")
    graph.add_edge("pr_agent",        END)

    return graph.compile()
