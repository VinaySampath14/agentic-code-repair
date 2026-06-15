from langgraph.graph import StateGraph, START, END

from src.state import AgentState
from src.agents.planner import planner
from src.agents.explorer import explorer, route_after_explorer
from src.agents.coder import coder
from src.agents.critic import critic, route_after_critic
from src.agents.pr_agent import pr_agent


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner)
    graph.add_node("explorer", explorer)
    graph.add_node("coder", coder)
    graph.add_node("critic", critic)
    graph.add_node("pr_agent", pr_agent)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "explorer")

    graph.add_conditional_edges("explorer", route_after_explorer, {
        "replan": "planner",
        "proceed": "coder",
    })

    graph.add_edge("coder", "critic")

    graph.add_conditional_edges("critic", route_after_critic, {
        "retry": "coder",
        "proceed": "pr_agent",
        "fail": END,
    })

    graph.add_edge("pr_agent", END)

    return graph.compile()
