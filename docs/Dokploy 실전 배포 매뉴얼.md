# 🚀 아파트 데이터 수집 시스템 Dokploy 실전 배포 매뉴얼

본 매뉴얼은 GitHub에 푸시된 프로젝트를 Hostinger VPS 상의 Dokploy에 배포하고, 초기 데이터를 수집(컨테이너 백그라운드 구동)한 뒤, 매일 자동 실행되도록 설정하는 전 과정을 담고 있습니다.

## 1. 사전 준비 (Local & GitHub)
1. 로컬 환경에서 코드를 작성하고 테스트를 완료합니다.
2. 제외해야 할 파일(특히 `datas/` 폴더 내의 대용량 CSV)이 `.gitignore`에 잘 등록되어 있는지 확인합니다.
3. 프로젝트 루트에 의존성 패키지 목록을 담은 파일(`pyproject.toml` 또는 `requirements.txt`)이 있어야 합니다.
4. 모든 코드를 GitHub 저장소(Repository)에 Push 합니다.

## 2. Dokploy 애플리케이션 생성 및 빌드
1. **Hostinger VPS**에 설치된 **Dokploy 대시보드**에 접속합니다.
2. **Applications** 탭에서 **Create** 버튼을 눌러 새 애플리케이션을 생성합니다.
3. **Repository 탭 설정:**
   - Provider: Github
   - Repository: 푸시했던 프로젝트 선택 (예: `datainworld/apt-data-collection-manipulation`)
   - Branch: `main` (또는 배포할 브랜치)
4. **Environment 탭 설정 (.env 처리):**
   - 아래의 환경 변수를 모두 복사하여 붙여넣고 저장합니다.
     ```env
     DATA_API_KEY=발급받은_공공데이터_키
     KAKAO_API_KEY=발급받은_카카오_키
     POSTGRES_USER=postgres
     POSTGRES_PASSWORD=비밀번호
     POSTGRES_HOST=host.docker.internal (혹은 로컬 DB 컨테이너 IP)
     POSTGRES_PORT=5432
     POSTGRES_DB=apt_data
     ```
5. **Deployments 탭 (중요 - 컨테이너 유지 설정):**
   - 이 앱은 계속 띄워두는 웹 서버가 아니기 때문에, 빌드가 끝나도 컨테이너가 죽지 않도록 **Start Command**를 입력해야 합니다.
   - **Start Command:** `sleep infinity`
6. **Deploy 버튼**을 눌러 빌드를 시작합니다. (Dokploy가 Nixpacks 빌더를 통해 자동으로 파이썬 환경을 구성합니다.)

---

## 3. Dokploy 컨테이너 내부 파일 구조 이해
배포가 완료된 후 컨테이너 내부의 구조는 다음과 같이 형성됩니다. (Nixpacks 빌드 기준)

```text
/
├── app/                      # 프로젝트 코드가 위치하는 실제 작업 디렉토리 (기본 실행 경로)
│    ├── collect_and_process.py
│    ├── update_and_migrate.py
│    ├── pyproject.toml
│    ├── utils.py
│    └── datas/               # 수집된 데이터가 저장될 폴더 (실행 시 생성됨)
│
├── opt/
│    └── venv/                # (참고) Dokploy가 기본으로 생성하는 파이썬 가상 환경
│
├── usr/
│    └── bin/
│         └── python3         # ⭐️ 우리가 최종적으로 사용할 Ubuntu 순정 파이썬
│
└── root/
     └── .nix-profile/bin/    # (참고) Nixpacks가 설치한 격리된 동작 환경 (의존성 충돌의 원인)
```

---

## 4. 서버 SSH 접속 및 1회성 데이터 최초 수집 실행
위 구조에서 보았듯, Dokploy가 임의로 만든 파이썬 환경(`/root/.../python3` 또는 가상환경)을 쓰면 C++ 빌드 라이브러리(`libstdc++6`) 누락 등으로 Numpy, Pandas가 깨지는 치명적 문제가 발생할 수 있습니다. 

따라서 **가장 안전한 우분투(Ubuntu) 순정 파이썬 패키지를 강제 설치하여 수집을 진행**합니다.

1. 개발자 PC의 터미널(CMD, PowerShell 등)에서 Hostinger 서버로 SSH 접속합니다.
   ```bash
   ssh root@서버아이피
   ```
2. 현재 실행 중인 Dokploy 컨테이너의 ID를 확인합니다.
   ```bash
   docker ps
   # 'apt-data-collect...' 이름의 컨테이너 ID 복사 (예: 46dc7e4195e3)
   ```
