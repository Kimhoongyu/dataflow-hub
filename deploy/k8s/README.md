# Kubernetes 배포

kustomize로 구성합니다. 공통 설정(base) 위에 환경별 설정(overlay)을 덧씌웁니다.

```text
base/                 API·Worker·Frontend Deployment, Service, HPA, PDB, 마이그레이션 Job, Ingress, ConfigMap
overlays/local/       kind 등 로컬 클러스터: 클러스터 안의 PostgreSQL·SeaweedFS, 로컬 이미지, nginx Ingress
overlays/ncp/         네이버 클라우드 NKS: ALB Ingress, NodePort, Container Registry, Terraform이 만든 설정 값
components/keda/      선택: 대기 작업 수에 따라 Worker 자동 확장 (KEDA 필요)
```

## 공통 설계

- **이미지:** API와 Worker는 같은 이미지를 쓰고 실행 명령만 다릅니다.
- **실행 권한:** 모든 컨테이너가 root가 아닌 사용자로 실행됩니다.
  - 루트 파일 시스템은 읽기 전용이고, 쓰기가 필요한 /tmp만 emptyDir로 붙입니다.
  - Linux capability는 모두 제거하고 seccomp RuntimeDefault를 적용합니다.
- **API:**
  - readiness는 DB와 저장소를 확인하고, liveness는 프로세스만 확인합니다.
  - 무중단 배포를 위해 롤링 업데이트는 maxUnavailable 0으로 설정합니다.
  - 복제본은 HPA(CPU 70%) 기준 2~6개, PDB로 최소 1개를 유지합니다.
- **Worker:**
  - 종료 유예 시간은 60초입니다. SIGTERM을 받으면 처리 중인 작업을 끝낸 뒤 종료합니다.
  - 멈춘 작업은 앱의 heartbeat 복구가 담당합니다.
- **마이그레이션:** 별도 Job으로 한 번만 실행합니다. API 복제본 여러 개가 동시에 마이그레이션하는 경합을 피하기 위해서입니다.
- **Ingress:** 도메인 하나에서 /api는 API로, 나머지는 Frontend로 보냅니다. 브라우저 입장에서 같은 출처라 쿠키와 Origin 검사가 그대로 동작합니다.
  /metrics는 외부로 노출하지 않고, Prometheus가 pod annotation(prometheus.io/*)을 보고 수집합니다.
- **POSTGRES_HOST:** 클러스터 전체에서 통하는 전체 이름(FQDN)을 씁니다. KEDA operator는 다른 네임스페이스에서 같은 값으로 DB에 접속하기 때문입니다.

## 로컬 클러스터에서 실행 (kind)

```powershell
kind create cluster --name dataflow --config deploy/k8s/kind.yaml
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.1/deploy/static/provider/kind/deploy.yaml
kubectl -n ingress-nginx wait --for=condition=ready pod -l app.kubernetes.io/component=controller --timeout=240s

docker build --target runtime -t dataflow-hub-api:local backend
docker build --target runtime -t dataflow-hub-frontend:local frontend
kind load docker-image --name dataflow dataflow-hub-api:local dataflow-hub-frontend:local

kubectl apply -k deploy/k8s/overlays/local
kubectl -n dataflow wait --for=condition=complete job/migrate --timeout=240s
kubectl -n dataflow exec deploy/api -- python -m app.seed --local
```

http://localhost:18088 에서 접속합니다. 첫 시작 때 DB가 준비되기 전이면 migrate Job과 Worker가 몇 번 재시작한 뒤 정상화됩니다.
정리할 때는 `kind delete cluster --name dataflow`를 실행합니다.

KEDA까지 확인하려면 KEDA를 설치하고, overlay에 `components: [../../components/keda]`를 추가해서 적용합니다.

```powershell
kubectl apply --server-side -f https://github.com/kedacore/keda/releases/download/v2.17.0/keda-2.17.0.yaml
```

## NCP (NKS)

- **ALB Ingress:** KVM 클러스터에는 NCP ALB Ingress Controller가 기본으로 설치되어 있습니다(`ingressClassName: alb`).
  Ingress 하나가 ALB 하나를 만들고, 대상 Service는 NodePort여야 합니다.
- **HTTPS:** [overlays/ncp/ingress-alb.yaml](overlays/ncp/ingress-alb.yaml)의 `ssl-certificate-no`에 Certificate Manager 인증서 번호를 넣어야 합니다.
- **설정 값:** `generated/config.env`와 `generated/secret.env`는 git에 올라가지 않습니다.
  Terraform output으로 자동 생성하도록 연결할 예정이고, 그 전까지는 `*.example`을 복사해 직접 채웁니다.
- **이미지 pull:** Container Registry는 NCP 콘솔에서 만듭니다(Terraform 리소스 없음). pod가 이미지를 받아올 수 있도록 pull용 Secret을 만듭니다.

```powershell
kubectl -n dataflow create secret docker-registry ncr --docker-server=<registry>.kr.ncr.ntruss.com --docker-username=<access key> --docker-password=<secret key>
```

배포 순서:

1. migrate Job을 삭제하고 다시 적용합니다. Job 스펙은 수정할 수 없기 때문입니다.
2. `kubectl apply -k deploy/k8s/overlays/ncp`
3. `kubectl -n dataflow wait --for=condition=complete job/migrate`
