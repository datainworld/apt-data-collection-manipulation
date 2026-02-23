"""
네이버 부동산 매물 데이터 수집 스크립트
- 서울/경기/인천 아파트 매물을 증분 방식으로 수집
- 기존 apt_id와 네이버 complexNo 매핑
- PostgreSQL DB 저장 (text-to-SQL 최적화)
- 수집 완료 후 상세 결과보고서 생성

사용법:
    python collect_naver_listing.py                    # 전체 수집 + DB 저장
    python collect_naver_listing.py --skip-db          # DB 저장 생략
    python collect_naver_listing.py --test              # 테스트 모드 (1개 구만 수집)
"""

import os
import re
import sys
import time
import math
import random
import argparse
import pandas as pd
from datetime import datetime, date
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from curl_cffi import requests as curl_requests
from sqlalchemy import text

from utils import get_db_engine, get_latest_file, get_today_str, DATA_DIR


# ==============================================================================
# 상수 및 설정
# ==============================================================================

# 네이버 부동산 API 기본 URL
BASE_URL = "https://new.land.naver.com/api"

# HTTP 요청 헤더
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://new.land.naver.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

# 대상 지역 시도 코드 (네이버 cortarNo)
SIDO_CODES = {
    "서울특별시": "1100000000",
    "경기도": "4100000000",
    "인천광역시": "2800000000",
}

# 거래 유형
TRADE_TYPES = {
    "A1": "매매",
    "B1": "전세",
    "B2": "월세",
}

# Rate Limiting 설정
MIN_DELAY = 1.5   # 최소 대기 시간 (초)
MAX_DELAY = 3.5   # 최대 대기 시간 (초)
MAX_RETRIES = 5   # 최대 재시도 횟수
MAX_WORKERS = 5   # 병렬 처리 워커 수


# ==============================================================================
# HTTP 요청 유틸리티
# ==============================================================================

# 세션 객체 (curl_cffi - Chrome TLS fingerprint 모방)
_session = curl_requests.Session(impersonate="chrome")
_session.headers.update(HEADERS)

# 세션 초기화 플래그
_session_initialized = False


def _init_session():
    """네이버 부동산 API 세션 초기화
    
    curl_cffi의 Chrome TLS fingerprint로 봇 감지를 우회하고,
    메인 페이지 HTML에서 JWT 토큰을 추출하여 Authorization 헤더를 설정합니다.
    """
    global _session_initialized
    if _session_initialized:
        return

    print("  세션 초기화 중 (Chrome TLS fingerprint 모방)...")

    # 1단계: 메인 페이지 방문 → 쿠키 + JWT 토큰 획득
    try:
        resp = _session.get("https://new.land.naver.com/", timeout=30)
        print(f"    메인 페이지: {resp.status_code}")

        # HTML에서 JWT 토큰 추출
        html = resp.text
        token_match = re.search(r'"token"\s*:\s*"([^"]+)"', html)
        if token_match:
            token = token_match.group(1)
            _session.headers["authorization"] = f"Bearer {token}"
            print(f"    JWT 토큰 획득: {token[:50]}...")
        else:
            print("    ⚠ JWT 토큰을 HTML에서 찾지 못했습니다. articles API 사용 불가.")

        time.sleep(2)
    except Exception as e:
        print(f"    메인 페이지 방문 실패: {e}")

    # 2단계: .env 쿠키가 있으면 추가 로드 (보조)
    cookie_str = os.getenv("NAVER_LAND_COOKIE", "")
    if cookie_str:
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                key, _, val = part.partition("=")
                _session.cookies.set(key.strip(), val.strip())

    # 획득된 쿠키 확인
    print(f"    쿠키: {list(_session.cookies.keys())}")

    _session_initialized = True
    print("  세션 초기화 완료")


def _request_with_retry(url, params=None, retries=MAX_RETRIES):
    """네이버 부동산 API 요청 (재시도 + 지수 백오프)"""
    _init_session()

    for attempt in range(retries):
        try:
            # 요청 간 랜덤 딜레이
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

            resp = _session.get(url, params=params, timeout=30)

            if resp.status_code == 429:
                wait = (2 ** attempt) * 5
                print(f"  Rate limit (429). {attempt+1}/{retries}회 재시도, {wait}초 대기...")
                time.sleep(wait)
                continue

            if resp.status_code == 404:
                return None

            resp.raise_for_status()

            # JSON 파싱 시도
            try:
                return resp.json()
            except ValueError:
                return None

        except Exception as e:
            if attempt < retries - 1:
                wait = (2 ** attempt) * 2
                print(f"  요청 실패 ({attempt+1}/{retries}): {e}, {wait}초 후 재시도")
                time.sleep(wait)
            else:
                print(f"  최종 실패: {url}")
                return None

    return None


