# DataFlow Hub

포트폴리오용 멀티테넌트 데이터 처리 SaaS MVP.
목표: 프로젝트별 CSV 업로드 → Worker 비동기 처리 → 결과·이력·운영 현황 조회.

## 현재 구현: 5단계

- React + TypeScript 로그인·대시보드·프로젝트 생성/목록/상세
- FastAPI + PostgreSQL, Alembic 마이그레이션
- 사용자·조직·소속·프로젝트·로그인 세션 테이블
- Argon2 비밀번호 해시, HttpOnly 쿠키 인증 및 서버 세션 폐기
- 매 요청 조직 소속 검증과 테넌트별 접근 제한
- CSV 업로드 → S3 호환 오브젝트 스토리지(로컬 SeaweedFS, 배포 시 NCP Object Storage) 저장 → 처리 작업 대기열 등록
- 별도 Worker가 대기 작업을 가져가 처리하고 결과 CSV를 저장 (검증·정제·변환·집계)
- 재시도(지수 백오프), 멈춘 작업 복구(heartbeat), 여러 Worker 동시 실행
- 작업 목록·상세·상태 이력 조회, 결과 CSV 다운로드, 대시보드 최근 작업
- 운영 모니터링 대시보드: 기간별 업로드·성공·실패·성공률·처리 시간, 처리 추이, 프로젝트별 현황, 최근 오류, Worker·대기열 상태
- 요청 ID(X-Request-ID)를 작업에 저장해 업로드 요청과 로그를 연결
- Docker Compose 로컬 실행과 별도 DB 기반 통합 테스트


## 시작하기 (PowerShell)

Docker Desktop을 Linux 컨테이너 모드로 실행하고 프로젝트 루트에서:

```powershell
# .env가 이미 있으면 복사하지 않습니다.
Copy-Item .env.example .env
docker compose up --build -d --wait
docker compose exec api python -m app.seed --local
docker compose ps
```

첫 실행은 이미지·의존성 다운로드가 필요합니다.
DB 준비 → migrate 성공 → API 준비 → frontend 순서로 시작합니다.
migrate 컨테이너의 Exited (0)은 정상 완료입니다.
seed는 명시적으로 실행하며 기존 계정·비밀번호·프로젝트를 덮어쓰지 않습니다.

- 웹: http://localhost:5173
- API 문서: http://localhost:8000/docs
- 서버 상태: http://localhost:8000/api/health/live
- DB·저장소 상태: http://localhost:8000/api/health/ready
- 프런트엔드 프록시: http://localhost:5173/api/health/ready

정상 시 readiness는 200과 {"status":"ok","database":"ok","storage":"ok"}를 반환합니다.
DB나 저장소 장애 시 readiness는 503과 실패한 항목을 반환하고, liveness는 200을 유지합니다.
포트 충돌은 .env의 FRONTEND_PORT / API_PORT로 조정합니다. DB 포트는 호스트에 공개하지 않습니다.

## 로컬 데모 계정

| 계정 | 조직 | 비밀번호 |
| --- | --- | --- |
| demo-a@dataflow.local | Flight Operations | Demo-local-2026! |
| demo-b@dataflow.local | Ground Services | Demo-local-2026! |

이 계정과 비밀번호는 로컬 시연 전용입니다.

1. A 계정 로그인 → 프로젝트 메뉴 → 프로젝트 생성.
2. 프로젝트 이름을 눌러 상세 확인.
3. 새로고침 후 프로젝트가 유지되는지 확인.
4. 프로젝트 상세에서 CSV 파일과 처리 유형을 골라 업로드 → 대기 → 처리 중 → 완료로 자동 갱신.
5. 파일 이름을 눌러 작업 상세와 처리 이력 확인, 결과 CSV 다운로드.
6. 로그아웃 → B 계정 로그인 → B 조직의 프로젝트와 작업만 표시되는지 확인.

## 폴더

```text
frontend/src/         React 화면, API 클라이언트
backend/app/          인증, 프로젝트, 업로드·작업, 오브젝트 스토리지, 모니터링, DB 모델, 상태 API
backend/worker/       작업 Worker(main.py)와 CSV 처리 함수(processors.py)
backend/migrations/   Alembic 변경 이력
backend/tests/        인증·조직 격리·업로드 통합 테스트
compose.yaml          앱·Worker·DB·S3(SeaweedFS)·마이그레이션, 선택적 테스트 서비스
deploy/local/         로컬 SeaweedFS S3 인증 설정
.env.example          로컬 설정 예시
```

## API 및 인증 정책

