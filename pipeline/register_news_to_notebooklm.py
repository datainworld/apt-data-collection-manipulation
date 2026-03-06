"""
수집된 뉴스 URL을 NotebookLM에 자동 등록하는 스크립트
nlm CLI를 subprocess로 호출하여 노트북 생성 + URL 소스 추가를 수행합니다.
"""

import os
import sys
import json
import subprocess
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from shared.config import DATA_DIR


def find_today_news():
    """오늘 수집된 뉴스 JSON 파일을 찾습니다."""
    today = datetime.now().strftime("%Y-%m-%d")
    filepath = os.path.join(DATA_DIR, f"news_urls_{today}.json")
    if os.path.exists(filepath):
        return filepath
    return None


def run_nlm(*args):
    """nlm CLI 명령어를 실행합니다."""
    cmd = ["uvx", "--from", "notebooklm-mcp-cli", "nlm", *args] if not _nlm_available() else ["nlm", *args]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, encoding="utf-8"
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "타임아웃", 1
    except Exception as e:
        return str(e), 1


def _nlm_available():
    """nlm이 PATH에 있는지 확인합니다."""
    try:
        subprocess.run(["nlm", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _parse_notebook_id(output):
    """노트북 생성 출력에서 ID를 추출합니다."""
    import re
    match = re.search(r"ID:\s*([a-f0-9\-]+)", output)
    return match.group(1) if match else None


def main():
    print("=" * 60)
    print("  뉴스 → NotebookLM 자동 등록")
    print("=" * 60)
    
    # 오늘 뉴스 파일 찾기
    news_file = find_today_news()
    if not news_file:
        print("[ERROR] 오늘 수집된 뉴스 파일이 없습니다. collect_news.py를 먼저 실행하세요.")
        return
    
    with open(news_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    items = data.get("items", [])
    today = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    print(f"  뉴스 파일: {news_file} ({len(items)}건)")
    
    if not items:
        print("  등록할 뉴스가 없습니다.")
        return
    
    # 1. 노트북 생성
    notebook_name = f"아파트뉴스_{today}"
    print(f"\n[1] 노트북 생성: '{notebook_name}'")
    output, code = run_nlm("notebook", "create", notebook_name)
    print(f"  > {output}")
    
    # 노트북 ID 추출 (소스 추가에 ID 사용)
    notebook_id = _parse_notebook_id(output)
    if not notebook_id:
        print("  ⚠ 노트북 ID를 파싱할 수 없습니다. 노트북 이름으로 시도합니다.")
        notebook_id = notebook_name
    else:
        print(f"  노트북 ID: {notebook_id}")
    
    # 2. URL 소스 추가
    print(f"\n[2] URL 소스 등록 ({len(items)}건)")
    success = 0
    fail = 0
    
    for i, item in enumerate(items):
        url = item.get("url", "")
        title = item.get("title", "")
        
        if not url:
            continue
        
        print(f"  ({i+1}/{len(items)}) {title[:40]}...")
        output, code = run_nlm("source", "add", notebook_id, "--url", url)
        
        if code == 0:
            success += 1
        else:
            fail += 1
            print(f"    ⚠ 실패: {output[:80]}")
        
        time.sleep(1)  # API 호출 간 딜레이
    
    print(f"\n  ✅ 등록 완료: 성공 {success}건, 실패 {fail}건")
    print(f"  노트북: '{notebook_name}' (ID: {notebook_id})")


if __name__ == "__main__":
    main()
