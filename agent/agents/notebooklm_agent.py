"""
NotebookLM 에이전트 노드 — 뉴스 기반 리서치·요약, 노트북 관리
MCP 서버(stdio)를 통해 NotebookLM과 연동합니다.
"""

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent

from agent.config import DEFAULT_MODEL, TEMPERATURE


NOTEBOOKLM_AGENT_PROMPT = """당신은 NotebookLM 연동 에이전트입니다.
Google NotebookLM을 통해 뉴스 기사와 문서를 관리하고, AI 기반 분석·요약을 수행합니다.

## 주요 역할

1. **노트북 관리**: 노트북 생성, 목록 조회
2. **소스 추가**: 뉴스 기사 URL을 노트북에 등록
3. **AI 질의**: 등록된 소스 기반 질문 응답, 요약, 인사이트 도출

## 응답 규칙

- 항상 한국어로 응답하세요.
- 뉴스 요약 시 핵심 포인트를 간결하게 정리하세요.
- 출처(뉴스 제목, URL)를 함께 제공하세요.
"""


def create_notebooklm_agent_node(mcp_tools):
    """NotebookLM 서브 에이전트 노드를 생성합니다.
    
    Args:
        mcp_tools: MCP 클라이언트에서 가져온 LangChain Tool 리스트
    """
    llm = ChatGoogleGenerativeAI(
        model=DEFAULT_MODEL,
        temperature=TEMPERATURE,
    )
    
    agent = create_react_agent(
        model=llm,
        tools=mcp_tools,
        prompt=NOTEBOOKLM_AGENT_PROMPT,
    )
    
    return agent
