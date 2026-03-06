"""
네이버 검색 API를 통한 아파트 관련 뉴스 수집 파이프라인
매일 '아파트 거래' 관련 뉴스 30건을 수집하여 JSON으로 저장합니다.
"""

import os
import sys
import json
import time
import requests
from datetime import datetime

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from shared.config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, DATA_DIR


SEARCH_QUERIES = ["아파트 거래", "아파트 매매", "부동산 시장"]
TARGET_COUNT = 30  # 최종 수집 목표 건수


def search_naver_news(query, display=30, sort="sim"):
    """네이버 검색 API로 뉴스를 조회합니다.
    
    Args:
        query: 검색어
        display: 결과 개수 (최대 100)
        sort: 정렬 기준 ('sim'=관련도순, 'date'=최신순)
    Returns:
        뉴스 아이템 리스트
    """
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": query,
        "display": display,
        "sort": sort,
    }
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as e:
        print(f"  ⚠ 검색 실패 ({query}): {e}")
        return []


def collect_news():
    """여러 검색어로 뉴스를 수집하고 중복 제거 후 30건을 선별합니다."""
    print("=" * 60)
    print("  네이버 뉴스 수집 파이프라인")
    print("=" * 60)
    
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("[ERROR] NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET이 설정되지 않았습니다.")
        return None
    
    all_items = []
    seen_links = set()
    
    for query in SEARCH_QUERIES:
        # 관련도순 + 최신순 각각 수집
        for sort_type in ["sim", "date"]:
            print(f"  검색: '{query}' (정렬: {sort_type})")
            items = search_naver_news(query, display=30, sort=sort_type)
            
            for item in items:
                link = item.get("originallink") or item.get("link", "")
                if link and link not in seen_links:
                    seen_links.add(link)
                    # HTML 태그 제거
                    title = item.get("title", "").replace("<b>", "").replace("</b>", "")
                    description = item.get("description", "").replace("<b>", "").replace("</b>", "")
                    
                    all_items.append({
                        "title": title,
                        "url": link,
                        "description": description,
                        "pub_date": item.get("pubDate", ""),
                        "source": query,
                        "sort": sort_type,
                    })
            
            time.sleep(0.2)  # API 호출 간 딜레이
    
    print(f"\n  수집 완료: 총 {len(all_items)}건 (중복 제거 후)")
    
    # 최종 30건 선별 (관련도순 우선, 나머지는 최신순으로 채움)
    sim_items = [i for i in all_items if i["sort"] == "sim"]
    date_items = [i for i in all_items if i["sort"] == "date"]
    
    selected = []
    seen_final = set()
    
    # 관련도순 우선 추가
    for item in sim_items:
        if item["url"] not in seen_final and len(selected) < TARGET_COUNT:
            seen_final.add(item["url"])
            selected.append(item)
    
    # 부족분은 최신순으로 채움
    for item in date_items:
        if item["url"] not in seen_final and len(selected) < TARGET_COUNT:
            seen_final.add(item["url"])
            selected.append(item)
    
    print(f"  최종 선별: {len(selected)}건")
    return selected


def save_news(news_items):
    """수집된 뉴스를 JSON 파일로 저장합니다."""
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"news_urls_{today}.json"
    filepath = os.path.join(DATA_DIR, filename)
    
    output = {
        "date": today,
        "count": len(news_items),
        "items": news_items,
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"  저장 완료: {filepath}")
    return filepath


def main():
    news_items = collect_news()
    if news_items:
        filepath = save_news(news_items)
        print(f"\n  ✅ {len(news_items)}건 뉴스 수집 완료 → {filepath}")
    else:
        print("\n  ❌ 뉴스 수집 실패")


if __name__ == "__main__":
    main()
