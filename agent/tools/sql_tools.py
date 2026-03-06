"""
SQL 에이전트용 LangChain 도구 (DB 스키마 조회, 쿼리 실행)
안전 규칙: SELECT만 허용, LIMIT 강제, DML 차단
"""

import re
from langchain_core.tools import tool
from sqlalchemy import text

from shared.config import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
from agent.config import SQL_MAX_ROWS


def _get_engine():
    """DB 엔진을 가져옵니다."""
    from sqlalchemy import create_engine
    url = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(url)


# 위험한 키워드 패턴 (SELECT 외 차단)
_DANGEROUS_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE
)


@tool
def list_tables() -> str:
    """DB의 모든 테이블 목록과 설명(COMMENT)을 조회합니다."""
    engine = _get_engine()
    query = text("""
        SELECT 
            t.table_name,
            COALESCE(d.description, '') as comment
        FROM information_schema.tables t
        LEFT JOIN pg_catalog.pg_description d
            ON d.objoid = (SELECT c.oid FROM pg_catalog.pg_class c WHERE c.relname = t.table_name)
            AND d.objsubid = 0
        WHERE t.table_schema = 'public'
        ORDER BY t.table_name;
    """)
    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()
    
    result = "테이블 목록:\n"
    for name, comment in rows:
        result += f"  - {name}: {comment}\n"
    return result


@tool
def get_schema(table_name: str) -> str:
    """특정 테이블의 컬럼명, 타입, 설명(COMMENT)을 조회합니다.
    
    Args:
        table_name: 조회할 테이블 이름
    """
    engine = _get_engine()
    query = text("""
        SELECT 
            c.column_name,
            c.data_type,
            COALESCE(d.description, '') as comment
        FROM information_schema.columns c
        LEFT JOIN pg_catalog.pg_description d
            ON d.objoid = (SELECT cl.oid FROM pg_catalog.pg_class cl WHERE cl.relname = :table_name)
            AND d.objsubid = c.ordinal_position
        WHERE c.table_name = :table_name AND c.table_schema = 'public'
        ORDER BY c.ordinal_position;
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {"table_name": table_name}).fetchall()
    
    if not rows:
        return f"테이블 '{table_name}'을 찾을 수 없습니다."
    
    result = f"테이블 '{table_name}' 스키마:\n"
    for col, dtype, comment in rows:
        result += f"  - {col} ({dtype}): {comment}\n"
    return result


@tool
def execute_query(sql: str) -> str:
    """SQL SELECT 쿼리를 실행하고 결과를 반환합니다.
    INSERT, UPDATE, DELETE 등 데이터 변경 쿼리는 차단됩니다.
    LIMIT이 없으면 자동으로 추가됩니다.
    
    Args:
        sql: 실행할 SQL SELECT 쿼리
    """
    # DML 차단
    if _DANGEROUS_PATTERN.search(sql):
        return "❌ 오류: SELECT 쿼리만 허용됩니다. 데이터 변경 쿼리는 실행할 수 없습니다."
    
    # LIMIT 강제
    if not re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        sql = sql.rstrip().rstrip(";") + f" LIMIT {SQL_MAX_ROWS};"
    
    engine = _get_engine()
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = result.fetchall()
        
        if not rows:
            return "조회 결과가 없습니다."
        
        # 결과를 보기 좋은 형태로 포맷
        output = f"컬럼: {', '.join(columns)}\n총 {len(rows)}건\n\n"
        for row in rows:
            output += " | ".join(str(v) for v in row) + "\n"
        return output
        
    except Exception as e:
        return f"❌ SQL 실행 오류: {e}"


@tool
def check_query(sql: str) -> str:
    """SQL 쿼리의 문법을 EXPLAIN으로 검증합니다. 실제로 실행하지 않고 구문만 확인합니다.
    
    Args:
        sql: 검증할 SQL 쿼리
    """
    if _DANGEROUS_PATTERN.search(sql):
        return "❌ SELECT 쿼리만 검증 가능합니다."
    
    engine = _get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text(f"EXPLAIN {sql}"))
        return "✅ 쿼리 문법이 유효합니다."
    except Exception as e:
        return f"❌ 쿼리 문법 오류: {e}"
