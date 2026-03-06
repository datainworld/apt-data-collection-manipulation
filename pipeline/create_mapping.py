import os
import time
import pandas as pd
from sqlalchemy import text
from haversine import haversine, Unit
from thefuzz import fuzz
import re

# 기존 파이프라인 모듈 활용
from utils import get_db_engine

def clean_name(name):
    """단지명 비교를 위해 괄호 내용 및 불필요한 단어를 제거합니다."""
    if pd.isna(name) or not name: 
        return ""
    name = re.sub(r'\(.*?\)', '', str(name))
    name = re.sub(r'\s+', '', name)
    # 비교를 어렵게 하는 공통 수식어 제거
    name = name.replace("아파트", "").replace("마을", "").replace("단지", "")
    return name

def create_mapping_table(engine):
    """complex_mapping 테이블을 생성합니다."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS complex_mapping (
                apt_id VARCHAR(50) PRIMARY KEY,
                naver_complex_no VARCHAR(20),
                mapping_method VARCHAR(20),
                confidence_score FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            COMMENT ON TABLE complex_mapping IS '공공데이터 아파트 식별자(apt_id)와 네이버 단지 식별자(complex_no) 매핑 테이블';
        """))

def main():
    print("=" * 60)
    print("  아파트 단지 식별자 매핑 파이프라인 (apt_id <-> complex_no)")
    print("=" * 60)

    engine = get_db_engine()
    
    print("[1] DB에서 단지 정보 로드 중...")
    try:
        with engine.connect() as conn:
            df_apt = pd.read_sql("SELECT apt_id, apt_name, road_address, jibun_address, latitude, longitude, admin_dong FROM apt_basic", conn)
            df_naver = pd.read_sql("SELECT complex_no, complex_name, sido_name, sgg_name, dong_name, latitude, longitude FROM naver_complex", conn)
    except Exception as e:
        print(f"DB 로드 실패: {e}")
        print("마이그레이션이 먼저 선행되어야 합니다.")
        return

    print(f"  > apt_basic: {len(df_apt)}건")
    print(f"  > naver_complex: {len(df_naver)}건")
    
    # 좌표값이 없는 데이터 필터링
    df_apt = df_apt.dropna(subset=['latitude', 'longitude']).copy()
    df_naver = df_naver.dropna(subset=['latitude', 'longitude']).copy()
    
    print("[2] 매핑 알고리즘 초기화 및 전처리...")
    df_apt['clean_name'] = df_apt['apt_name'].apply(clean_name)
    df_naver['clean_name'] = df_naver['complex_name'].apply(clean_name)
    
    mappings = []
    count = 0
    start_time = time.time()
    
    print("[3] 공간 및 텍스트 유사도 매핑 시작 (최대 300m 거리 내 탐색)...")
    
    for idx, row_apt in df_apt.iterrows():
        lat_a = row_apt['latitude']
        lon_a = row_apt['longitude']
        
        # 최적화: 전체 거리 계산을 피하기 위해 바운딩 박스로 1차 필터링
        # 위경도 약 0.005도는 대략 500m 이내
        lat_diff = 0.005
        lon_diff = 0.005
        
        candidates = df_naver[
            (df_naver['latitude'] >= lat_a - lat_diff) &
            (df_naver['latitude'] <= lat_a + lat_diff) &
            (df_naver['longitude'] >= lon_a - lon_diff) &
            (df_naver['longitude'] <= lon_a + lon_diff)
        ]
        
        best_match = None
        best_score = 0
        best_mapped_by = ""
        
        if not candidates.empty:
            for c_idx, row_n in candidates.iterrows():
                # haversine 패키지를 통한 정확한 거리(m) 계산
                dist_m = haversine((lat_a, lon_a), (row_n['latitude'], row_n['longitude']), unit=Unit.METERS)
                if dist_m > 300: 
                    continue
                
                # thefuzz를 통한 텍스트 유사도 점수 (0~100)
                sim = fuzz.token_set_ratio(row_apt['clean_name'], row_n['clean_name'])
                
                # 규칙 1. 거리가 매우 가깝고(50m 이내) 일부 이름이 비슷한 경우 (위치 기반 강한 매칭)
                if dist_m < 50 and sim > 40:
                    score = 100 - dist_m + sim
                    if score > best_score:
                        best_score = score
                        best_match = row_n
                        best_mapped_by = "DISTANCE"
                
                # 규칙 2. 거리는 조금 떨어져 있지만(300m 이내) 이름이 매우 유사한 경우 (이름 기반 매칭)
                elif sim >= 70 and dist_m <= 300:
                    score = sim + (300 - dist_m)/10
                    if score > best_score:
                        best_score = score
                        best_match = row_n
                        best_mapped_by = "NAME_SIMILARITY"
        
        if best_match is not None:
            mappings.append({
                'apt_id': row_apt['apt_id'],
                'naver_complex_no': best_match['complex_no'],
                'mapping_method': best_mapped_by,
                'confidence_score': round(best_score, 2)
            })
            
        count += 1
        if count % 2000 == 0:
            elapsed = time.time() - start_time
            print(f"  > 진행률: {count}/{len(df_apt)} 단지 분석 완료 (소요시간: {elapsed:.1f}초)")
            
    df_mapping = pd.DataFrame(mappings)
    print(f"\n[결과] 총 {len(df_apt)}개 단지 중 {len(df_mapping)}개 매핑 완료!")
    
    if not df_mapping.empty:
        print("[4] DB에 매핑 데이터 저장 (UPSERT)...")
        create_mapping_table(engine)
        
        # CSV 파일 로컬 백업
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "datas")
        os.makedirs(data_dir, exist_ok=True)
        today_str = time.strftime("%Y-%m-%d")
        csv_path = os.path.join(data_dir, f"complex_mapping_master_{today_str}.csv")
        df_mapping.to_csv(csv_path, index=False, encoding='utf-8-sig')
        
        # DB 저장
        with engine.begin() as conn:
            df_mapping.to_sql("complex_mapping_staging", conn, if_exists="replace", index=False)
            conn.execute(text("""
                INSERT INTO complex_mapping (apt_id, naver_complex_no, mapping_method, confidence_score)
                SELECT apt_id, naver_complex_no, mapping_method, confidence_score
                FROM complex_mapping_staging
                ON CONFLICT (apt_id) DO UPDATE SET
                    naver_complex_no = EXCLUDED.naver_complex_no,
                    mapping_method = EXCLUDED.mapping_method,
                    confidence_score = EXCLUDED.confidence_score,
                    created_at = CURRENT_TIMESTAMP;
            """))
            conn.execute(text("DROP TABLE IF EXISTS complex_mapping_staging;"))
            
        print(f"  > DB 저장 완료 (`complex_mapping` 테이블)")
        print(f"  > CSV 백업 완료: {csv_path}")
    else:
        print("  > 매칭된 데이터가 없습니다.")

if __name__ == "__main__":
    main()
