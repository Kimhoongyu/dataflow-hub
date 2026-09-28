# DataFlow Hub

포트폴리오용 멀티테넌트 데이터 처리 SaaS MVP.
목표: 프로젝트별 CSV 업로드 → Worker 비동기 처리 → 결과·이력·운영 현황 조회.

## 현재 구현: 2단계

- React + TypeScript 로그인·대시보드·프로젝트 생성/목록/상세
- FastAPI + PostgreSQL, Alembic 마이그레이션
- 사용자·조직·소속·프로젝트·로그인 세션 테이블
- Argon2 비밀번호 해시, HttpOnly 쿠키 인증 및 서버 세션 폐기
- 매 요청 조직 소속 검증과 테넌트별 접근 제한
- Docker Compose 로컬 실행과 별도 DB 기반 통합 테스트

프로젝트와 계정은 DB에 저장됩니다. CSV 업로드, Worker, 실제 처리 통계·최근 오류 집계는 후속 단계입니다.
처리 통계는 화면에서 준비 중으로 표시합니다.

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
- DB 상태: http://localhost:8000/api/health/ready
- 프런트엔드 프록시: http://localhost:5173/api/health/ready

DB 정상 시 readiness는 200과 {"status":"ok","database":"ok"}를 반환합니다.
DB 장애 시 readiness는 503이고 liveness는 200을 유지합니다.
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
4. 로그아웃 → B 계정 로그인 → B 조직의 프로젝트만 표시되는지 확인.

## 폴더

```text
frontend/src/         React 화면, API 클라이언트
backend/app/          인증, 프로젝트, DB 모델, 상태 API
backend/migrations/   Alembic 변경 이력
backend/tests/        인증·조직 격리 통합 테스트
compose.yaml          앱·DB·마이그레이션, 선택적 테스트 서비스
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

## 개발과 종료

컨테이너는 소스를 이미지에 포함합니다. 변경 후 다시 빌드합니다.

```powershell
docker compose up --build -d --wait
docker compose logs --tail 100 api
docker compose down
```

down은 일반 DB 볼륨을 보존합니다. down -v는 DB 데이터를 삭제하므로 초기화 시에만 사용합니다.
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

## 다음 단계와 운영 모니터링

1. 파일·작업 모델과 CSV 업로드
2. 별도 Worker 처리·재시도·복구
3. 결과·이력과 운영 대시보드
4. Terraform + Azure AKS / ACR / PostgreSQL / Blob Storage

운영 대시보드는 테넌트 권한이 적용된 DB 집계 API로 프로젝트별 업로드·처리 현황,
성공·실패 건수, 대기·처리 중 작업, 최근 오류를 제공합니다.
업로드는 저장 완료 시각, 처리 실적은 최종 완료 시각으로 기간 집계하고
재시도 오류는 실행 이력으로 구분합니다. 대기·처리 중은 현재 수치입니다.

후속 단계에서 JSON 로그와 요청 ID / 작업 ID를 도입합니다.
Azure에서는 메트릭을 Prometheus / Grafana, 컨테이너 로그를 Azure Monitor / Log Analytics에 연결합니다.
작업 ID·사용자 ID는 Prometheus 라벨로 사용하지 않습니다.
현재 health API만 구현됐으며 메트릭 수집·운영 집계·경보는 아직 구현하지 않았습니다.
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
