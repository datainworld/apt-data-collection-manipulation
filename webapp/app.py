"""
FastAPI 웹 애플리케이션 메인 서버
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from webapp.routes.chat import router as chat_router
from webapp.routes.news_insight import router as news_router

app = FastAPI(
    title="APT Insight Platform",
    description="아파트 실거래가·매물 AI 분석 플랫폼",
    version="0.2.0",
)

# 정적 파일 서빙
app.mount("/static", StaticFiles(directory="webapp/static"), name="static")

# 템플릿 엔진
templates = Jinja2Templates(directory="webapp/templates")

# 라우터 등록
app.include_router(chat_router)
app.include_router(news_router)

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "ok"}