# ==============================================================================
# 문자열 유틸리티
# ==============================================================================

def _normalize_name(s):
    """단지명 정규화 (아파트, 공백, 괄호, 특수문자 제거)"""
    if not isinstance(s, str):
        return ""
    s = re.sub(r'아파트', '', s)
    s = re.sub(r'\s+', '', s)
    s = re.sub(r'\(.*?\)', '', s)
    s = re.sub(r'[·\-]', '', s)
    return s.strip()


def _parse_price(price_str):
    """네이버 가격 문자열을 만원 단위 정수로 변환
    예: '9억 5,000' → 95000, '45,000' → 45000, '9억' → 90000
    """
    if not price_str or not isinstance(price_str, str):
        return 0
    price_str = price_str.strip().replace(',', '')

    total = 0
    # '억' 단위 처리
    eok_match = re.search(r'(\d+)억', price_str)
    if eok_match:
        total += int(eok_match.group(1)) * 10000

    # 억 뒤의 나머지 숫자 또는 억이 없는 경우 전체 숫자
    remaining = re.sub(r'\d+억\s*', '', price_str).strip()
    if remaining:
        num_match = re.search(r'(\d+)', remaining)
        if num_match:
            total += int(num_match.group(1))
    elif not eok_match:
        # 억이 없고 그냥 숫자만 있는 경우
        num_match = re.search(r'(\d+)', price_str)
        if num_match:
            total = int(num_match.group(1))

    return total


def _haversine_distance(lat1, lon1, lat2, lon2):
    """두 좌표 간 거리 계산 (미터 단위)"""
    R = 6371000  # 지구 반경 (m)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ==============================================================================
# Step 1: 지역코드 수집
# ==============================================================================

def get_cortars():
    """서울/경기/인천의 시군구 → 읍면동 코드를 계층적으로 수집"""
    print("\n[Step 1] 지역코드(cortarNo) 수집")
    all_dongs = []
    sgg_count = 0

    for sido_name, sido_code in SIDO_CODES.items():
        print(f"  {sido_name} ({sido_code})...")
        # 시군구 목록
        data = _request_with_retry(
            f"{BASE_URL}/regions/list", params={"cortarNo": sido_code}
        )
        if not data or "regionList" not in data:
            print(f"    시군구 목록 조회 실패")
            continue

        sgg_list = data["regionList"]
        sgg_count += len(sgg_list)
        print(f"    시군구 {len(sgg_list)}개 발견")

        for sgg in sgg_list:
            sgg_code = sgg.get("cortarNo", "")
            sgg_name = sgg.get("cortarName", "")

            # 읍면동 목록
            dong_data = _request_with_retry(
                f"{BASE_URL}/regions/list", params={"cortarNo": sgg_code}
            )
            if not dong_data or "regionList" not in dong_data:
                continue

            for dong in dong_data["regionList"]:
                all_dongs.append({
                    "sido_name": sido_name,
                    "sgg_name": sgg_name,
                    "sgg_code": sgg_code,
                    "dong_name": dong.get("cortarName", ""),
                    "dong_code": dong.get("cortarNo", ""),
                    "center_lat": dong.get("centerLat", 0),
                    "center_lon": dong.get("centerLon", 0),
                })

    print(f"  총 {len(all_dongs)}개 읍면동 수집 완료 (시군구 {sgg_count}개)")
    return all_dongs, sgg_count


# ==============================================================================
# Step 2: 단지 목록 수집 (/api/regions/complexes)
# ==============================================================================

