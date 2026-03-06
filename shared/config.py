"""
환경변수 로드 및 프로젝트 공통 설정
"""

import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# API 키
DATA_API_KEY = os.getenv("DATA_API_KEY")
KAKAO_API_KEY = os.getenv("KAKAO_API_KEY")

# LLM 관련
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

if GOOGLE_API_KEY:
    os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY

# 네이버 검색 API
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# PostgreSQL 설정
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "postgres")

# 데이터 디렉토리
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datas")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