| 메서드 | 경로 | 동작 |
| --- | --- | --- |
| POST | /api/auth/login | 이메일·비밀번호로 세션 생성 |
| POST | /api/auth/logout | 세션 폐기 및 쿠키 삭제 |
| GET | /api/auth/me | 현재 사용자 및 소속 조직 |
| GET / POST | /api/tenants/{tenant_id}/projects | 목록 / 생성 |
| GET | /api/tenants/{tenant_id}/projects/{project_id} | 상세 |
| POST | /api/tenants/{tenant_id}/projects/{project_id}/jobs | CSV 업로드(multipart: file, job_type, notes) 후 작업 등록 |
| GET | /api/tenants/{tenant_id}/jobs | 작업 목록 (project_id, status 필터) |
| GET | /api/tenants/{tenant_id}/jobs/{job_id} | 작업 상세와 상태 이력 |
| GET | /api/tenants/{tenant_id}/jobs/{job_id}/result | 결과 CSV 다운로드 (UTF-8 BOM) |
| GET | /api/tenants/{tenant_id}/monitoring?period=24h\|7d\|30d | 운영 현황 집계 (대시보드 전체) |

목록은 offset(기본 0), limit(기본 20, 최대 100)을 지원합니다.
조직 소속을 매번 검증하고 타 조직과 없는 리소스 모두 404를 반환합니다.
본문 tenant_id는 허용하지 않으며 검증된 경로에서 결정합니다.
같은 조직의 동일 프로젝트명은 409, 빈 이름 등 잘못된 입력은 422입니다.

세션은 8시간 유효하고 무작위 토큰의 SHA-256 해시만 DB에 저장합니다.
쿠키는 HttpOnly, SameSite=Lax, Path=/api를 사용합니다.
로그인·로그아웃 포함 쓰기 요청은 허용된 Origin이 필수입니다.
브라우저는 자동 전송하지만 curl 등에서는 Origin 헤더를 명시해야 합니다.
Compose는 로컬 포트 설정을 Origin 허용 목록에 반영합니다.

배포 시 HTTPS, COOKIE_SECURE=true, 정확한 ALLOWED_ORIGINS,
로그인 시도 제한, 세션 정기 정리와 실제 계정 발급을 적용해야 합니다.
공개된 데모 비밀번호는 배포 환경에 사용하지 않습니다.

## CSV 업로드 정책

- 확장자 .csv, UTF-8(BOM 허용), 10MB 이하(MAX_UPLOAD_BYTES). 빈 파일·바이너리는 422, 초과는 413.
- Content-Length가 한도를 넘으면 본문을 읽기 전에 413으로 거절합니다. 배포 시 Ingress에도 본문 크기 제한을 둡니다.
- 처리 유형: validation(검증), cleansing(정제), transformation(변환), aggregation(집계).
- 저장 경로는 {tenant_id}/{project_id}/{file_id}.csv이며 사용자가 보낸 파일 이름은 경로에 쓰지 않습니다.
  원본 이름과 SHA-256 해시는 uploaded_files에 저장합니다.
- 저장소 장애 시 503을 반환하고 DB에는 아무것도 기록하지 않습니다.
  DB 기록이 실패하면 방금 올린 객체를 삭제합니다. 삭제마저 실패하면 orphan_blob 로그를 남깁니다.
- 업로드 시점에는 형식만 가볍게 확인하고, 행 단위 검증은 Worker가 담당합니다.

