"""
뉴스 인사이트 API 라우트
뉴스 기사에서 핵심 질문을 추출 → SQL 에이전트로 DB 조회 → 결과 반환
"""

import os
import json
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage

from agent.graph import build_graph
from shared.config import DATA_DIR


router = APIRouter(prefix="/api", tags=["news"])


def _load_today_news():
    """오늘 수집된 뉴스 목록을 로드합니다."""
    today = datetime.now().strftime("%Y-%m-%d")
    filepath = os.path.join(DATA_DIR, f"news_urls_{today}.json")
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/news-insight")
async def news_insight():
    """오늘 뉴스를 기반으로 핵심 질문을 추출하고 DB 데이터로 답변합니다."""
    # 뉴스 데이터 로드
    news_data = _load_today_news()
    if not news_data or not news_data.get("items"):
        return JSONResponse({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "message": "오늘 수집된 뉴스가 없습니다.",
            "insights": [],
        })
    
    # 뉴스 제목 요약 (그래프에 전달할 컨텍스트)
    titles = [item["title"] for item in news_data["items"][:10]]
    news_summary = "\n".join(f"- {t}" for t in titles)
    
    # Supervisor 그래프에 질의
    prompt = (
        f"오늘 주요 부동산 뉴스 제목입니다:\n{news_summary}\n\n"
        f"위 뉴스를 참고하여 현재 DB의 실거래 데이터로 확인할 수 있는 "
        f"핵심 인사이트 3가지를 SQL로 조회하여 알려주세요."
    )
    
    try:
        graph = await build_graph()
        config = {"configurable": {"thread_id": "news-insight"}}
        
        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=prompt)],
                "next_agent": "",
                "query_result": None,
                "is_complete": False,
                "news_context": news_summary,
            },
            config=config,
        )
        
        last_msg = result["messages"][-1]
        
        return JSONResponse({
            "date": news_data.get("date"),
            "news_count": len(news_data.get("items", [])),
            "insights": last_msg.content,
            "news_titles": titles,
        })
        
    except Exception as e:
        return JSONResponse(
            {"error": f"인사이트 생성 오류: {str(e)}"}, status_code=500
        )