3. 컨테이너 내부 쉘로 들어갑니다. (명령어에 복사한 ID 입력)
   ```bash
   docker exec -it <컨테이너ID> /bin/bash
   docker exec -it 46dc7e4195e3 /bin/bash
   docker exec -it 1ccf0749f56c /bin/bash 
   # 접속 후 프롬프트가 root@<컨테이너ID>:/app# 로 변경됨
   ```

4. **(핵심 트러블슈팅 - 가짜 파이썬 회피)** 우분투 OS의 시스템 파이썬(`python3`)에 패키지를 강제로 모두 설치 시킵니다. (`--break-system-packages` 옵션 사용)
   이때 Dokploy의 임의 파이썬 환경(`/root/.nix-profile/bin/python3`)이 실행을 가로채어 pip 오류가 발생하지 않도록, **반드시 `/usr/bin/python3` 절대 경로를 명시**하여 설치해야 합니다.
   ```bash
   apt-get update
   apt-get install -y python3-pip libstdc++6 gcc make g++
   /usr/bin/python3 -m pip install pandas requests xmltodict python-dotenv sqlalchemy psycopg2-binary python-dateutil curl-cffi --break-system-packages
   ```
5. 완벽하게 준비된 `/usr/bin/python3` 절대 경로를 명시하여 백그라운드 수집을 시작합니다. (약 8~12시간 소요)
   ```bash
   nohup /usr/bin/python3 collect_and_process.py --regions 11 28 41 --months 36 > collect.log 2>&1 &
   ```
6. 데이터가 무사히 수집되고 있는지 실시간 로그를 확인합니다.
   ```bash
   tail -f collect.log
   ```
7. 문제없이 수집 로그가 찍힌다면 `Ctrl + C`를 눌러 로그 화면을 빠져나온 후, `exit`를 쳐서 컨테이너에서 나오고 다시 서버 연결을 종료해도 됩니다.

> [!TIP] **API 일일 제한(Rate Limit) 대응**
> K-Apt 기본/상세 정보 수집은 하루 10,000건 호출 제한이 있습니다. 스크립트에는 이미 `--max-basic 10000`이 기본 적용되어 있어 1만 건 도달 시 다음 단계로 자동 넒어갑니다.
> 만약 특정 단계만 단독으로 다시 돌려야 할 경우 `--skip-code`, `--skip-basic`, `--skip-trade` 옵션을 조합하여 불필요한 단계를 스킵할 수 있습니다.
> 예시: `nohup ... collect_and_process.py --skip-code --skip-basic`

---

## 5. (중요) 데이터 보존을 위한 Volume 설정
컨테이너 기반 환경인 Dokploy는 코드가 업데이트되어 새로 배포될 때마다 내부 파일(`datas/` 등)이 리셋됩니다. 이를 막기 위해 반드시 저장소 볼륨 마운트가 필요합니다.

1. Dokploy 대시보드의 Application 화면에서 **Advanced** (또는 Volumes/Storage) 탭으로 이동
2. 아래 정보로 볼륨을 **Add** 합니다:
   - **Type**: Bind (또는 Mount)
   - **Host Path**: `/var/lib/dokploy/apt-datas` (Hostinger 서버 물리 경로, 임의 지정 가능)
   - **Mount Path**: `/app/datas` (컨테이너 내 데이터 저장 경로)
3. **Save** 후 애플리케이션을 다시 **Deploy** 합니다. 이제 컨테이너가 100번 재시작해도 수집된 마스터 CSV 데이터는 무조건 안전하게 유지됩니다!

---

## 6. 일일 작동 설정 (Dokploy 스케줄러 등록)
초기 거대한 데이터 수집이 끝난 뒤 매일매일 자동으로 데이터를 업데이트하거나, 특정 시간에 수집을 예약하려면 **Dokploy 대시보드의 Scheduled Jobs**를 활용합니다. (서버에서 crontab을 칠 필요가 없습니다!)

### 📝 스케줄러 생성 화면 (Create Schedule) 작성 가이드
1. Dokploy 대시보드 좌측 메뉴에서 **Scheduled Jobs** (또는 Application 요약 화면의 Jobs 탭)로 이동하여 **Add Job(또는 Create Schedule)**을 클릭합니다.
2. 아래 항목들을 목적에 맞게 작성합니다.
   * **Task Name:** 작업 이름 (예: `Daily_Apt_Update`, `Initial_Data_Collection` 등)
   * **Schedule:** `Custom cron expression` 선택 후 크론식 입력 (예: `0 2 * * *` = 매일 새벽 2시)
   * **Timezone:** `Asia/Seoul` 선택 (중요! 없으면 UTC 기준으로 시간 계산 필요)
   * **Shell Type:** `Bash` 유지
   * **Command:** `/usr/bin/python3 /app/실행할_파이썬_파일.py [옵션]`
   * **Enabled:** 스위치 켬 (활성화 유지)

