# Hub Authentication & Accounts — 구현 계획

이 문서는 Trailbox Hub의 **단일 공유 토큰 → 다중 사용자 + admin 승인 기반 계정 체계** 전환을 위한 확정된 구현 계획이다. ROADMAP의 후속 작업이며, 실제 구현 시 이 문서를 따라 진행한다.

---

## 결정사항 (확정)

| 항목 | 결정 |
|---|---|
| DB | **SQLite** (`hub_data/hub.db`), stdlib `sqlite3`로 충분, SQLAlchemy/Alembic 불사용 |
| 비밀번호 해시 | **argon2-cffi** (argon2id) |
| 세션 (웹) | **쿠키** (HttpOnly, SameSite=Lax, `itsdangerous` 서명) |
| 세션 (클라이언트/MCP) | 사용자별 **API 토큰** — 헤더 `X-Trailbox-Token` 그대로 (의미만 변경) |
| 회원가입 | 누구나 신청 가능, **admin 승인 필수**(기본). 자동 승인 옵션 토글 제공 |
| 자동 승인 토글 위치 | DB `hub_settings` 테이블 + admin UI (런타임 변경 가능). env `TRAILBOX_HUB_AUTO_APPROVE`는 초기값 시드용 |
| 소유권 | 세션마다 `owner_id`. 일반 user는 본인 세션만 list/get, admin은 전체 |
| 공개 결정 | **share 토큰 발급 = 공개 의사 표시.** `/v/{token}/*`는 익명 접근 유지 |
| 익명 Hub 접근 | 없음. 모든 `/api/*` 는 로그인 필수. 미인증 클라이언트는 로컬 저장만 |
| 레거시 `TRAILBOX_HUB_TOKEN` | **admin service-token** 으로 강등 (선택적, 신규 설치 권장X) |
| 부트스트랩 admin | Docker/CLI: env 변수 또는 1회용 setup-token. Windows: 인스톨러 입력 페이지 |
| 웹 UI | **서버 렌더 Jinja2** (SPA 안 함) — 단일 운영자/소규모 트래픽 가정 |

배경: 현재 `hub_server/auth.py`는 단일 공유 비밀(`X-Trailbox-Token`)만 검증한다. 여러 QA가 한 Hub를 공유하기 시작하면 (1) 누가 어떤 세션을 올렸는지 추적 불가, (2) 토큰 유출 시 전체 무효화 외 대응 불가, (3) 공유 토큰을 가진 누구나 전체 세션을 삭제 가능하다는 문제가 있다. 본 계획은 이 셋을 해결하면서, share-link 익명 뷰어(외부 공유 회의록 등)는 그대로 유지한다.

---

## 설계 원칙

- **CLAUDE.md의 단일 출력 규약 유지**: 세션 디렉터리 레이아웃·JSONL 스키마는 손대지 않는다. `session_owners` 테이블이 디스크 외부에서 소유권을 매핑한다.
- **인증 일원화**: FastAPI 의존성 `require_user` / `require_admin` 둘만 라우터에서 쓴다. 쿠키와 헤더 토큰 둘 다 같은 의존성 안에서 해석.
- **마이그레이션 in-place**: `PRAGMA user_version`을 키로 `hub_server/db.py:migrate()`가 점진 적용. 기존 세션 디렉터리는 첫 부팅에 admin 소유로 백필.
- **하위 호환 1버전**: 0.5.0에서 env `TRAILBOX_HUB_TOKEN`이 있으면 admin service-token으로 동작 → 0.6.0에서 client UX 전환 → 0.7.0에서 웹 UI → 0.8.0에서 인스톨러 페이지. 매 PR이 단독으로 빌드/배포 가능.

---

## Phase 0.5.0 — DB, 사용자 모델, 인증 의존성

행동 변화 없음 (= 외부에서 보기에 0.4.x 그대로). 내부 자료구조와 의존성만 교체.

**새 파일**

