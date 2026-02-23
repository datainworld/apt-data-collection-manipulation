# 아파트 데이터 수집·가공·분석 시스템

서울/인천/경기 아파트 실거래가 및 네이버 매물 데이터를 수집하고, PostgreSQL DB로 적재하여 Text-to-SQL 분석에 활용하는 시스템입니다.

## 시스템 구성

| 스크립트 | 역할 | 실행 빈도 |
|---|---|---|
| `collect_and_process.py` | 최초 데이터 수집 + 가공 (단지코드, 기본/상세정보, 매매/전월세) | 최초 1회 |
| `update_and_migrate.py` | 일일 증분 업데이트 + DB 마이그레이션 | 매일 1회 |
| `collect_naver_listing.py` | 네이버 부동산 매물 수집 | 매일 1회 |
| `utils.py` | 공통 유틸리티 (API, 파일, DB) | - |

## 데이터 소스

- **공공데이터포털**: 아파트 단지코드, 기본/상세정보, 매매/전월세 실거래가
- **K-Apt**: 아파트 기본/상세 정보
- **Kakao API**: 주소 → 위경도, 행정동 지오코딩
- **네이버 부동산**: 아파트 매물 (호가, 전세/월세)

## 환경 설정

```bash
# 1. 의존성 설치
uv sync

# 2. .env 파일 생성
cp .env.example .env
# DATA_API_KEY, KAKAO_API_KEY, POSTGRES_* 설정
```

### .env 필수 항목
```
DATA_API_KEY=공공데이터포털_API키
KAKAO_API_KEY=카카오_REST_API키
POSTGRES_USER=postgres
POSTGRES_PASSWORD=비밀번호
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=apt_data
```

## 실행 방법

```bash
# 1단계: 최초 데이터 수집 + 가공 (약 2~3시간)
python collect_and_process.py --regions 11 28 41 --months 36

# 2단계: DB 마이그레이션
python update_and_migrate.py

# 3단계(매일): 실거래 데이터 업데이트
python update_and_migrate.py

# 3단계(매일): 네이버 매물 수집
python collect_naver_listing.py
```

## 문서
- [데이터 수집 가이드](docs/아파트%20데이터%20수집(최초).md)
- [데이터 가공 가이드](docs/아파트%20데이터%20가공(최초).md)
- [운영 매뉴얼](docs/사용자_매뉴얼.md)
