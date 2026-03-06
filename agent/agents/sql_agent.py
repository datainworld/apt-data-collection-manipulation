"""
SQL 에이전트 노드 — 자연어 → SQL 변환 및 DB 데이터 조회
"""

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent

from agent.config import DEFAULT_MODEL, TEMPERATURE
from agent.tools.sql_tools import list_tables, get_schema, execute_query, check_query
from agent.prompts.sql_prompt import SQL_AGENT_SYSTEM_PROMPT


def create_sql_agent_node():
    """SQL 서브 에이전트 노드를 생성합니다."""
    llm = ChatGoogleGenerativeAI(
        model=DEFAULT_MODEL,
        temperature=TEMPERATURE,
    )
    
    tools = [list_tables, get_schema, execute_query, check_query]
    
    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SQL_AGENT_SYSTEM_PROMPT,
    )
    
    return agent