- `hub_server/db.py`
  - `connect(cfg)` — `sqlite3.connect(data_root/"hub.db", check_same_thread=False)`, `PRAGMA foreign_keys=ON`, `journal_mode=WAL`
  - `migrate(conn)` — `user_version` 기반 마이그레이션 디스패처. v1: 아래 5개 테이블 생성 + 시드(`hub_settings`).
  - `get_conn()` — FastAPI `Depends` 호환 컨텍스트 매니저
- `hub_server/users.py` — `UserStore`
  - `create(username, password, email, role, status) -> User`
  - `verify_password(username, password) -> User | None`
  - `get_by_id`, `get_by_username`, `list_pending`, `list_all`
  - `approve(user_id, by_admin_id)`, `disable(user_id)`, `set_role(user_id, role)`
  - argon2-cffi `PasswordHasher` 모듈 싱글톤
- `hub_server/tokens.py` — `ApiTokenStore`
  - `issue(user_id, label) -> (plain_token, row)` — 평문은 1회만 노출, DB엔 `sha256(token)` 저장
  - `verify(plain) -> User | None` — 조회 시 `last_used` 갱신
  - `list_for_user`, `revoke`, `revoke_all_for_user`
- `hub_server/web_sessions.py` — 쿠키 세션 store (sid + expires_at, 30일 슬라이딩)
- `hub_server/settings_store.py` — `hub_settings` 테이블 read/write (`auto_approve_registration` 등)

**스키마 (v1)**

```sql
CREATE TABLE users (
  id            INTEGER PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  email         TEXT,
  pw_hash       TEXT NOT NULL,
  role          TEXT NOT NULL CHECK(role IN ('admin','user')),
  status        TEXT NOT NULL CHECK(status IN ('pending','active','disabled')),
  created_at    TEXT NOT NULL,
  approved_at   TEXT,
  approved_by   INTEGER REFERENCES users(id)
);

CREATE TABLE api_tokens (
  id          INTEGER PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash  TEXT NOT NULL UNIQUE,
  label       TEXT,
  created_at  TEXT NOT NULL,
  last_used   TEXT,
  revoked_at  TEXT
);

CREATE TABLE web_sessions (
  sid         TEXT PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL
);

CREATE TABLE session_owners (
  session_id  TEXT PRIMARY KEY,
  owner_id    INTEGER NOT NULL REFERENCES users(id),
  uploaded_at TEXT NOT NULL
);

CREATE TABLE hub_settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE audit_log (
  id         INTEGER PRIMARY KEY,
  ts         TEXT NOT NULL,
  actor_id   INTEGER,
  action     TEXT NOT NULL,
  target     TEXT,
  detail     TEXT
);

-- seed
INSERT INTO hub_settings(key,value) VALUES('auto_approve_registration','0');
```

**수정**

- `hub_server/auth.py` — `require_token` 은 한 줄 shim으로 유지(`require_user_or_service` 위임). 신규 의존성 `require_user` / `require_admin` 추가. 쿠키(`sid` 헤더 자동 파싱) 우선, 없으면 `X-Trailbox-Token` → `api_tokens` 조회 → User 반환. `status != 'active'` 면 401.
- `hub_server/config.py` — `TRAILBOX_HUB_ADMIN_USER`, `TRAILBOX_HUB_ADMIN_PASS`, `TRAILBOX_HUB_AUTO_APPROVE`, `TRAILBOX_HUB_SECRET_KEY`(쿠키 서명용) 추가. 비어있으면 첫 부팅 시 생성하여 `data_root/.secret_key` 에 저장.
- `hub_server/app.py` — `create_app` 진입에서 `db.migrate()` + 부트스트랩(아래) 실행. 기존 `Depends(auth)` 는 0.5.0에서 그대로 두되, **내부적으로 service-token (= env `TRAILBOX_HUB_TOKEN`) 또는 신규 User 토큰 둘 다 통과** 하도록 `require_token` shim 확장.
- `hub_server/storage.py` — `ingest_zip(session_id, zip_path, owner_id)` 시그니처에 `owner_id` 추가, `session_owners` 에 매핑. 기존 호출부 업데이트.
- `hub_server/retention.py` — 세션 삭제 시 `session_owners` row 도 정리.
- `requirements-hub.txt` — `argon2-cffi`, `itsdangerous`, `jinja2` 추가.

