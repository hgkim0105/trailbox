# Trailbox Hub — Deployment

세 가지 배포 형태를 지원합니다. 가장 가벼운 것부터:

## 1. 단일 .exe (Windows, 사내 LAN)

```powershell
.\.venv\Scripts\python.exe build.py
# dist\Trailbox-hub.exe 생성

# 실행 (PowerShell)
$env:TRAILBOX_HUB_ADMIN_USER = "admin"
$env:TRAILBOX_HUB_ADMIN_PASS = "<choose-something-strong-12chars+>"
$env:TRAILBOX_HUB_DATA       = "C:\trailbox-hub-data"
.\dist\Trailbox-hub.exe
```

처음 실행 시 위 env 로 admin 계정이 자동 생성됩니다. env 가 비어 있으면 콘솔에 1회용
setup-token 이 출력되고 `{data}/.setup_token` 에도 기록됩니다. 브라우저로 `/setup` 에 접속해
이 토큰으로 admin 을 생성하세요. 두 번째 부팅부터는 이 흐름이 동작하지 않습니다 (멱등).

기본 바인드는 `127.0.0.1:8765`. 사내 LAN 노출은 `TRAILBOX_HUB_HOST=0.0.0.0` 추가.

### Windows 인스톨러 사용 시 (Phase 0.8.0+)

`Trailbox-Setup.exe` 를 실행하고 «Hub» 컴포넌트를 선택하면 마법사가 admin username/password
를 묻습니다. 입력값은 `{app}\hub.env` 로 기록되고 Hub 첫 실행 시 자동 소비된 뒤 즉시 삭제됩니다.

## 2. Docker (Linux / macOS / Windows-WSL)

```bash
cp .env.example .env
# .env 의 TRAILBOX_HUB_ADMIN_USER / TRAILBOX_HUB_ADMIN_PASS 를 채우거나
# 빈 채로 두고 첫 부팅 후 stderr 의 setup-token 으로 /setup 진행
docker compose up -d
```

기본 `docker-compose.yml` 은 `127.0.0.1:8765` 만 바인드. 사내 다른 머신에서 접근하려면
`ports` 를 `"0.0.0.0:8765:8765"` 로 변경.

세션 데이터와 SQLite (`hub.db`) 는 호스트의 `./hub_data/` 로 마운트됩니다.

## 3. Docker + Caddy (공용 인터넷, 자동 TLS)

1. 도메인 (예: `hub.example.com`) DNS A 레코드를 서버 IP 로 등록
2. `.env` 에 `TRAILBOX_HUB_DOMAIN=hub.example.com` 추가
3. `docker-compose.yml` 의 `caddy` 서비스와 `volumes:` 블록 주석 해제
4. `hub` 서비스의 `ports:` 매핑 주석 처리 (Caddy 뒤에 숨김)
5. `docker compose up -d`

Caddy 가 첫 요청 시 Let's Encrypt 인증서를 자동 발급/갱신합니다.

## 계정 / 클라이언트 설정 (0.5.0+)

### 회원가입 → 승인 → 토큰 발급 흐름

1. **사용자가 Trailbox GUI** 에서 «허브 설정» → «회원가입» 탭 → username/password 입력
2. **운영자(admin)** 가 `https://hub.example.com/admin/users` 에서 pending 사용자 «승인»
3. **GUI 다이얼로그** 가 자동으로 다시 로그인 → 토큰 발급 → 저장

운영자가 «설정» 에서 **자동 승인 (auto_approve_registration)** 을 켜면 가입과 동시에 활성화됩니다.

### 토큰만 미리 받기 (수동)

브라우저로 `https://hub.example.com` 접속 → 로그인 → «내 계정» → «새 토큰 발급» →
출력된 평문 토큰을 GUI 의 «고급 (수동 토큰)» 탭에 붙여넣기.

### 레거시 service-token 호환

기존 0.4.x 클라이언트나 자동화 스크립트는 `TRAILBOX_HUB_TOKEN` 환경변수로 운영되던 단일
공유 토큰을 그대로 보낼 수 있습니다. 새 서버에서는 이 토큰이 **첫 admin 의 service-token**
으로 매핑되므로 기존 클라이언트 코드는 무변경. 신규 배포에선 사용을 권장하지 않습니다.

## AI MCP 연결

`Trailbox-mcp.exe` 에 두 환경변수만 설정해서 등록하면 Hub 의 세션을 그대로 조회 가능:

```jsonc
// Claude Desktop config
{
  "mcpServers": {
    "trailbox-hub": {
      "command": "C:\\path\\to\\Trailbox-mcp.exe",
      "env": {
        "TRAILBOX_HUB_URL": "https://hub.example.com",
        "TRAILBOX_HUB_TOKEN": "<per-user-token-from-내-계정>"
      }
    }
  }
}
```

`TRAILBOX_HUB_URL` 이 빠지면 자동으로 로컬 `output/` 폴더 모드로 동작.

## 운영 메모

- **DB**: `hub_data/hub.db` (SQLite, WAL). 백업은 디렉토리 통째로 tar.gz.
- **저장 정책**: `TRAILBOX_HUB_RETENTION_DAYS=30` 으로 자동 정리. 0 이면 영구 보관.
- **수동 정리**: `POST /api/admin/prune?dry_run=true` 로 미리보기, `dry_run=false` 로 실제 삭제 (admin 인증 필요).
- **백업**: `hub_data/` 디렉토리 전체. mp4/jsonl/meta 외에 `hub.db`/`.secret_key` 까지 포함.
- **업로드 캡**: 기본 8GB. 다른 값은 `TRAILBOX_HUB_MAX_UPLOAD_MB`.
- **감사 로그**: 웹 `/admin/audit` 또는 `GET /api/admin/audit?limit=N`.

## 비밀번호 복구

| 상황 | 방법 |
|---|---|
| 일반 사용자 분실 | admin 이 웹 `/admin/users` → 해당 사용자 «reset password» → 임시 비번 1회 노출 → 전달 |
| admin 이 2명 이상, 한 명 분실 | 다른 admin 이 위 방법으로 재설정 |
| admin 1명이고 본인 분실 | Hub 호스트 디스크 접근 권한으로 CLI 사용 (아래) |

### CLI 복구 (Trailbox-hub.exe / Docker)

```powershell
# Windows (설치 폴더에서, 또는 TRAILBOX_HUB_DATA 지정):
cd "C:\Program Files\Trailbox"
.\Trailbox-hub.exe reset-password -u admin
New password: ********
Confirm:      ********
OK: password reset for 'admin' (role=admin, status=active)
```

```bash
# Docker:
docker compose exec hub python hub_entry.py reset-password -u admin

# 또는 비대화형 (셸 히스토리에 비번이 남으니 주의):
docker compose exec hub python hub_entry.py reset-password -u admin -p '<new>'
```

옵션:
- `-u/--username` : 대상 계정 (필수)
- `-p/--password` : 비밀번호. 생략하면 getpass 프롬프트 (이력에 안 남음, 권장)
- `--require-change` : 다음 로그인 때 강제 변경 플래그 설정 (다른 사용자의 임시 비번 발급 시 권장)

CLI 사용은 Hub 가 떠 있든 꺼져 있든 동작합니다 (SQLite WAL). 액션은 audit_log 에 `actor_id=NULL, via=cli` 로 기록됩니다.