def get_active_complexes(dong_list, test_mode=False):
    """동별 단지 목록 수집 (/api/regions/complexes)"""
    print("\n[Step 2] 단지 목록 수집 (/api/regions/complexes)")
    complexes = {}  # complexNo → 정보 딕셔너리 (중복 제거)

    targets = dong_list[:10] if test_mode else dong_list

    for i, dong in enumerate(targets):
        if (i + 1) % 50 == 0 or i == 0:
            print(f"  진행: {i+1}/{len(targets)} ({dong['sido_name']} {dong['sgg_name']} {dong['dong_name']})")

        data = _request_with_retry(
            f"{BASE_URL}/regions/complexes",
            params={
                "cortarNo": dong["dong_code"],
                "realEstateType": "APT",
                "order": "",
            }
        )

        if not data:
            continue

        # complexList 파싱
        complex_list = data.get("complexList", [])
        if not isinstance(complex_list, list):
            continue

        for cpx in complex_list:
            complex_no = str(cpx.get("complexNo", ""))
            if not complex_no:
                continue

            complexes[complex_no] = {
                "naver_complex_no": complex_no,
                "complex_name": cpx.get("complexName", ""),
                "latitude": float(cpx.get("latitude", 0)),
                "longitude": float(cpx.get("longitude", 0)),
                "dong_name": dong["dong_name"],
                "sgg_name": dong["sgg_name"],
                "sido_name": dong["sido_name"],
            }

    print(f"  수집된 단지: {len(complexes)}개")
    return complexes


# ==============================================================================
# Step 3: apt_id 매핑
# ==============================================================================

def build_mapping(complexes):
    """네이버 complexNo ↔ 기존 apt_id 매핑"""
    print("\n[Step 3] apt_id ↔ complexNo 매핑")

    # 기존 apt_basic_info_master 로드
    basic_file = get_latest_file("apt_basic_info_master_*.csv")
    if not basic_file:
        print("  ⚠ apt_basic_info_master 파일을 찾을 수 없습니다. 매핑 없이 진행합니다.")
        # 매핑 없이 진행 (apt_id = None)
        mapping_list = []
        for cno, info in complexes.items():
            mapping_list.append({
                "naver_complex_no": cno,
                "apt_id": None,
                "complex_name": info["complex_name"],
                "sgg_name": info.get("sgg_name", ""),
                "dong_name": info.get("dong_name", ""),
                "match_type": None,
                "match_score": 0.0,
            })
        return pd.DataFrame(mapping_list)

    df_basic = pd.read_csv(basic_file)
    print(f"  기존 단지 수: {len(df_basic)}건 (from {os.path.basename(basic_file)})")

    # 정규화된 이름 + 동 준비
    df_basic["_norm_name"] = df_basic["apt_name"].apply(_normalize_name)
    df_basic["_norm_dong"] = df_basic["admin_dong"].fillna("").apply(_normalize_name)

    # 빠른 조회를 위한 인덱스 구조
    # (norm_name, norm_dong) → apt_id 매핑
    name_dong_idx = {}
    for _, row in df_basic.iterrows():
        key = (row["_norm_name"], row["_norm_dong"])
        name_dong_idx[key] = row["apt_id"]

    # 위경도 매핑용 리스트
    geo_list = []
    for _, row in df_basic.iterrows():
        if pd.notna(row.get("latitude")) and pd.notna(row.get("longitude")):
            geo_list.append({
                "apt_id": row["apt_id"],
                "lat": float(row["latitude"]),
                "lon": float(row["longitude"]),
            })

    mapping_list = []
    match_counts = {"name": 0, "geo": 0, "none": 0}

    for cno, info in complexes.items():
        c_name_norm = _normalize_name(info["complex_name"])
        c_dong_norm = _normalize_name(info["dong_name"])

        matched_apt_id = None
        match_type = None
        match_score = 0.0

        # 방법 1: 이름+동 완전 일치
        key = (c_name_norm, c_dong_norm)
        if key in name_dong_idx:
            matched_apt_id = name_dong_idx[key]
            match_type = "name"
            match_score = 1.0
            match_counts["name"] += 1

        # 방법 2: 위경도 근접 매칭 (50m 이내)
        if not matched_apt_id and info["latitude"] and info["longitude"]:
            best_dist = float('inf')
            for geo_item in geo_list:
                dist = _haversine_distance(
                    info["latitude"], info["longitude"],
                    geo_item["lat"], geo_item["lon"]
                )
                if dist < best_dist:
                    best_dist = dist
                    if dist <= 50:  # 50m 이내
                        matched_apt_id = geo_item["apt_id"]
                        match_type = "geo"
                        match_score = round(max(0, 1 - dist / 50), 2)

            if match_type == "geo":
                match_counts["geo"] += 1

        if not matched_apt_id:
            match_counts["none"] += 1

        mapping_list.append({
            "naver_complex_no": cno,
            "apt_id": matched_apt_id,
            "complex_name": info["complex_name"],
            "sgg_name": info.get("sgg_name", ""),
            "dong_name": info.get("dong_name", ""),
            "match_type": match_type,
            "match_score": match_score,
        })

    total = len(mapping_list)
    matched = match_counts["name"] + match_counts["geo"]
    rate = (matched / total * 100) if total > 0 else 0
    print(f"  매핑 결과: {matched}/{total} ({rate:.1f}%)")
    print(f"    이름매칭: {match_counts['name']}건, 위경도매칭: {match_counts['geo']}건, 미매칭: {match_counts['none']}건")

    return pd.DataFrame(mapping_list)