**부트스트랩 로직** (`hub_server/app.py:create_app` 또는 별도 `bootstrap.py`)

```
on startup:
  migrate()
  if users.count(role='admin') == 0:
    if env.ADMIN_USER and env.ADMIN_PASS:
      users.create(env.ADMIN_USER, env.ADMIN_PASS, role='admin', status='active')
      log "admin bootstrapped from env"
    else:
      setup_token = secrets.token_urlsafe(32)
      write data_root/.setup_token
      stderr "First-run setup token: {setup_token} — visit /setup"
  if existing session dirs without session_owners row:
    backfill owner_id = first admin
  seed hub_settings.auto_approve_registration from env.TRAILBOX_HUB_AUTO_APPROVE if absent
```

**검증** (0.5.0 PR 머지 조건)

- `python -m hub_server` 첫 부팅 → `hub.db` 생성, admin 1명 존재.
- 기존 토큰으로 모든 API 호출 동작 (service-token 호환 경로).
- 새 사용자 직접 SQL 삽입 후 그 user의 토큰으로 `/api/sessions` → 본인 세션만 반환.
- 두 번째 부팅에서 마이그레이션 멱등.

---

## Phase 0.6.0 — 인증 라우트 + 클라이언트 UX

신규 라우트와 Trailbox 클라이언트의 로그인/회원가입 다이얼로그.

**새 파일**

- `hub_server/routes/__init__.py`
- `hub_server/routes/api_auth.py`
  - `POST /api/auth/register` — `{username, password, email?}` → `hub_settings.auto_approve_registration` 보고 `status='active'` 또는 `'pending'` 결정. 응답: `{user_id, status}`. audit_log 기록.
  - `POST /api/auth/login` — `{username, password}` → 쿠키 set + `{user, role, status}`. 실패 5회/15분 lockout (메모리 카운터 + 마지막 실패 시각, 단순 dict).
  - `POST /api/auth/logout` — sid 무효화.
  - `GET  /api/auth/me` — 미인증 401, 인증 시 `{user, role, status}`. 클라이언트가 승인 폴링용.
  - `POST /api/auth/tokens` — `{label}` → 평문 토큰 1회 노출.
  - `GET  /api/auth/tokens` — 본인 토큰 메타 목록 (해시 미노출).
  - `DELETE /api/auth/tokens/{id}` — 본인 토큰 revoke.
- `hub_server/routes/api_admin.py` (admin 전용)
  - `GET  /api/admin/users`
  - `POST /api/admin/users/{id}/approve`
  - `POST /api/admin/users/{id}/disable`
  - `POST /api/admin/users/{id}/role` — `{role}`
  - `DELETE /api/admin/users/{id}/tokens` — 강제 revoke-all
  - `GET  /api/admin/settings` / `PATCH /api/admin/settings` — `auto_approve_registration` 토글 등
  - `POST /api/setup` — 1회용 setup-token 검증 후 첫 admin 생성. admin이 1명 이상 존재하면 410.

**수정**

- `hub_server/app.py` — 라우터 마운트. 기존 `/api/sessions/*` 핸들러는 `routes/api_sessions.py`로 이전하면서 의존성을 `require_user`로 교체, owner 가드 추가.
  - list: `if user.role == 'admin': all else: where owner_id = user.id`
  - get/delete/share/zip: `owner_id == user.id or user.role == 'admin'` 아니면 404 (403보다 정보 노출 적음)
  - upload: `ingest_zip(..., owner_id=user.id)`
