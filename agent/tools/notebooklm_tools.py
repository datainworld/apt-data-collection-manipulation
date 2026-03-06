"""
NotebookLM MCP 도구를 LangChain Tool로 래핑합니다.
notebooklm-mcp-cli 패키지의 MCP 서버(stdio)에 연결하여
노트북 조회, 생성, URL 소스 추가, AI 질의 등을 수행합니다.
"""

import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from agent.config import NOTEBOOKLM_MCP_COMMAND


# MCP 서버 설정 (stdio 방식)
MCP_SERVER_CONFIG = {
    "notebooklm": {
        "command": "uvx",
        "args": ["--from", "notebooklm-mcp-cli", "notebooklm-mcp"],
        "transport": "stdio",
    }
}


def get_mcp_client():
    """MCP 클라이언트 인스턴스를 반환합니다."""
    return MultiServerMCPClient(MCP_SERVER_CONFIG)