# ==============================================================================
# Step 4: 매물 증분 수집
# ==============================================================================

def _fetch_articles(complex_no, trade_type):
    """특정 단지·거래유형의 매물 목록을 모두 가져옴 (페이지네이션)"""
    articles = []
    page = 1
    max_pages = 10  # 안전 제한

    while page <= max_pages:
        data = _request_with_retry(
            f"{BASE_URL}/articles/complex/{complex_no}",
            params={
                "realEstateType": "APT",
                "tradeType": trade_type,
                "page": page,
                "sameAddressGroup": "false",
            }
        )

        if not data:
            break

        article_list = data.get("articleList", [])
        if not article_list:
            break

        articles.extend(article_list)

        # 다음 페이지 확인
        is_more = data.get("isMoreData", False)
        if not is_more:
            break
        page += 1

    return articles


def _parse_article(article, complex_no, apt_id, trade_type, today_str,
                   sgg_name="", dong_name=""):
    """API 응답의 개별 매물을 표준 형식으로 변환"""
    article_no = str(article.get("articleNo", ""))
    if not article_no:
        return None

    # 전용면적 정수화
    area2 = article.get("area2", article.get("exclusiveArea", 0))
    try:
        exclusive_area = int(float(area2))
    except (ValueError, TypeError):
        exclusive_area = 0

    # 가격 파싱
    price = _parse_price(str(article.get("dealOrWarrantPrc", "0")))
    rent = _parse_price(str(article.get("rentPrc", "0"))) if trade_type == "B2" else 0

    # 확인일자
    confirm_ymd = article.get("articleConfirmYmd", "")
    confirm_date = None
    if confirm_ymd and len(confirm_ymd) == 8:
        try:
            confirm_date = f"{confirm_ymd[:4]}-{confirm_ymd[4:6]}-{confirm_ymd[6:8]}"
        except (ValueError, IndexError):
            pass

    return {
        "article_no": article_no,
        "apt_id": apt_id,
        "naver_complex_no": complex_no,
        "sgg_name": sgg_name,
        "dong_name": dong_name,
        "trade_type": trade_type,
        "exclusive_area": exclusive_area,
        "initial_price": price,
        "current_price": price,
        "rent_price": rent,
        "floor_info": str(article.get("floorInfo", "")).strip() or None,
        "direction": str(article.get("direction", "")).strip() or None,
        "confirm_date": confirm_date,
        "first_seen_date": today_str,
        "last_seen_date": today_str,
        "is_active": True,
    }


