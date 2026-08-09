# Trailbox Desktop

Trailbox의 데스크톱 클라이언트입니다. Tauri 2 + React + TypeScript UI가 Rust command를 통해 Python 캡처 엔진과 Hub 클라이언트를 호출합니다.

Windows 설치 파일은 `v0.14.0`에서 제공하고, Apple Silicon용 macOS/iOS 캡처는 `v0.15.0` 미리보기로 배포합니다. 플랫폼별 다운로드 경로는 루트 [README](../README.md)를 참고하세요.

## 현재 구조

```text
React UI
  ├─ CaptureScreen       캡처 설정, 녹화, Lookback
  ├─ SessionsScreen      로컬·Hub 세션, 뷰어, Trim
  └─ HubSettingsScreen   로그인, 동기화, 보존 설정
          │ Tauri invoke / event
          ▼
Rust commands
  ├─ 파일·다이얼로그·오버레이 직접 처리
  └─ Python bridge 프로세스 호출
          ▼
Python core
  ├─ 화면·오디오·로그·입력·텔레메트리 캡처
  ├─ viewer.html 생성
  └─ Hub 업로드·다운로드
```

세부 모듈과 IPC 흐름은 [ARCHITECTURE.md](../ARCHITECTURE.md)에 정리되어 있습니다.

## 연결된 기능

- Windows 모니터·창 캡처와 녹화 오버레이
- Android 디바이스 캡처
- macOS/iOS 캡처 미리보기
- 로컬 세션 목록, 뷰어 열기, 삭제
- 세션 Trim과 Lookback 저장
- Hub 로그인, 업로드·다운로드, 동기화와 정리 정책
- 파일·폴더 선택, 창 선택, 전역 단축키
- 다크·라이트 테마

## 개발 환경

- Node.js 20+
- npm 10+
- Rust 1.77+
- Python 3.11+와 루트 `requirements.txt`
- Windows 빌드는 MSVC 툴체인 필요
- macOS 번들은 Apple Silicon 환경에서 생성

```powershell
cd desktop-tauri
npm ci

# React/TypeScript만 검증
npm run build

# Tauri 개발 모드
npm run tauri:dev

# 현재 플랫폼용 Tauri 번들
npm run tauri:build
```

전체 Windows 설치 파일, Python sidecar, MCP, Hub를 함께 빌드하려면 저장소 루트의 `build.py`를 사용합니다. 릴리스 순서는 루트 [CLAUDE.md](../CLAUDE.md)의 버전 동기화 절차를 따릅니다.

## 버전

제품 버전의 기준은 다음 세 파일입니다.

- `../main.py`의 `__version__`
- `../installer/Trailbox-installer.iss`의 `MyAppVersion`
- `src-tauri/tauri.conf.json`의 `version`

`package.json`과 `Cargo.toml`의 `0.0.0`은 제품 릴리스 버전으로 사용하지 않습니다.

## 플랫폼 상태

- **Windows:** `v0.14.0` 설치 파일 제공
- **Android:** Windows 호스트에서 USB 디바이스 캡처
- **macOS/iOS:** `v0.15.0` Apple Silicon 미리보기. ad-hoc 서명, 미공증

macOS/iOS의 실기 검증 내용과 남은 제한은 [mac-ios-HANDOFF.md](../docs/mac-ios-HANDOFF.md)를 참고하세요.
