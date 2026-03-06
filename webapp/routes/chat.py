"""
채팅 API 라우트 — 사용자 자연어 질문을 Supervisor 그래프에 전달
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage

from agent.graph import build_graph


router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(request: Request):
    """사용자 질문을 Supervisor 그래프에 전달하고 결과를 반환합니다."""
    body = await request.json()
    question = body.get("question", "")
    thread_id = body.get("thread_id", "default")
    
    if not question:
        return JSONResponse({"error": "질문을 입력해주세요."}, status_code=400)
    
    try:
        graph = await build_graph()
        config = {"configurable": {"thread_id": thread_id}}
        
        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=question)],
                "next_agent": "",
                "query_result": None,
                "is_complete": False,
                "news_context": None,
            },
            config=config,
        )
        
        # 마지막 AI 메시지를 응답으로 반환
        last_msg = result["messages"][-1]
        return JSONResponse({
            "answer": last_msg.content,
            "thread_id": thread_id,
        })
        
    except Exception as e:
        return JSONResponse({"error": f"처리 중 오류: {str(e)}"}, status_code=500)