def collect_listings_incremental(complexes, df_mapping, test_mode=False):
    """단지별 매물을 수집하고 기존 데이터와 비교하여 증분 처리"""
    print("\n[Step 4] 매물 증분 수집")
    today_str = get_today_str()
    today_date = datetime.now().strftime("%Y-%m-%d")

    # 매핑 딕셔너리: complexNo → apt_id
    mapping_dict = {}
    for _, row in df_mapping.iterrows():
        mapping_dict[str(row["naver_complex_no"])] = row.get("apt_id")

    # 기존 매물 데이터 로드 (증분 비교용)
    existing_articles = {}
    prev_file = get_latest_file("naver_listing_*.csv", exclude_today=True)
    if prev_file:
        try:
            df_prev = pd.read_csv(prev_file, dtype={"article_no": str})
            df_active = df_prev[df_prev["is_active"] == True]
            for _, row in df_active.iterrows():
                existing_articles[str(row["article_no"])] = row.to_dict()
            print(f"  기존 활성 매물: {len(existing_articles)}건 (from {os.path.basename(prev_file)})")
        except Exception as e:
            print(f"  기존 데이터 로드 실패: {e}")

    # 수집 대상 단지 목록
    complex_list = list(complexes.keys())
    if test_mode:
        complex_list = complex_list[:20]

    # 수집
    all_listings = []
    seen_article_nos = set()
    stats = {"sale": 0, "jeonse": 0, "monthly": 0, "new": 0, "updated": 0}

    total = len(complex_list)
    for idx, cno in enumerate(complex_list):
        if (idx + 1) % 100 == 0 or idx == 0:
            print(f"  진행: {idx+1}/{total} 단지 ({stats['new']}건 신규, {stats['updated']}건 갱신)")

        apt_id = mapping_dict.get(cno)
        cpx_info = complexes.get(cno, {})
        sgg = cpx_info.get("sgg_name", "")
        dong = cpx_info.get("dong_name", "")

        for trade_type in TRADE_TYPES.keys():
            articles = _fetch_articles(cno, trade_type)

            for art in articles:
                parsed = _parse_article(art, cno, apt_id, trade_type, today_date,
                                        sgg_name=sgg, dong_name=dong)
                if not parsed:
                    continue

                ano = parsed["article_no"]
                seen_article_nos.add(ano)

                # 거래유형별 카운트
                if trade_type == "A1":
                    stats["sale"] += 1
                elif trade_type == "B1":
                    stats["jeonse"] += 1
                else:
                    stats["monthly"] += 1

                # 증분 비교
                if ano in existing_articles:
                    # 기존 매물: first_seen 유지, 가격 변경 확인
                    prev = existing_articles[ano]
                    parsed["first_seen_date"] = prev.get("first_seen_date", today_date)
                    parsed["initial_price"] = prev.get("initial_price", parsed["current_price"])

                    if parsed["current_price"] != prev.get("current_price"):
                        stats["updated"] += 1
                else:
                    # 신규 매물
                    stats["new"] += 1

                all_listings.append(parsed)

    # 종료 처리: 기존에 active였지만 오늘 안 나온 매물
    closed_count = 0
    for ano, prev in existing_articles.items():
        if ano not in seen_article_nos:
            prev_copy = dict(prev)
            prev_copy["is_active"] = False
            prev_copy["last_seen_date"] = prev.get("last_seen_date", today_date)
            all_listings.append(prev_copy)
            closed_count += 1

    stats["closed"] = closed_count
    stats["total"] = len(all_listings)

    print(f"\n  수집 완료:")
    print(f"    매매: {stats['sale']}건, 전세: {stats['jeonse']}건, 월세: {stats['monthly']}건")
    print(f"    신규: {stats['new']}건, 가격변경: {stats['updated']}건, 종료: {stats['closed']}건")
    print(f"    총: {stats['total']}건")

    df_listing = pd.DataFrame(all_listings) if all_listings else pd.DataFrame()
    return df_listing, stats


# ==============================================================================
# Step 5: CSV 저장
# ==============================================================================

def save_results_csv(df_mapping, df_listing):
    """매핑/매물 데이터를 CSV로 저장"""
    print("\n[Step 5] CSV 저장")
    today = get_today_str()
    files = {}

    # 매핑 저장
    mapping_file = os.path.join(DATA_DIR, f"naver_complex_mapping_{today}.csv")
    df_mapping.to_csv(mapping_file, index=False, encoding="utf-8-sig")
    print(f"  매핑: {mapping_file} ({len(df_mapping)}건)")
    files["mapping"] = mapping_file

    # 매물 저장
    if not df_listing.empty:
        listing_file = os.path.join(DATA_DIR, f"naver_listing_{today}.csv")
        df_listing.to_csv(listing_file, index=False, encoding="utf-8-sig")
        print(f"  매물: {listing_file} ({len(df_listing)}건)")
        files["listing"] = listing_file

    return files


# ==============================================================================
# Step 6: DB 저장
# ==============================================================================

