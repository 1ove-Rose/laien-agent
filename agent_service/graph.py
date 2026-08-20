from langgraph.graph import END, START, StateGraph

from .agents.classification import classification_agent
from .agents.critic import critic_failure, evidence_critic
from .agents.insight import insight_agent, insight_revision_agent
from .agents.prd import prd_planner
from .agents.test_designer import test_designer
from .agents.traceability import traceability_validator
from .state import AnalysisState


def route_after_critic(state):
    if state.get("criticPassed"):
        return "prd"
    if state.get("iteration", 0) < 1:
        return "revise"
    return "fail"


def build_graph(llm):
    graph = StateGraph(AnalysisState)

    async def classification_node(state, writer=None):
        return await classification_agent(state, llm, writer)

    async def insight_node(state, writer=None):
        return await insight_agent(state, llm, writer)

    async def critic_node(state, writer=None):
        return await evidence_critic(state, llm, writer)

    async def revision_node(state, writer=None):
        return await insight_revision_agent(state, llm, writer)

    async def prd_node(state, writer=None):
        return await prd_planner(state, llm, writer)

    async def test_node(state, writer=None):
        return await test_designer(state, llm, writer)

    graph.add_node("classification_agent", classification_node)
    graph.add_node("insight_agent", insight_node)
    graph.add_node("evidence_critic", critic_node)
    graph.add_node("insight_revision_agent", revision_node)
    graph.add_node("critic_failure", critic_failure)
    graph.add_node("prd_planner", prd_node)
    graph.add_node("test_designer", test_node)
    graph.add_node("traceability_validator", traceability_validator)

    graph.add_edge(START, "classification_agent")
    graph.add_edge("classification_agent", "insight_agent")
    graph.add_edge("insight_agent", "evidence_critic")
    graph.add_conditional_edges(
        "evidence_critic",
        route_after_critic,
        {"prd": "prd_planner", "revise": "insight_revision_agent", "fail": "critic_failure"},
    )
    graph.add_edge("insight_revision_agent", "evidence_critic")
    graph.add_edge("critic_failure", END)
    graph.add_edge("prd_planner", "test_designer")
    graph.add_edge("test_designer", "traceability_validator")
    graph.add_edge("traceability_validator", END)
    return graph.compile()
