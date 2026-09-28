# Terraform: 네이버 클라우드(NCP)

NCP VPC 환경에 앱 인프라를 만듭니다. provider는 `NaverCloudPlatform/ncloud` 4.0.x입니다.

| 파일 | 만드는 것 |
| --- | --- |
| network.tf | VPC, 서브넷 5개(노드·DB 프라이빗, NAT 퍼블릭, LB 프라이빗·퍼블릭), NAT Gateway, 프라이빗 라우트 |
| nks.tf | NKS 클러스터(KVM, Cilium, 감사 로그), 노드 풀(2 vCPU / 8 GB, 2~4대 자동 확장) |
| database.tf | Cloud DB for PostgreSQL(단일 인스턴스, 저장소 암호화, 백업 7일), 무작위 비밀번호 |
| storage.tf | 업로드용 Object Storage 버킷 |
| outputs.tf | Kubernetes overlay가 읽을 `deploy/k8s/overlays/ncp/generated/config.env`와 `secret.env` |

```text
Internet ─▶ ALB (lb_public) ─▶ NKS 노드 (nodes, private) ─▶ Cloud DB (database, private)
                                     │                    └▶ Object Storage
                                     └─▶ NAT Gateway ─▶ Internet (이미지 pull 등)
```

- 노드와 DB는 프라이빗 서브넷에 둡니다. DB는 노드 서브넷에서 오는 접속만 허용합니다(`client_cidr`).
- NCP는 지역별로 코드가 달라서 버전·노드 이미지·서버 사양을 하드코딩하지 않습니다. data source로 조회합니다.
  provider와 data source의 기본 하이퍼바이저는 XEN이라 모두 KVM으로 지정합니다.
- 비밀번호와 키는 git에 올라가지 않습니다.
  - NCP API 키는 환경 변수로 넘깁니다.
  - 앱용 Object Storage 키는 tfvars나 `TF_VAR_*` 환경 변수로 넘깁니다.
  - DB 비밀번호는 Terraform이 생성합니다.
  - 모두 state와 git-ignored 파일(`secret.env`)에만 저장됩니다.

## 미리 준비할 것 (콘솔)

1. **API 인증키:** Terraform용입니다(마이페이지 → 인증키 관리).
2. **앱용 서브 계정:** Sub Account에서 **Object Storage 권한만 가진** 계정을 만들고 인증키를 발급합니다. 앱이 이 키로 버킷에 접근합니다.
3. **state 버킷:** Object Storage 버킷을 하나 만듭니다(예: `dataflow-tfstate-<임의 문자>`). Terraform이 만들 수 없는 순환 의존이라 한 번만 수동으로 만듭니다.
4. **Container Registry:** Terraform 리소스가 없어서 콘솔에서 만듭니다. 주소는 `<이름>.kr.ncr.ntruss.com`입니다.
5. **(HTTPS)** 도메인과 Certificate Manager 인증서를 준비합니다. 인증서 번호는 overlay의 `ssl-certificate-no`에 넣습니다.
6. **kubeconfig 도구:** `ncp-iam-authenticator`를 설치합니다.
   메인 계정에 API 접근 제한이 켜져 있으면 IAM 인증은 서브 계정만 쓸 수 있습니다.

## 실행

```powershell
cd infra/terraform
$env:NCLOUD_ACCESS_KEY = "<API access key>"
$env:NCLOUD_SECRET_KEY = "<API secret key>"
# state 버킷 접근(S3 호환)도 같은 키를 씁니다.
$env:AWS_ACCESS_KEY_ID = $env:NCLOUD_ACCESS_KEY
$env:AWS_SECRET_ACCESS_KEY = $env:NCLOUD_SECRET_KEY

Copy-Item backend.hcl.example backend.hcl            # state 버킷 이름 입력
Copy-Item terraform.tfvars.example terraform.tfvars  # 도메인, 앱용 Object Storage 키 입력
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan                           # 만들 리소스와 비용 항목 확인
terraform apply tfplan
```

apply가 끝나면 `deploy/k8s/README.md`의 NCP 순서대로 배포합니다.

```powershell
terraform output -raw kubeconfig_command | Invoke-Expression    # kubeconfig.yaml 생성
$env:KUBECONFIG = "$PWD/kubeconfig.yaml"
kubectl get nodes
```

## 비용

아래 항목은 켜 두는 동안 **시간 단위로 과금됩니다.**
- NKS 클러스터 요금과 노드 2대
- Cloud DB for PostgreSQL
- NAT Gateway
- ALB: Ingress를 적용할 때 생성됩니다.
- Object Storage: 용량과 요청 수만큼 과금됩니다.

정확한 금액은 [NCP 요금 계산기](https://www.ncloud.com/charge/calc/ko)로 확인합니다. 위 사양(노드 2대, PostgreSQL 최소 사양 `db_ha = false`, NAT 1개, ALB 1개)을 입력하면 됩니다.
시연이 끝나면 아래 명령으로 모두 삭제합니다. 콘솔에서 만든 state 버킷과 Container Registry는 별도로 지웁니다.

```powershell
kubectl delete -k ../../deploy/k8s/overlays/ncp   # ALB는 Ingress를 지우면 삭제됩니다
terraform destroy
```

## 검증 상태

- **검증한 것:** `terraform validate`로 provider 4.0.7 스키마와 대조했습니다. 모든 리소스와 인자 이름이 맞습니다. CI에서도 fmt와 validate를 실행합니다.
- **plan 전에는 확인할 수 없는 것:** 아래 항목은 계정 권한과 지역에 따라 달라서, plan이나 apply 단계에서 확인해야 합니다.
  - `nks_cluster_type` 기본값(`SVR.VNKS.STAND.C002.M008.G003`)
  - 노드 사양 필터(2 vCPU, 8GB)
  - `k8s_version_prefix`(1.32)가 이 계정에서 사용 가능한지 여부
- **확인되지 않은 것:** state backend 설정은 Terraform S3 backend의 호환 옵션으로 작성했습니다. NCP가 공식 문서로 확인해 준 설정은 아닙니다.