def create_naver_schema(engine):
    """네이버 매물 관련 PostgreSQL 테이블 생성 (Drop & Create + COMMENT)"""
    print("\n[Step 6-1] DB 스키마 생성")
    with engine.begin() as conn:
        # 매핑 테이블
        conn.execute(text("""
            DROP TABLE IF EXISTS naver_listing CASCADE;
            DROP TABLE IF EXISTS naver_complex_mapping CASCADE;

            CREATE TABLE naver_complex_mapping (
                naver_complex_no VARCHAR(20) PRIMARY KEY,
                apt_id VARCHAR(50),
                complex_name VARCHAR(100),
                sgg_name VARCHAR(50),
                dong_name VARCHAR(50),
                match_type VARCHAR(20),
                match_score FLOAT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            COMMENT ON TABLE naver_complex_mapping IS
                '네이버 부동산 단지번호와 기존 apt_id 간 매핑 정보 (Naver Complex to Apt ID Mapping)';
            COMMENT ON COLUMN naver_complex_mapping.naver_complex_no IS
                '네이버 부동산 단지 고유번호 (Naver Complex ID)';
            COMMENT ON COLUMN naver_complex_mapping.apt_id IS
                '기존 아파트 고유 코드 - apt_basic.apt_id와 조인 가능 (Apartment ID, FK to apt_basic)';
            COMMENT ON COLUMN naver_complex_mapping.complex_name IS
                '네이버에 등록된 단지명 (Complex Name on Naver)';
            COMMENT ON COLUMN naver_complex_mapping.sgg_name IS
                '시군구명 - 행정구역 (District Name, e.g. 강남구)';
            COMMENT ON COLUMN naver_complex_mapping.dong_name IS
                '행정동명 - 행정구역 (Administrative Dong Name, e.g. 개포동)';
            COMMENT ON COLUMN naver_complex_mapping.match_type IS
                '매핑 방법: name(이름매칭), geo(위경도매칭), address(주소매칭) (Matching Method)';
            COMMENT ON COLUMN naver_complex_mapping.match_score IS
                '매핑 신뢰도 0~1 (Matching Confidence Score)';
        """))

        # 매물 테이블
        conn.execute(text("""
            CREATE TABLE naver_listing (
                article_no VARCHAR(20) PRIMARY KEY,
                apt_id VARCHAR(50),
                naver_complex_no VARCHAR(20),
                sgg_name VARCHAR(50),
                dong_name VARCHAR(50),
                trade_type VARCHAR(10),
                exclusive_area INTEGER,
                initial_price INTEGER,
                current_price INTEGER,
                rent_price INTEGER,
                floor_info VARCHAR(10),
                direction VARCHAR(10),
                confirm_date DATE,
                first_seen_date DATE,
                last_seen_date DATE,
                is_active BOOLEAN DEFAULT true
            );
            COMMENT ON TABLE naver_listing IS
                '네이버 부동산 아파트 매물 정보 - 증분 수집 (Naver Real Estate Listings, Incremental)';
            COMMENT ON COLUMN naver_listing.article_no IS
                '네이버 매물 고유번호 (Naver Article ID, PK)';
            COMMENT ON COLUMN naver_listing.apt_id IS
                '기존 아파트 고유 코드 - apt_basic/apt_trade/apt_rent와 조인 가능 (Apartment ID, FK)';
            COMMENT ON COLUMN naver_listing.naver_complex_no IS
                '네이버 단지번호 - naver_complex_mapping과 조인 가능 (Naver Complex ID)';
            COMMENT ON COLUMN naver_listing.sgg_name IS
                '시군구명 - 행정구역 (District Name, e.g. 강남구)';
            COMMENT ON COLUMN naver_listing.dong_name IS
                '행정동명 - 행정구역 (Administrative Dong Name, e.g. 개포동)';
            COMMENT ON COLUMN naver_listing.trade_type IS
                '거래 유형: A1=매매(Sale), B1=전세(Jeonse), B2=월세(Monthly Rent)';
            COMMENT ON COLUMN naver_listing.exclusive_area IS
                '전용 면적 (㎡, 정수) - apt_trade/apt_rent.exclusive_area와 조인 가능 (Exclusive Area)';
            COMMENT ON COLUMN naver_listing.initial_price IS
                '최초 등록 호가, 만원 (Initial Asking Price)';
            COMMENT ON COLUMN naver_listing.current_price IS
                '현재 호가, 만원 - 가격 변경 시 갱신됨 (Current Asking Price)';
            COMMENT ON COLUMN naver_listing.rent_price IS
                '월세, 만원 - 월세(B2)인 경우에만 값 있음 (Monthly Rent Amount)';
            COMMENT ON COLUMN naver_listing.floor_info IS
                '층 정보 (Floor Info)';
            COMMENT ON COLUMN naver_listing.direction IS
                '향 (Direction/Facing)';
            COMMENT ON COLUMN naver_listing.confirm_date IS
                '매물 확인 일자 (Confirmation Date)';
            COMMENT ON COLUMN naver_listing.first_seen_date IS
                '최초 수집 일자 - 매물 등록 시점 추정 (First Seen Date)';
            COMMENT ON COLUMN naver_listing.last_seen_date IS
                '마지막 확인 일자 - 매물 종료 시점 (Last Seen Date)';
            COMMENT ON COLUMN naver_listing.is_active IS
                '현재 노출 중 여부: true=활성, false=종료 (Is Currently Active)';
        """))

    print("  스키마 생성 완료")