저장소는 S3 API(boto3)로 접근합니다. 로컬은 S3 호환 SeaweedFS이고, NCP Object Storage도 S3 호환이라
S3_ENDPOINT_URL(NCP: https://kr.object.ncloudstorage.com), S3_REGION, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET만 바꾸면 같은 코드가 동작합니다.
Compose의 S3 키는 deploy/local/seaweedfs-s3.json과 짝을 이루는 로컬 전용 값입니다.

- S3 호환 저장소는 최신 botocore의 기본 CRC 체크섬을 지원하지 않을 수 있어서, 체크섬은 필요할 때만 보냅니다.
- 요청 처리 경로는 최대 2회 시도합니다(S3_MAX_ATTEMPTS). readiness 확인은 probe 제한 시간 안에 응답하도록 재시도하지 않습니다.

## Worker

API와 같은 이미지를 `python -m worker.main`으로 실행합니다.

```text
queued ──claim(SKIP LOCKED)──▶ processing ──▶ completed
   ▲                              │
   └── 일시 오류: 10·20초 후 재시도 ┤
                                  └──▶ failed (데이터 오류, 또는 최대 3회 시도 초과)
```

- **작업 가져가기:** `SELECT … FOR UPDATE SKIP LOCKED`로 가장 오래된 대기 작업을 가져갑니다.
  Worker가 여러 개여도 같은 작업을 두 번 처리하지 않습니다. `docker compose up -d --scale worker=3`로 늘릴 수 있습니다.
- **잠금 범위:** 파일을 처리하는 동안에는 DB 잠금을 잡지 않습니다. 결과는 이 Worker가 아직 작업을 소유하고 있을 때만 기록합니다.
- **오류 분류:**
  - 데이터 오류(INVALID_CSV, EMPTY_FILE, SCHEMA_MISMATCH, FILE_MISSING)는 재시도해도 결과가 같으므로 즉시 실패로 처리합니다.
  - 일시 오류(STORAGE_ERROR, INTERNAL)는 지수 백오프로 최대 3회까지 시도합니다.
- **멈춘 작업 복구:**
  - Worker는 10초마다 worker_heartbeats를 갱신합니다.
  - 60초 넘게 갱신이 없는 Worker의 processing 작업은 다른 Worker가 다시 대기열로 돌려놓습니다.
  - 최대 시도 횟수를 넘긴 작업은 WORKER_LOST로 실패 처리합니다.
- **정상 종료:** SIGTERM을 받으면 처리 중인 작업을 끝낸 뒤 종료합니다(stop_grace_period 30초).
- **행 단위 오류:** 결과 리포트와 error_row_count에 기록하고, 작업 자체는 완료로 처리합니다.

| 처리 유형 | 동작 | 결과 CSV |
| --- | --- | --- |
| validation | 열 개수 불일치, 빈 값 검사 | 오류 목록 (line, column, error) |
| cleansing | 공백 제거, 중복 행·형식 오류 행 제거 | 정제된 데이터 |
| transformation | 열 이름 snake_case, 천 단위 쉼표 숫자 변환 | 변환된 데이터 |
| aggregation | 열별 개수·고유값, 숫자 열 min/max/sum/mean | 열 통계 |

환경 변수: WORKER_POLL_SECONDS(2), WORKER_HEARTBEAT_SECONDS(10), WORKER_STALE_SECONDS(60),
WORKER_MAX_ATTEMPTS(3), WORKER_RETRY_BASE_SECONDS(10).

## 검증

```powershell
npm --prefix frontend run lint
npm --prefix frontend run build
docker compose --profile test run --build --rm tests
docker compose --profile test stop test-db
docker compose exec api alembic current
docker compose exec api alembic check
```

테스트는 별도 dataflow_test DB와 tmpfs를 사용하고 테스트별 트랜잭션을 롤백합니다.
일반 DB와 데모 데이터에는 영향을 주지 않습니다. 테스트 DB 중지 시 테스트 데이터는 사라집니다.
마이그레이션과 모델 일치, 로그인 실패·세션 만료·폐기·교체, Origin 검증,
타 조직 목록·상세·생성 차단, 중복·빈 이름·페이지 조회를 검증합니다.
업로드 테스트는 메모리 저장소를 주입해 S3 없이 실행하며, 타 조직 업로드·조회 차단,
형식·인코딩·크기 거절, 저장소 장애 503, DB 실패 시 객체 정리, 상태 이력을 검증합니다.
Worker 테스트는 처리 함수 4종과 오류 분류, 완료·결과 다운로드, 재시도 백오프와 최대 시도,
멈춘 작업 복구, 소유권을 잃은 Worker의 결과 무시를 검증합니다.
실제 두 DB 연결로 SKIP LOCKED가 서로 다른 작업을 가져가는지도 확인합니다.

## 개발과 종료

컨테이너는 소스를 이미지에 포함합니다. 변경 후 다시 빌드합니다.

```powershell
docker compose up --build -d --wait
docker compose logs --tail 100 api
docker compose down
```

down은 DB와 S3 볼륨을 보존합니다. down -v는 DB 데이터와 업로드 파일을 삭제하므로 초기화 시에만 사용합니다.
이미 생성된 DB의 계정은 .env 수정만으로 변경되지 않습니다.

프런트엔드만 로컬 개발할 때는 Node.js 24 환경에서:

```powershell
cd frontend
npm ci
npm run dev
```

로그인과 조회에는 API가 필요합니다. 기본 프록시 대상은 http://localhost:8000 입니다.
API 포트를 바꿨다면 실행 전 $env:API_PROXY_TARGET = 'http://localhost:변경한포트'를 설정합니다.
Vite 컨테이너는 개발용이며 배포 시 정적 빌드 제공 방식으로 변경합니다.

새 DB 변경은 backend에서 Alembic revision으로 추가하고 검토 후 적용합니다.
기존 마이그레이션은 수정하지 않습니다. 컨테이너 안에서 생성한 revision은 호스트에 자동 저장되지 않으므로
로컬 Python 개발 환경에서 생성하거나 생성 파일을 호스트의 backend/migrations/versions로 복사해야 합니다.

## 운영 모니터링

대시보드는 모니터링 API 한 번으로 그리며 10초마다 갱신합니다. 모든 집계는 조직 범위로 제한됩니다.

| 항목 | 기준 |
| --- | --- |
| 업로드 | 기간 내 업로드 시각 |
| 완료·실패·성공률 | 기간 내 종료 시각. 성공률 = 완료 ÷ (완료 + 실패) |
| 평균·p95 처리 시간 | 기간 내 완료 작업의 duration_ms |
| 재시도 | 기간 내 processing → queued 이벤트 수 |
| 대기열·처리 중·최장 대기 | 현재 값 |
| 멈춘 작업 | heartbeat가 끊긴 Worker가 잡고 있는 processing 작업 |
| Worker 정상/중단 | 플랫폼 공통. WORKER_STALE_SECONDS 이내 heartbeat 여부, 개수만 노출 |
| 처리 추이 | 24h는 시간별, 7d·30d는 일별. DASHBOARD_TIMEZONE(기본 Asia/Seoul) 기준, 빈 구간은 0 |
| 최근 오류 | 실패 작업과 오류 후 재시도 대기 작업 최근 10건, 오류 코드별 건수 |

- **상태 표시:** Worker가 없으면 치명, 멈춘 작업이나 5분 넘게 기다린 작업이 있으면 경고로 표시합니다. 색만이 아니라 아이콘과 문구로도 구분합니다.
- **차트:** 완료(파랑)와 실패(빨강) 누적 막대입니다. 색각 이상 구분 검사를 통과한 조합이고, 범례·툴팁·표 보기를 함께 제공합니다.
- **집계 방식:** 인덱스(tenant_id·status, tenant_id·project_id·created_at)를 활용해 요청 시점에 바로 집계합니다.
  데이터가 커지면 일 단위 요약 테이블이나 materialized view로 옮깁니다.

## 다음 단계

1. JSON 구조화 로그, Prometheus 메트릭(/metrics: 처리량·처리 시간 histogram·대기열 길이)
2. GitHub Actions CI (테스트, 이미지 빌드)
3. Terraform으로 네이버 클라우드(NCP) 배포

| 구성 요소 | 로컬 (Compose) | NCP |
| --- | --- | --- |
| 컨테이너 실행 | Docker Compose | Ncloud Kubernetes Service (NKS) |
| 이미지 저장소 | 로컬 빌드 | NCP Container Registry |
| DB | postgres 컨테이너 | Cloud DB for PostgreSQL |
| 파일 저장소 | SeaweedFS (S3 호환) | Object Storage (S3 호환) |
| 인프라 코드 | compose.yaml | Terraform (NCP 공식 provider) |

네트워크(VPC·서브넷), NKS, Cloud DB, Object Storage 버킷, Container Registry를 Terraform으로 만들고,
Worker는 대기 작업 수 기준으로 확장합니다(예: KEDA PostgreSQL scaler).

모니터링 확장: 앱 안의 운영 대시보드(DB 집계)는 그대로 두고,
NKS에 Prometheus / Grafana를 설치해 /metrics를 수집합니다. 서버·DB 인프라 지표와 로그는 NCP 모니터링 서비스로 보냅니다.
작업 ID·사용자 ID처럼 값이 계속 늘어나는 항목은 Prometheus 라벨로 쓰지 않습니다.
메트릭 수집과 경보는 아직 구현하지 않았습니다.

## 계정 정보 변경 (로컬 관리자)

프로젝트 루트의 대화형 터미널에서 다음 명령을 실행합니다.

```powershell
docker compose exec api python -m app.manage_user
```

현재 이메일 → 새 이메일 → 새 이름 → 비밀번호 변경 여부 순서로 입력합니다.
새 이메일·이름은 Enter로 유지하고, 비밀번호 변경에는 y를 입력합니다.
새 비밀번호는 12~256자이며 화면에 표시되지 않고 두 번 확인합니다.
Ctrl+C로 취소할 수 있으며 비밀번호 불일치·중복 이메일 등 오류 시 저장하지 않습니다.
변경하면 해당 사용자의 모든 로그인 세션을 만료합니다. 조직 소속과 프로젝트는 유지됩니다.

현재 이메일을 지정할 수도 있습니다.

```powershell
docker compose exec api python -m app.manage_user --email demo-a@dataflow.local
```

-T 옵션은 사용하지 마세요. 비밀번호를 명령행 인자로 받지 않으므로 셸 기록에 남지 않습니다.
이 명령은 서버/DB 접근 권한을 가진 로컬 관리자용이며 웹의 사용자 본인 변경 기능은 아닙니다.
새 코드가 컨테이너에 없으면 docker compose up --build -d --wait로 먼저 반영합니다.
데모 이메일을 변경한 뒤 seed --local을 다시 실행하면 기존 데모 이메일로 별도 계정·조직이 생성될 수 있습니다.
계정 변경에는 seed가 아닌 이 관리 명령을 사용하세요.
