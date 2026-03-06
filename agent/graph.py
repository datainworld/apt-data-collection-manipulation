"""
메인 Supervisor 그래프 (LangGraph v1 StateGraph 기반)
사용자 질문 → Supervisor → 서브 에이전트 위임 → 최종 응답
"""

import functools
from typing import Literal

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from agent.state import AgentState
from agent.config import DEFAULT_MODEL, TEMPERATURE
from agent.prompts.supervisor import SUPERVISOR_SYSTEM_PROMPT
from agent.agents.sql_agent import create_sql_agent_node
from agent.agents.notebooklm_agent import create_notebooklm_agent_node
from agent.tools.notebooklm_tools import get_mcp_client


# Supervisor가 선택할 수 있는 대상
AGENT_OPTIONS = ["sql_agent", "notebooklm_agent", "FINISH"]


def _make_supervisor_node(llm):
    """Supervisor 노드: 사용자 질문을 분석하여 다음 에이전트를 결정합니다."""
    
    async def supervisor_node(state: AgentState):
        messages = state["messages"]
        
        # Supervisor에게 라우팅 결정을 요청
        routing_prompt = (
            f"{SUPERVISOR_SYSTEM_PROMPT}\n\n"
            f"다음 중 하나를 선택하세요: {AGENT_OPTIONS}\n"
            f"반드시 하나의 에이전트 이름만 답하세요."
        )
        
        response = await llm.ainvoke(
            [{"role": "system", "content": routing_prompt}] + messages
        )
        
        # 응답에서 에이전트 이름 추출
        content = response.content
        if isinstance(content, list):
            content = " ".join([c.get("text", "") for c in content if isinstance(c, dict) and "text" in c])
        content = content.strip()
        next_agent = "FINISH"
        for option in ["sql_agent", "notebooklm_agent"]:
            if option in content.lower():
                next_agent = option
                break
        
        return {"next_agent": next_agent}
    
    return supervisor_node


def _make_agent_node(agent, name: str):
    """서브 에이전트 래퍼 노드: 에이전트 실행 후 상태를 업데이트합니다."""
    
    async def agent_node(state: AgentState):
        result = await agent.ainvoke(state)
        # 에이전트의 마지막 메시지를 AIMessage로 상태에 추가
        last_msg = result["messages"][-1]
        msg_content = last_msg.content
        if isinstance(msg_content, list):
            msg_content = " ".join([c.get("text", "") for c in msg_content if isinstance(c, dict) and "text" in c])
        return {
            "messages": [AIMessage(content=msg_content, name=name)],
            "next_agent": "FINISH",
        }
    
    return agent_node


def _route(state: AgentState) -> Literal["sql_agent", "notebooklm_agent", "__end__"]:
    """Supervisor의 라우팅 결과에 따라 다음 노드를 결정합니다."""
    next_agent = state.get("next_agent", "FINISH")
    if next_agent == "FINISH":
        return "__end__"
    return next_agent


async def build_graph():
    """Supervisor 패턴 멀티에이전트 그래프를 빌드합니다.
    
    MCP 클라이언트와 함께 사용해야 하므로 async context manager 내에서 호출합니다.
    Returns:
        컴파일된 LangGraph 그래프
    """
    llm = ChatGoogleGenerativeAI(
        model=DEFAULT_MODEL,
        temperature=TEMPERATURE,
    )
    
    # SQL 에이전트 생성
    sql_agent = create_sql_agent_node()
    
    # NotebookLM MCP 도구 로드 및 에이전트 생성
    mcp_client = get_mcp_client()
    mcp_tools = await mcp_client.get_tools()
    
    # Gemini 엄격 스키마 검증에서 오류를 유발하는 도구 제외 (예: slide_instructions 빈 배열 이슈)
    filtered_tools = [t for t in mcp_tools if t.name not in ["studio_revise"]]
    nlm_agent = create_notebooklm_agent_node(filtered_tools)
    
    # 그래프 구성
    workflow = StateGraph(AgentState)
    
    # 노드 등록
    workflow.add_node("supervisor", _make_supervisor_node(llm))
    workflow.add_node("sql_agent", _make_agent_node(sql_agent, "sql_agent"))
    workflow.add_node("notebooklm_agent", _make_agent_node(nlm_agent, "notebooklm_agent"))
    
    # 엣지 구성
    workflow.add_edge(START, "supervisor")
    workflow.add_conditional_edges("supervisor", _route)
    workflow.add_edge("sql_agent", "supervisor")
    workflow.add_edge("notebooklm_agent", "supervisor")
    
    # 체크포인터 연결
    memory = MemorySaver()
    graph = workflow.compile(checkpointer=memory)
    
    return graph