- `core/hub_config.py` — `HubSettings` 에 `username` 필드 추가 (UX용, 토큰만 있어도 동작). `configured` 정의 동일.
- `core/hub_client.py` — 변경 거의 없음. `register(username, password, email)`, `login(username, password)`(쿠키는 안 쓰고 토큰 발급 흐름만 노출), `me()`, `issue_token(label)` 헬퍼 추가.
- `ui/hub_dialogs.py`
  - 탭/모드: **로그인 / 회원가입 / 고급(수동 토큰)**
  - 신규 사용자 흐름: URL 입력 → 회원가입 → 응답이 `pending`이면 다이얼로그가 "관리자 승인 대기" 상태 전환 + `GET /api/auth/me` 30초 폴링. 승인되면 자동으로 `POST /api/auth/tokens` (label=`trailbox-{computer_name}`) → 발급 평문 토큰을 `HubSettings.token`에 저장 + 다이얼로그 닫힘.
  - 자동 승인 환경에서는 회원가입 → 즉시 로그인 → 토큰 발급까지 한 흐름.
  - 기존 "수동 토큰 붙여넣기" 는 고급 탭으로 이동 (운영자 service-token 사용자 호환).
- `mcp_server/backends/hub.py` — 변경 없음 (헤더 의미만 바뀜).

**검증**

- 신규 가입 → admin이 `/api/admin/users`로 승인 → 클라이언트가 자동으로 토큰 받고 업로드 성공.
- 자동 승인 ON → 가입 직후 토큰 발급, 업로드 성공.
- admin이 다른 user의 세션을 list/get 가능. 일반 user는 본인 외 세션에 대해 404.
- service-token으로 호출 시 admin 권한으로 동작 (운영자 호환).

---

## Phase 0.7.0 — 웹 관리 페이지 (Jinja2)

**새 파일**

- `hub_server/templates/base.html` — 공통 레이아웃, 로그인 상태 헤더
- `hub_server/templates/login.html`
- `hub_server/templates/register.html`
- `hub_server/templates/setup.html` — 1회용 setup-token으로 첫 admin 생성
- `hub_server/templates/sessions/list.html` — 본인(또는 전체) 세션 테이블, 다운로드/삭제/공유 토큰 발급/revoke
- `hub_server/templates/sessions/detail.html` — 메타 + 메트릭 요약 + viewer 진입 링크 (`/v/{token}` 발급 후)
- `hub_server/templates/admin/users.html` — pending 승인, role 변경, disable, 토큰 강제 revoke
- `hub_server/templates/admin/settings.html` — `auto_approve_registration` 등 토글
- `hub_server/templates/admin/audit.html` — audit_log 페이징 (선택, 없어도 0.7.0 머지 가능)
- `hub_server/static/app.css` — 외부 CDN 없음, vanilla
- `hub_server/static/app.js` — 테이블 정렬·삭제 확인·토스트만, 빌드 단계 없음
- `hub_server/routes/web.py` — 위 템플릿 라우트. 쿠키 인증, 미로그인 시 `/login?next=...` 리다이렉트.

**수정**

- `hub_server/app.py` — `StaticFiles` 마운트, Jinja2 `TemplateResponse` 헬퍼.
- `hub_server/config.py` — `TRAILBOX_HUB_PUBLIC_URL` 추가 (선택, 가입 안내 메일 등 추후 확장 대비).
- `Trailbox-hub.spec` — `templates/`, `static/` 디렉터리를 PyInstaller `datas`에 포함.
- `Dockerfile.hub` — 동일하게 디렉터리 COPY.

**검증**

- `/login`에서 로그인 → `/sessions` 본인 세션 목록 표시.
- admin 로그인 → `/admin/users`에서 pending 승인 → 해당 user 즉시 토큰 발급 가능.
- admin이 `/admin/settings`에서 자동 승인 ON/OFF 즉시 반영 (재시작 불필요).
- 세션 detail에서 share 토큰 발급 후 익명 브라우저로 `/v/{token}` 열기 성공.