def save_to_db(engine, df_mapping, df_listing):
    """매핑/매물 데이터를 PostgreSQL에 적재 (UPSERT)"""
    print("\n[Step 6-2] DB 데이터 적재")
    results = {}

    with engine.begin() as conn:
        # 매핑 테이블: 전체 교체
        df_mapping.to_sql("naver_complex_mapping", conn,
                          if_exists="replace", index=False, chunksize=1000)
        # COMMENT 재적용 (replace 후 소실됨)
        conn.execute(text("""
            COMMENT ON TABLE naver_complex_mapping IS
                '네이버 부동산 단지번호와 기존 apt_id 간 매핑 정보 (Naver Complex to Apt ID Mapping)';
        """))
        results["mapping"] = len(df_mapping)
        print(f"  매핑 적재: {len(df_mapping)}건")

    # 매물 테이블: UPSERT (staging 테이블 활용)
    if not df_listing.empty:
        # 날짜 컬럼 변환
        for col in ["confirm_date", "first_seen_date", "last_seen_date"]:
            if col in df_listing.columns:
                df_listing[col] = pd.to_datetime(df_listing[col], errors="coerce")

        chunk_size = 5000
        total_loaded = 0

        with engine.begin() as conn:
            for i in range(0, len(df_listing), chunk_size):
                chunk = df_listing.iloc[i:i+chunk_size]
                chunk.to_sql("naver_listing_staging", conn,
                             if_exists="replace", index=False)

                conn.execute(text("""
                    INSERT INTO naver_listing
                    SELECT * FROM naver_listing_staging
                    ON CONFLICT (article_no) DO UPDATE SET
                        apt_id = EXCLUDED.apt_id,
                        current_price = EXCLUDED.current_price,
                        rent_price = EXCLUDED.rent_price,
                        last_seen_date = EXCLUDED.last_seen_date,
                        is_active = EXCLUDED.is_active;
                """))
                conn.execute(text("DROP TABLE IF EXISTS naver_listing_staging;"))
                total_loaded += len(chunk)
                print(".", end="", flush=True)

        print(f"\n  매물 적재: {total_loaded}건")
        results["listing"] = total_loaded
    else:
        results["listing"] = 0

    return results


def create_naver_indices(engine):
    """성능 최적화 인덱스 생성"""
    print("\n[Step 6-3] 인덱스 생성")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_naver_listing_apt_area "
            "ON naver_listing (apt_id, exclusive_area);"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_naver_listing_active "
            "ON naver_listing (is_active, last_seen_date);"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_naver_listing_trade "
            "ON naver_listing (trade_type);"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_naver_listing_complex "
            "ON naver_listing (naver_complex_no);"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_naver_mapping_apt "
            "ON naver_complex_mapping (apt_id);"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_naver_listing_sgg "
            "ON naver_listing (sgg_name, dong_name);"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_naver_mapping_sgg "
            "ON naver_complex_mapping (sgg_name, dong_name);"
        ))
    print("  인덱스 7개 생성 완료")


# ==============================================================================
# Step 7: 결과보고서 생성
# ==============================================================================

def generate_report(results):
    """수집 완료 후 상세 결과보고서 생성"""
    print("\n[Step 7] 결과보고서 생성")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = get_today_str()

    # 안전하게 값 추출
    r = results
    mapping_total = r.get("mapping_total", 0)
    mapping_success = r.get("mapping_success", 0)
    mapping_failed = mapping_total - mapping_success
    mapping_rate = (mapping_success / mapping_total * 100) if mapping_total > 0 else 0

    report = f"""{'='*60}
  네이버 부동산 매물 수집 결과 보고서
  수집 일시: {now}
{'='*60}

[1. 지역코드 수집]
  시도: {r.get('sido_count', 0)}개
  시군구: {r.get('sgg_count', 0)}개
  읍면동: {r.get('dong_count', 0)}개

[2. 단지 수집]
  전체 네이버 단지: {r.get('total_complexes', 0)}개
  매물 있는 단지: {r.get('active_complexes', 0)}개

[3. apt_id 매핑 결과]
  매핑 시도: {mapping_total}건
  매핑 성공: {mapping_success}건
  매핑 실패: {mapping_failed}건
  매핑률: {mapping_rate:.1f}%
  ┌──────────────────────────────────┐
  │ 매칭 방법별 분포                 │
  │   이름+동 매칭: {r.get('match_name', 0):>8}건      │
  │   위경도 매칭:  {r.get('match_geo', 0):>8}건      │
  │   미매칭:       {r.get('match_none', 0):>8}건      │
  └──────────────────────────────────┘

[4. 매물 수집 결과]
  매매(A1): {r.get('sale_count', 0):>8}건
  전세(B1): {r.get('jeonse_count', 0):>8}건
  월세(B2): {r.get('monthly_count', 0):>8}건
  총 매물:  {r.get('total_listings', 0):>8}건
  ┌──────────────────────────────────┐
  │ 증분 처리                        │
  │   신규 등록: {r.get('new_count', 0):>8}건          │
  │   가격 변경: {r.get('updated_count', 0):>8}건          │
  │   종료 처리: {r.get('closed_count', 0):>8}건          │
  └──────────────────────────────────┘

[5. DB 저장 결과]
  naver_complex_mapping: {r.get('db_mapping', '-')}건
  naver_listing: {r.get('db_listing', '-')}건
  인덱스 생성: 5개

[6. 파일 저장]
  {r.get('mapping_file', '-')}
  {r.get('listing_file', '-')}
{'='*60}
"""

    print(report)

    # 보고서 파일 저장
    report_file = os.path.join(DATA_DIR, f"naver_collection_report_{today}.txt")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  보고서 저장: {report_file}")

    return report_file