### 📌 추천 자동화 스케줄 예시
1. **실거래가 매일 업데이트 (증분 수집/DB 적재)**
   - **Name:** Daily_Apt_Update
   - **Cron Expression:** `0 2 * * *` (매일 새벽 2시)
   - **Command:** `/usr/bin/python3 /app/update_and_migrate.py`
2. **네이버 부동산 매물 매일 수집**
   - **Name:** Daily_Naver_Update
   - **Cron Expression:** `0 4 * * *` (매일 새벽 4시)
   - **Command:** `/usr/bin/python3 /app/collect_naver_listing.py`
3. **(참고) 1회성 데이터 최초 수집 예약 세팅 시 (예: 2월 26일 새벽 1시)**
   - **Name:** Initial_Apt_Collect
   - **Cron Expression:** `0 1 26 2 *` 
   - **Command:** `/usr/bin/python3 /app/collect_and_process.py --regions 11 28 41 --months 36`

✅ **완료!** 
이제 GitHub에 코드를 푸시하면 새로운 수집 스크립트가 배포되며, 볼륨 마운트를 통해 데이터 유실 없이 매일 설정된 시간에 안전하게 자동 수집 시스템이 돌아가는 최적의 아키텍처가 완성되었습니다.

---

## 7. 스케줄러 및 백그라운드 작업 실행 상태 확인 방법

예약된 스케줄러(Dokploy Scheduled Jobs 혹은 crontab)를 통해 데이터 수집이 정상적으로 실행 중인지 확인하는 방법은 크게 4가지가 있습니다.

### 1. Dokploy 대시보드에서 시스템 로그 확인 (가장 권장됨)
Dokploy 웹 화면에서 실행 상태와 실제 출력 로그를 바로 확인할 수 있습니다.
* **확인 경로:** Dokploy 대시보드 접속 ➔ Project ➔ APT ➔ **Schedules** ➔ Schedule Tasks 아이콘
* **방법:** 등록된 스케줄 항목(예: `Daily_Apt_Update`)의 **Status/Logs** 탭을 클릭하여 현재 스크립트 출력 로그(진행률 등)를 실시간으로 확인합니다. **Last Run**(마지막 실행 시간)도 함께 체크하여 스케줄러가 정상 동작했는지 확인합니다.

### 2. 서버 SSH 접속하여 프로세스(Process) 확인
서버 백그라운드 환경에서 스크립트가 온전히 돌아가고 있는지 직접 검사하는 방식입니다.
* **확인 방법:** VPS 서버에 SSH 접속 후 Docker 컨테이너 내의 파이썬 프로세스를 검색합니다.
```bash
# 1. 컨테이너 ID 확인 (apt-data-collect... 등)
docker ps

# 2. 실행 중인 컨테이너 내부의 python 프로세스 검색
docker exec -it <컨테이너ID> ps -ef | grep python
```
* **정상 상태:** 결과 목록에 `/usr/bin/python3 /app/update_and_migrate.py` 혹은 `/app/collect_naver_listing.py` 등의 프로세스가 보인다면 수집이 정상적으로 실행 중인 것입니다.

### 3. 데이터 파일(CSV) 갱신 시간 확인
데이터 통합 및 적재 과정에서 저장소 파일이 갱신되는지 확인합니다.
* **확인 방법:** 서버 내 호스트 볼륨으로 마운트한 폴더(예: `/var/lib/dokploy/apt-datas`)를 조회합니다.
```bash
ls -l /var/lib/dokploy/apt-datas
```
* **정상 상태:** 디렉토리 내 마스터 파일(`apt_trade_master_*.csv` 등)이나 임시 작업 파일의 **수정 시간(날짜/시간)** 이 스크줄러가 실행된 시점과 가깝게 맞물려 기록되어 있다면 데이터 쓰기가 진행 중이거나 완료된 것입니다.

### 4. DB (PostgreSQL) 최신 데이터 등록 여부 확인
수집 처리가 모두 끝난 후 최종적으로 데이터 마이그레이션이 잘 반영되었는지 확인하는 확실한 방법입니다.
* **확인 방법:** DBeaver, pgAdmin 등 외부 클라이언트나 쿼리 툴을 이용해 DB에 접속한 뒤 아래 쿼리를 수행합니다.
```sql
-- 실거래 매매 데이터 최신 날짜 확인
SELECT MAX(deal_date) FROM apt_trade;

-- 네이버 부동산 호가 데이터 최신 반영일 확인
SELECT MAX(last_seen_date) FROM naver_listing;
```
* **정상 상태:** 최신 날짜 데이터가 조회된다면(어제 혹은 실시간 수집 내역) 스케줄러가 무사히 데이터를 수집하고 적재까지 완료한 것을 의미합니다.

