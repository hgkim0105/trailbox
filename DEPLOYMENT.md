# Trailbox Hub — Deployment

세 가지 배포 형태를 지원합니다. 가장 가벼운 것부터:

## 1. 단일 .exe (Windows, 사내 LAN)

```powershell
.\.venv\Scripts\python.exe build.py
# dist\Trailbox-hub.exe 생성

# 실행 (PowerShell)
$env:TRAILBOX_HUB_TOKEN = "<token>"
$env:TRAILBOX_HUB_DATA  = "C:\trailbox-hub-data"
.\dist\Trailbox-hub.exe
```

기본 바인드는 `127.0.0.1:8765`. 사내 LAN 노출은 `TRAILBOX_HUB_HOST=0.0.0.0` 추가 (이때 토큰 필수, 미설정 시 부팅 거부).

## 2. Docker (Linux / macOS / Windows-WSL)

```bash
cp .env.example .env
# .env 의 TRAILBOX_HUB_TOKEN 을 진짜 토큰으로 교체
docker compose up -d
```

기본 `docker-compose.yml` 은 `127.0.0.1:8765` 만 바인드. 사내 다른 머신에서 접근하려면 `ports` 를 `"0.0.0.0:8765:8765"` 로 변경.

세션 데이터는 호스트의 `./hub_data/` 로 마운트됩니다.

## 3. Docker + Caddy (공용 인터넷, 자동 TLS)

1. 도메인 (예: `hub.example.com`) DNS A 레코드를 서버 IP 로 등록
2. `.env` 에 `TRAILBOX_HUB_DOMAIN=hub.example.com` 추가
3. `docker-compose.yml` 의 `caddy` 서비스와 `volumes:` 블록 주석 해제
4. `hub` 서비스의 `ports:` 매핑 주석 처리 (Caddy 뒤에 숨김)
5. `docker compose up -d`

Caddy 가 첫 요청 시 Let's Encrypt 인증서를 자동 발급/갱신합니다.

## 클라이언트 설정

Trailbox GUI 에서:
1. **세션 뷰어 열기** → **허브 설정**
2. Hub URL (`http://hub.local:8765` 또는 `https://hub.example.com`) + API 토큰 입력
3. **연결 테스트** 로 검증 → **OK**

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
        "TRAILBOX_HUB_TOKEN": "<token>"
      }
    }
  }
}
```

`TRAILBOX_HUB_URL` 이 빠지면 자동으로 로컬 `output/` 폴더 모드로 동작.

## 운영 메모

- **저장 정책**: `TRAILBOX_HUB_RETENTION_DAYS=30` 으로 자동 정리. 0 이면 영구 보관.
- **수동 정리**: `POST /api/admin/prune?dry_run=true` 로 미리보기, `dry_run=false` 로 실제 삭제 (둘 다 API 토큰 필요).
- **백업**: `hub_data/` 디렉토리 전체를 `tar.gz` → S3/B2/외장 디스크. 메타/JSON/MP4 외에 의존 파일 없음.
- **업로드 캡**: 기본 8GB. 다른 값은 `TRAILBOX_HUB_MAX_UPLOAD_MB`.
- **공유 토큰**: `hub_data/_tokens.json` 한 파일. 수동 편집 가능 (서버 재시작 필요).