---

## Phase 0.8.0 — 인스톨러/Docker admin 부트스트랩

**수정**

- `installer/Trailbox-installer.iss`
  - `[Code]` 섹션에 Admin Username/Password 입력 페이지(`CreateInputQueryPage`).
  - 결과를 `{app}\hub.env` 에 `TRAILBOX_HUB_ADMIN_USER=...` / `TRAILBOX_HUB_ADMIN_PASS=...` 로 기록 (서비스 등록 시 env로 전달).
  - 비밀번호 정책(12자+, 흔한 비밀번호 거부)을 인스톨러 단계에서도 1회 검증.
- `Trailbox-hub.exe` 실행 진입(`hub_entry.py`)에서 `hub.env` 가 있으면 로드 후 한 번만 사용하고 해당 파일 권한을 ACL로 제한 (또는 admin 생성 직후 삭제).
- `Dockerfile.hub` / `docker-compose.yml`
  - env 변수 문서화: `TRAILBOX_HUB_ADMIN_USER`, `TRAILBOX_HUB_ADMIN_PASS`, `TRAILBOX_HUB_AUTO_APPROVE`, `TRAILBOX_HUB_SECRET_KEY`.
  - 미지정 시 stderr의 setup-token 흐름이 fallback.
- `DEPLOYMENT.md` — Docker/Compose/Windows 각 경로별 첫 admin 생성 방법 정리.
- `README.md` — Hub 섹션 갱신.

**검증**

- Windows 클린 설치 → 인스톨러 입력값으로 첫 부팅 admin 로그인 성공.
- `docker compose up` 클린 부팅 → env 값으로 admin 생성, 미지정 시 setup-token 콘솔 출력.
- 두 번째 부팅에서 admin 중복 생성 안 함 (멱등).

---

## 보안 메모

- argon2id 파라미터는 argon2-cffi 기본값 사용 (time_cost=2, memory_cost=64MB, parallelism=1). 운영 환경에 따라 `core/hub_config` 가 아닌 `hub_settings`에 두지 않는다 (런타임 변경 시 기존 해시 검증 깨지지 않게 — argon2는 해시 문자열에 파라미터 포함되어 호환됨).
- API 토큰 평문: 32B `secrets.token_urlsafe(32)` → 43자. 기존 `_TOKEN_RE = ^[A-Za-z0-9_\-]{16,64}$` 와 호환.
- 쿠키 `sid`: 32B URL-safe, `itsdangerous.URLSafeSerializer` 로 secret_key 서명. HttpOnly, Secure(프로덕션 HTTPS 가정), SameSite=Lax.
- 비밀번호 정책: 최소 12자, 사용자명 포함 금지, 매우 짧은 deny-list(공통 비밀번호 50개 정도) — `hub_server/users.py:validate_password`.
- 로그인 lockout: in-process dict `{username: (fail_count, last_ts)}`. 5회/15분. 분산 환경 미고려 (Hub는 단일 인스턴스 가정).
- audit_log에 기록할 액션: `register`, `login`, `login_failed`, `logout`, `approve`, `disable`, `role_change`, `token_issued`, `token_revoked`, `auto_approved`, `settings_changed`, `session_delete`, `share_created`, `share_revoked`.

## 알려진 제약

- 비밀번호 리셋(이메일 링크)은 본 계획에 없음 — admin이 사용자 비밀번호 강제 재설정(`/api/admin/users/{id}/password`) 만 0.6.0에 포함 검토 가능. (현재는 운영자가 DB 직접 갱신)
- SSO/OIDC 미포함. 사내망 단일 운영자 가정.
- 분산 Hub 미지원. SQLite는 단일 호스트 + WAL로 충분.
- 기존 share 토큰(`_tokens.json`)은 그대로 호환. 0.5.0에서 owner 매핑 백필 시 모든 share 토큰의 소유자 = admin.