---

## 8. 외부/로컬 PC에서 DB (PostgreSQL) 안전하게 접속하는 방법

보안(해킹 방지)을 위해 클라우드 방화벽(Hostinger Firewall)에서 데이터베이스 포트(5432)를 전면 개방하는 것(`0.0.0.0/0`)은 매우 위험합니다. 따라서 가장 안전하고 모범적인 실무 방식인 **SSH 포트 포워딩(터널링)**을 통해 내 PC의 로컬 툴(pgAdmin, DBeaver 등)에서 접속하는 방법을 안내합니다.

### 8.1 PowerShell에서 SSH 터널(비밀 통로) 뚫기

윈도우 환경에서 가장 안정적으로 포트를 연결하는 방법입니다.

1. PC에서 **Windows PowerShell**을 실행합니다.
2. 아래 명령어를 입력하여 터널을 뚫습니다. (자신의 VPS IP 사용)
   ```powershell
   ssh -L 5432:localhost:5432 root@76.13.246.35
   ```
   > **의미:** "내 PC의 5432 포트 ➔ SSH 암호화 ➔ VPS 서버 접속 ➔ 서버 내부의 5432(DB) 포트" 로 강제로 길을 뚫어줍니다.
3. `password:` 입력 란에 윈도우 비밀번호가 아닌 **Hostinger VPS의 root 계정 비밀번호**를 입력하고 엔터를 칩니다.
4. 접속에 성공하여 리눅스 터미널(`root@srv...:~#`)이 나타나면, **이 검은 창을 절대 닫지 말고 백그라운드에 그대로 켜둡니다.** (이 창이 유지되는 동안에만 터널이 열려 있습니다.)

### 8.2 pgAdmin 등 쿼리 툴에서 접속하기

터널이 유지된 상태에서는 내 PC가 곧 서버인 것처럼 행동할 수 있습니다. 이미 뚫어놓은 터널을 통해 DB로 직행합니다.

1. **pgAdmin** 또는 DBeaver를 엽니다.
2. 새 서버(Connection) 추가/등록 메뉴로 들어갑니다.
3. **[General] 탭**: 서버 이름을 알아보기 쉽게 적어줍니다. (예: `Hostinger APT DB (터널링)`)
4. **[Connection] 탭**을 아래와 같이 **자신(localhost)**을 향하게 세팅합니다.
   * **Host name/address:** `localhost` (또는 `127.0.0.1`)
   * **Port:** `5432`
   * **Maintenance database:** `postgres`
   * **Username:** `postgres`
   * **Password:** Dokploy에서 설정했던 DB의 비밀번호 (예: `4444`)
5. **[SSH Tunnel] 탭**:
   * 내장 SSH 터널 기능은 오류가 잦으므로 **항상 끄기(비활성화)**를 권장합니다. 앞서 PowerShell이 이 역할을 완벽하게 대신하고 있습니다.
6. **[Save]** 를 눌러 연결합니다! 대기 시간 없이 즉시 연결됩니다.

### 8.3 데이터 테이블 확인 방법

접속 후, 우리가 스크립트로 밀어 넣었던 테이블 내용을 확인하려면 트리 메뉴를 아래 순서대로 펼칩니다.

1. `Servers` ➔ 내가 만든 서버명 ➔ `Databases` ➔ `postgres` ➔ `Schemas` ➔ `public` ➔ `Tables`
2. 생성된 `apt_basic`, `apt_detail`, `apt_trade`, `apt_rent` 등 확인.
3. 엑셀처럼 표로 보려면 테이블에서 마우스 우클릭 ➔ **View/Edit Data** ➔ **First 100 Rows** 클릭.
4. 직접 쿼리(SQL)를 쳐서 확인하려면 해당 DB 우클릭 ➔ **Query Tool**을 연 뒤 아래처럼 입력하고 실행(F5)합니다.
   ```sql
   -- 매매 데이터 총 보유 건수
   SELECT COUNT(*) FROM apt_trade;
   
   -- 아파트 기본 정보 및 위치 샘플 10개 조회
   SELECT apt_name, road_address, latitude, admin_dong FROM apt_basic LIMIT 10;
   ```