# ==============================================================================
# 메인 실행
# ==============================================================================

def main(skip_db=False, test_mode=False):
    """네이버 부동산 매물 수집 메인 함수"""
    print("=" * 60)
    print("  네이버 부동산 매물 데이터 수집 시작")
    if test_mode:
        print("  ⚠ 테스트 모드: 소규모 수집")
    print("=" * 60)

    results = {
        "sido_count": len(SIDO_CODES),
    }

    # Step 1: 지역코드 수집
    dong_list, sgg_count = get_cortars()
    results["sgg_count"] = sgg_count
    results["dong_count"] = len(dong_list)

    if not dong_list:
        print("지역코드 수집 실패. 종료합니다.")
        return

    # Step 2: 매물 있는 단지 목록
    complexes = get_active_complexes(dong_list, test_mode=test_mode)
    results["total_complexes"] = len(complexes)
    results["active_complexes"] = len(complexes)

    if not complexes:
        print("단지 수집 실패. 종료합니다.")
        return

    # Step 3: apt_id 매핑
    df_mapping = build_mapping(complexes)
    matched = df_mapping["apt_id"].notna().sum()
    results["mapping_total"] = len(df_mapping)
    results["mapping_success"] = int(matched)
    results["match_name"] = int((df_mapping["match_type"] == "name").sum())
    results["match_geo"] = int((df_mapping["match_type"] == "geo").sum())
    results["match_none"] = int(df_mapping["match_type"].isna().sum())

    # Step 4: 매물 증분 수집
    df_listing, stats = collect_listings_incremental(
        complexes, df_mapping, test_mode=test_mode
    )
    results["sale_count"] = stats.get("sale", 0)
    results["jeonse_count"] = stats.get("jeonse", 0)
    results["monthly_count"] = stats.get("monthly", 0)
    results["total_listings"] = stats.get("total", 0)
    results["new_count"] = stats.get("new", 0)
    results["updated_count"] = stats.get("updated", 0)
    results["closed_count"] = stats.get("closed", 0)

    # Step 5: CSV 저장
    files = save_results_csv(df_mapping, df_listing)
    results["mapping_file"] = files.get("mapping", "-")
    results["listing_file"] = files.get("listing", "-")

    # Step 6: DB 저장
    if not skip_db:
        try:
            engine = get_db_engine()
            create_naver_schema(engine)
            db_results = save_to_db(engine, df_mapping, df_listing)
            create_naver_indices(engine)
            results["db_mapping"] = db_results.get("mapping", 0)
            results["db_listing"] = db_results.get("listing", 0)
        except Exception as e:
            print(f"\n  ⚠ DB 저장 실패: {e}")
            results["db_mapping"] = "실패"
            results["db_listing"] = "실패"
    else:
        print("\n  (DB 저장 건너뛰기)")
        results["db_mapping"] = "건너뜀"
        results["db_listing"] = "건너뜀"

    # Step 7: 결과보고서
    report_file = generate_report(results)
    results["report_file"] = report_file

    print("\n" + "=" * 60)
    print("  수집 완료!")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="네이버 부동산 매물 수집")
    parser.add_argument("--skip-db", action="store_true", help="DB 저장 생략")
    parser.add_argument("--test", action="store_true", help="테스트 모드 (소규모 수집)")
    args = parser.parse_args()

    main(skip_db=args.skip_db, test_mode=args.test)
