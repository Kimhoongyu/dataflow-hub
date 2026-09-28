# DataFlow Hub

포트폴리오용 멀티테넌트 데이터 처리 SaaS MVP.

목표: 프로젝트별 CSV 업로드 → 별도 Worker에서 비동기 처리 → 결과·이력·운영 현황 조회.

## 현재 구현 범위: 1단계

- React + TypeScript + Vite 대시보드 시제품
- FastAPI 서버와 liveness/readiness API
- SQLAlchemy + psycopg를 통한 PostgreSQL 연결
- Docker Compose 로컬 실행 및 DB 데이터 볼륨

현재 화면의 사용자, 프로젝트, 통계, 작업은 데모 데이터입니다.
작업 추가는 브라우저 메모리에만 반영됩니다.
실제 업로드, 로그인, 테넌트 격리, Worker, DB 기반 운영 대시보드는 후속 단계입니다.

## 폴더 구조

```text
frontend/       React 앱과 Vite 설정
backend/app/    FastAPI 앱과 DB 연결
compose.yaml    로컬 frontend / api / db
.env.example    로컬 환경 변수 예시
```

## 로컬 실행 (PowerShell)

Docker Desktop을 Linux 컨테이너 모드로 실행한 뒤 프로젝트 루트에서:

```powershell
Copy-Item .env.example .env
docker compose up --build -d --wait
docker compose ps
```

.env가 이미 있으면 복사하지 않고 기존 설정을 사용합니다.
첫 실행은 이미지와 의존성 다운로드 때문에 시간이 걸릴 수 있습니다.

- 웹: http://localhost:5173
- API 문서: http://localhost:8000/docs
- 서버 상태: http://localhost:8000/api/health/live
- DB 연결 상태: http://localhost:8000/api/health/ready
- 프런트엔드 프록시: http://localhost:5173/api/health/ready

정상 readiness 응답: `{"status":"ok","database":"ok"}`
DB 연결 불가 시 readiness는 HTTP 503을 반환하고 liveness는 HTTP 200을 유지합니다.
DB 준비 완료 후 API, API 준비 완료 후 프런트엔드를 시작합니다.

포트 충돌 시 .env의 FRONTEND_PORT / API_PORT를 바꾸고 다시 실행합니다.
DB 포트는 호스트에 공개하지 않습니다. 로컬 예시 비밀번호는 배포용으로 사용하지 않습니다.

## 확인 및 종료

```powershell
docker compose logs --tail 100 api
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
docker compose exec db psql -U dataflow -d dataflow_hub -c "SELECT 1;"
docker compose down
```

DB 사용자나 이름을 변경했다면 psql 인자도 맞춰주세요.
`docker compose down`은 DB 볼륨을 보존합니다.
`docker compose down -v`는 저장된 DB 데이터를 삭제하므로 초기화할 때만 사용합니다.
이미 생성한 DB의 계정은 .env 수정만으로 변경되지 않습니다.

컨테이너는 소스를 이미지에 포함합니다. 코드 변경 후 `docker compose up --build -d --wait`로 반영합니다.
Vite 컨테이너는 로컬 개발용이며 실제 배포 시 정적 빌드 제공 방식으로 전환합니다.

## 프런트엔드만 로컬 개발

Node.js 24 환경에서:

```powershell
cd frontend
npm ci
npm run dev
```

기본 API 프록시 대상은 http://localhost:8000 입니다.
Compose API 포트를 바꿨다면 실행 전에 `$env:API_PROXY_TARGET = 'http://localhost:변경한포트'`를 설정합니다.
API 없이도 현재 데모 화면은 사용할 수 있습니다.

## 다음 구현 순서

1. 테넌트·사용자·프로젝트·파일·작업 모델과 마이그레이션, 인증 및 테넌트 격리
2. 프로젝트 API 및 화면 연결
3. CSV 업로드와 작업 등록
4. 별도 Worker의 처리·재시도·복구
5. 결과·이력 조회 및 DB 집계 기반 운영 대시보드
6. 격리·실패·복구 테스트와 데모 시나리오
7. Terraform + Azure AKS / ACR / PostgreSQL / Blob Storage

## 운영 모니터링 설계

MVP는 테넌트 권한이 적용된 DB 집계 API로 프로젝트별 업로드·처리 현황,
성공·실패 건수, 현재 대기·처리 중 작업, 최근 오류를 제공합니다.
업로드는 저장 완료 시각, 처리 실적은 최종 완료 시각으로 기간 집계하며,
재시도 오류는 실행 이력으로 분리합니다. 대기·처리 중은 현재 수치입니다.

API·Worker 구현 단계에서 JSON 로그와 요청 ID / 작업 ID를 도입합니다.
후속 Azure 단계에서 메트릭은 Prometheus / Grafana,
컨테이너 로그는 Azure Monitor / Log Analytics로 연결합니다.
작업 ID와 사용자 ID 등 값이 계속 늘어나는 항목은 Prometheus 라벨로 쓰지 않습니다.
현재 health API는 그 기반이며, 메트릭 수집·운영 집계·경보는 아직 구현하지 않았습니다.
