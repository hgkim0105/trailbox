; Trailbox Windows installer (Inno Setup 6).
;
; Builds Trailbox-Setup.exe that bundles all three binaries from ../dist/.
; The user picks which components to install; if Hub or MCP is included,
; a custom config page collects Hub URL + token (with auto-generate button)
; and the values are written to HKCU\Software\Trailbox\Trailbox\hub so the
; first launch of Trailbox.exe / Trailbox-mcp.exe / Trailbox-hub.exe is
; already configured.
;
; Build:  ISCC.exe Trailbox-installer.iss      (in installer/ dir)
; Output: ../dist/Trailbox-Setup.exe

#define MyAppName      "Trailbox"
#define MyAppVersion   "0.8.0"
#define MyAppPublisher "hgkim0105"
#define MyAppURL       "https://github.com/hgkim0105/trailbox"
#define DistDir        "..\dist"

[Setup]
AppId={{F1D2A8B6-7E4C-4A1F-9B2D-7E2C8B0E9F1A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\Trailbox
; Do NOT append DefaultDirName segment to a user-picked Browse folder.
; Without this, picking "D:\Trailbox" via Browse silently becomes
; "D:\Trailbox\Trailbox" — the nested-folder bug from v0.2.2..v0.2.4.
AppendDefaultDirName=no
DefaultGroupName=Trailbox
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
OutputDir={#DistDir}
OutputBaseFilename=Trailbox-Setup
SetupIconFile=..\assets\trailbox.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Trailbox.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english";  MessagesFile: "compiler:Default.isl"
Name: "korean";   MessagesFile: "compiler:Languages\Korean.isl"

[Types]
Name: "full";    Description: "Full install (GUI + MCP + Hub)"
Name: "client";  Description: "Client only (GUI + MCP) — connect to existing Hub"
Name: "minimal"; Description: "GUI only"
Name: "custom";  Description: "Custom"; Flags: iscustom

[Components]
Name: "gui";  Description: "Trailbox GUI (녹화/뷰어 — 필수)"; Types: full client minimal custom; Flags: fixed
Name: "mcp";  Description: "Trailbox MCP (AI 분석 서버, 약 43 MB)"; Types: full client custom
Name: "hub";  Description: "Trailbox Hub (세션 공유 서버, 약 43 MB)"; Types: full custom

[Files]
; GUI is built with PyInstaller --onedir, so the source is dist/Trailbox/* (the
; launcher .exe + the _internal/ runtime tree). recursesubdirs flattens that tree
; into {app}, putting Trailbox.exe next to _internal/ — same layout as dist.
Source: "{#DistDir}\Trailbox\*";       DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: gui
Source: "{#DistDir}\Trailbox-mcp.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: mcp
Source: "{#DistDir}\Trailbox-hub.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: hub

; Android capture tooling. Files are sourced from tools/android/{platform-tools,scrcpy}/
; relative to the repo root and flattened into {app}\bin\ so core.adb's
; bin/<name> lookup works the same in both frozen+installed and frozen+_MEIPASS
; modes. skipifsourcedoesntexist keeps the installer building even when the
; developer hasn't populated tools/android/ yet (the resulting .exe just can't
; do Android capture).
Source: "..\tools\android\platform-tools\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist; Components: gui
Source: "..\tools\android\scrcpy\*";          DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist; Components: gui

; Third-party attribution for the Android tooling we bundle. Both are
; Apache-2.0. The installer succeeds without it but produced binaries should
; ship the NOTICE alongside.
Source: "..\tools\android\NOTICE.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist; Components: gui

[Dirs]
; Make sure the GUI's output dir + Hub data dir exist.
Name: "{app}\output";   Components: gui
Name: "{app}\hub_data"; Components: hub

[Icons]
Name: "{group}\Trailbox";       Filename: "{app}\Trailbox.exe";       Components: gui
Name: "{group}\Trailbox Hub";   Filename: "{app}\start-hub.bat";      WorkingDir: "{app}"; IconFilename: "{app}\Trailbox-hub.exe"; Components: hub
Name: "{group}\Uninstall Trailbox"; Filename: "{uninstallexe}"
; {autodesktop} = {userdesktop} under lowest privileges, {commondesktop} when elevated.
; Hardcoding {commondesktop} fails silently for non-admin installs (the v0.2.5 desktop-shortcut bug).
Name: "{autodesktop}\Trailbox"; Filename: "{app}\Trailbox.exe"; Tasks: desktopicon; Components: gui

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut for Trailbox"; GroupDescription: "Additional shortcuts:"; Components: gui

[Registry]
; QSettings native format on Windows = HKCU\Software\<Org>\<App>\<group>\<key>
; HubSettingsDialog reads from {hub}; pre-populate it from the installer config.
Root: HKCU; Subkey: "Software\Trailbox\Trailbox\hub"; ValueType: string; ValueName: "url";   ValueData: "{code:GetHubUrl}";   Flags: uninsdeletevalue; Components: gui
Root: HKCU; Subkey: "Software\Trailbox\Trailbox\hub"; ValueType: string; ValueName: "token"; ValueData: "{code:GetHubToken}"; Flags: uninsdeletevalue; Components: gui

[Run]
; Optional final-page checkbox to launch the GUI right after install.
Filename: "{app}\Trailbox.exe"; Description: "{cm:LaunchProgram,Trailbox}"; Flags: nowait postinstall skipifsilent; Components: gui

[UninstallDelete]
; Hub-managed runtime artifacts. Keep output/ and hub_data/ in case the user
; wants their recordings preserved (they're the user's data, not ours).
Type: files;          Name: "{app}\start-hub.bat"
Type: files;          Name: "{app}\hub-token.txt"
Type: files;          Name: "{app}\hub.env"

[Code]
const
  TOKEN_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

var
  HubConfigPage: TWizardPage;
  EditHubUrl:    TNewEdit;
  EditHubToken:  TNewEdit;
  LabelHubHelp:  TNewStaticText;
  BtnGenToken:   TNewButton;
  BtnCopyToken:  TNewButton;
  // Phase 0.8.0 — Hub admin bootstrap page (shown only when 'hub' is selected).
  HubAdminPage:  TWizardPage;
  EditAdminUser: TNewEdit;
  EditAdminPass: TNewEdit;
  EditAdminPass2: TNewEdit;
  LabelAdminHelp: TNewStaticText;

function RandToken: string;
var
  i, n: Integer;
  s: string;
begin
  s := '';
  n := Length(TOKEN_ALPHABET);
  for i := 1 to 32 do
    s := s + TOKEN_ALPHABET[Random(n) + 1];
  Result := s;
end;

procedure OnGenerateTokenClick(Sender: TObject);
begin
  EditHubToken.Text := RandToken;
end;

procedure OnCopyTokenClick(Sender: TObject);
var
  TmpPath: string;
  ResultCode: Integer;
begin
  if Length(EditHubToken.Text) = 0 then Exit;
  // PascalScript has no native clipboard helper, so round-trip via clip.exe.
  // SaveStringToFile + redirect avoids the trailing newline that `echo` adds.
  TmpPath := ExpandConstant('{tmp}\trailbox-token-copy.txt');
  if SaveStringToFile(TmpPath, EditHubToken.Text, False) then
  begin
    Exec(ExpandConstant('{cmd}'), '/c clip < "' + TmpPath + '"', '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
    DeleteFile(TmpPath);
    MsgBox('토큰이 클립보드에 복사되었습니다.', mbInformation, MB_OK);
  end;
end;

function NeedsHubConfigPage: Boolean;
begin
  // Show when Hub or MCP is selected (client setup also needs URL+token).
  Result := WizardIsComponentSelected('hub') or WizardIsComponentSelected('mcp');
end;

function MakeStaticText(Parent: TWinControl; X, Y: Integer; const Caption: string): TNewStaticText;
begin
  Result := TNewStaticText.Create(Parent);
  Result.Parent := Parent;
  Result.Left := X;
  Result.Top := Y;
  Result.Caption := Caption;
end;

function MakeEdit(Parent: TWinControl; X, Y, W: Integer; const Initial: string): TNewEdit;
begin
  Result := TNewEdit.Create(Parent);
  Result.Parent := Parent;
  Result.Left := X;
  Result.Top := Y;
  Result.Width := W;
  Result.Height := 23;
  Result.Text := Initial;
end;

function MakeButton(Parent: TWinControl; X, Y, W, H: Integer; const Caption: string): TNewButton;
begin
  Result := TNewButton.Create(Parent);
  Result.Parent := Parent;
  Result.Left := X;
  Result.Top := Y;
  Result.Width := W;
  Result.Height := H;
  Result.Caption := Caption;
end;

function IsCommonPassword(const Pwd: string): Boolean;
var
  lower: string;
begin
  lower := Lowercase(Pwd);
  Result :=
    (lower = 'password') or (lower = 'password1') or (lower = 'password12') or
    (lower = 'password123') or (lower = 'password1234') or
    (lower = 'passw0rd') or (lower = 'qwerty12345') or
    (lower = 'qwertyuiop') or (lower = '1234567890') or
    (lower = '12345678901') or (lower = '111111111111') or
    (lower = 'trailbox') or (lower = 'trailbox123') or
    (lower = 'administrator') or (lower = 'letmein12345') or
    (lower = 'welcome12345') or (lower = 'iloveyou1234') or
    (lower = 'admin1234567');
end;

function ContainsCaseInsensitive(const Needle, Haystack: string): Boolean;
begin
  Result := Pos(Lowercase(Needle), Lowercase(Haystack)) > 0;
end;

procedure InitializeWizard;
var
  Y: Integer;
begin
  HubConfigPage := CreateCustomPage(
    wpSelectComponents,
    'Hub 연결 설정',
    'Trailbox 클라이언트가 사용할 Hub 주소를 입력하세요.' + #13#10 +
    '계정/토큰은 설치 후 Trailbox 의 «허브 설정» 다이얼로그에서 로그인 또는 ' +
    '회원가입으로 발급받습니다. 기존 운영자 토큰이 있으면 여기에 미리 붙여넣을 수 있습니다.');

  Y := 8;

  MakeStaticText(HubConfigPage.Surface, 0, Y, 'Hub URL');
  EditHubUrl := MakeEdit(HubConfigPage.Surface, 0, Y + 18, HubConfigPage.SurfaceWidth, 'http://127.0.0.1:8765');

  Y := Y + 56;

  MakeStaticText(HubConfigPage.Surface, 0, Y, 'API Token');
  EditHubToken := MakeEdit(HubConfigPage.Surface, 0, Y + 18, HubConfigPage.SurfaceWidth - 220, '');

  BtnGenToken := MakeButton(HubConfigPage.Surface, HubConfigPage.SurfaceWidth - 212, Y + 16, 100, 25, 'Generate');
  BtnGenToken.OnClick := @OnGenerateTokenClick;

  BtnCopyToken := MakeButton(HubConfigPage.Surface, HubConfigPage.SurfaceWidth - 104, Y + 16, 104, 25, '클립보드 복사');
  BtnCopyToken.OnClick := @OnCopyTokenClick;

  Y := Y + 56;

  LabelHubHelp := MakeStaticText(HubConfigPage.Surface, 0, Y,
    '• Hub URL: 로컬 Hub 설치 시 그대로 두세요. 팀 공유 환경이면 Hub 호스트로 변경 ' +
    '(예: http://hub.local:8765).' + #13#10 +
    '• Token: 사용 안 함(권장). 운영자 service-token 호환이 필요하면 «Generate» 후 ' +
    'Hub 와 클라이언트 모두에 동일하게 적용됩니다.' + #13#10 +
    '• 설치 후 Trailbox 의 «허브 설정» 다이얼로그에서 로그인하여 자동 토큰 발급 가능.');
  LabelHubHelp.AutoSize := False;
  LabelHubHelp.Width := HubConfigPage.SurfaceWidth;
  LabelHubHelp.Height := 80;

  // ---- Hub admin bootstrap page (Phase 0.8.0) -----------------------------
  HubAdminPage := CreateCustomPage(
    HubConfigPage.ID,
    'Hub 관리자 계정',
    '이 Hub 의 첫 admin 계정을 생성합니다.' + #13#10 +
    'Hub 첫 실행 시 자동으로 이 계정을 만들고, 사용 후 hub.env 파일은 즉시 삭제됩니다.');

  Y := 8;
  MakeStaticText(HubAdminPage.Surface, 0, Y, 'Admin Username');
  EditAdminUser := MakeEdit(HubAdminPage.Surface, 0, Y + 18, HubAdminPage.SurfaceWidth, 'admin');

  Y := Y + 56;
  MakeStaticText(HubAdminPage.Surface, 0, Y, 'Password (최소 8자)');
  EditAdminPass := MakeEdit(HubAdminPage.Surface, 0, Y + 18, HubAdminPage.SurfaceWidth, '');
  EditAdminPass.PasswordChar := '*';

  Y := Y + 56;
  MakeStaticText(HubAdminPage.Surface, 0, Y, 'Password (확인)');
  EditAdminPass2 := MakeEdit(HubAdminPage.Surface, 0, Y + 18, HubAdminPage.SurfaceWidth, '');
  EditAdminPass2.PasswordChar := '*';

  Y := Y + 56;
  LabelAdminHelp := MakeStaticText(HubAdminPage.Surface, 0, Y,
    '• 8자 이상, username 을 포함하지 않을 것.' + #13#10 +
    '• 너무 흔한 비밀번호(password123, qwerty… 등)는 거부됩니다.' + #13#10 +
    '• 분실 시 hub_data\hub.db 를 삭제하고 다시 설치하거나, ' +
    '관리자 콘솔에서 setup-token 재발급 후 재설정해야 합니다.');
  LabelAdminHelp.AutoSize := False;
  LabelAdminHelp.Width := HubAdminPage.SurfaceWidth;
  LabelAdminHelp.Height := 80;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (PageID = HubConfigPage.ID) and (not NeedsHubConfigPage) then
    Result := True;
  if (PageID = HubAdminPage.ID) and (not WizardIsComponentSelected('hub')) then
    Result := True;
end;

function ValidateAdminInputs: Boolean;
var
  user, pass, pass2: string;
begin
  user := Trim(EditAdminUser.Text);
  pass := EditAdminPass.Text;
  pass2 := EditAdminPass2.Text;

  if (Length(user) < 2) or (Length(user) > 40) then
  begin
    MsgBox('Username 은 2~40자여야 합니다.', mbError, MB_OK);
    Result := False; Exit;
  end;
  if pass <> pass2 then
  begin
    MsgBox('비밀번호가 일치하지 않습니다.', mbError, MB_OK);
    Result := False; Exit;
  end;
  if Length(pass) < 8 then
  begin
    MsgBox('비밀번호는 최소 8자여야 합니다.', mbError, MB_OK);
    Result := False; Exit;
  end;
  if ContainsCaseInsensitive(user, pass) then
  begin
    MsgBox('비밀번호에 username 을 포함할 수 없습니다.', mbError, MB_OK);
    Result := False; Exit;
  end;
  if IsCommonPassword(pass) then
  begin
    MsgBox('너무 흔한 비밀번호입니다. 다른 값을 사용하세요.', mbError, MB_OK);
    Result := False; Exit;
  end;
  Result := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = HubConfigPage.ID then
  begin
    if Trim(EditHubUrl.Text) = '' then
    begin
      MsgBox('Hub URL 을 입력하세요.', mbError, MB_OK);
      Result := False;
    end;
  end;
  if CurPageID = HubAdminPage.ID then
  begin
    Result := ValidateAdminInputs;
  end;
end;

function GetHubUrl(Param: string): string;
begin
  if (HubConfigPage <> nil) and (EditHubUrl <> nil) then
    Result := Trim(EditHubUrl.Text)
  else
    Result := '';
end;

function GetHubToken(Param: string): string;
begin
  if (HubConfigPage <> nil) and (EditHubToken <> nil) then
    Result := Trim(EditHubToken.Text)
  else
    Result := '';
end;

procedure WriteHubTokenFile;
var
  Path, Body: string;
begin
  if not WizardIsComponentSelected('hub') then Exit;
  if Trim(EditHubToken.Text) = '' then Exit;

  Path := ExpandConstant('{app}\hub-token.txt');
  Body :=
    '# Trailbox Hub - share this with your team' + #13#10 +
    '# (or rotate via TRAILBOX_HUB_TOKEN env var)' + #13#10 +
    'URL=' + Trim(EditHubUrl.Text) + #13#10 +
    'TOKEN=' + Trim(EditHubToken.Text) + #13#10;
  SaveStringToFile(Path, Body, False);
end;

procedure WriteStartHubBat;
var
  Path, Body, AppDir: string;
begin
  if not WizardIsComponentSelected('hub') then Exit;

  AppDir := ExpandConstant('{app}');
  Path := AppDir + '\start-hub.bat';
  Body :=
    '@echo off' + #13#10 +
    'REM Trailbox Hub launcher - generated by installer.' + #13#10 +
    'REM Service-token (TRAILBOX_HUB_TOKEN) is optional; admin login is via web UI.' + #13#10 +
    'set TRAILBOX_HUB_TOKEN=' + Trim(EditHubToken.Text) + #13#10 +
    'set TRAILBOX_HUB_DATA=' + AppDir + '\hub_data' + #13#10 +
    'set TRAILBOX_HUB_HOST=127.0.0.1' + #13#10 +
    'set TRAILBOX_HUB_PORT=8765' + #13#10 +
    'set TRAILBOX_HUB_RETENTION_DAYS=30' + #13#10 +
    'title Trailbox Hub' + #13#10 +
    '"' + AppDir + '\Trailbox-hub.exe"' + #13#10 +
    'pause' + #13#10;
  SaveStringToFile(Path, Body, False);
end;

procedure WriteHubEnvFile;
var
  Path, Body, AppDir: string;
  ResultCode: Integer;
begin
  if not WizardIsComponentSelected('hub') then Exit;
  AppDir := ExpandConstant('{app}');
  Path := AppDir + '\hub.env';
  // Plain-text bootstrap file. hub_entry.py reads + deletes this on first
  // launch, so the password doesn't linger on disk. Permissions are
  // tightened via icacls below (best-effort — failure here is a warning).
  Body :=
    '# Trailbox Hub bootstrap (consumed + deleted on first launch).' + #13#10 +
    '# DO NOT redistribute — contains the first-admin password in plaintext.' + #13#10 +
    'TRAILBOX_HUB_ADMIN_USER=' + Trim(EditAdminUser.Text) + #13#10 +
    'TRAILBOX_HUB_ADMIN_PASS=' + EditAdminPass.Text + #13#10;
  if SaveStringToFile(Path, Body, False) then
  begin
    // Restrict to the current user only (and SYSTEM). Best-effort.
    Exec(ExpandConstant('{cmd}'), '/c icacls "' + Path + '" /inheritance:r /grant:r "%USERNAME%":F SYSTEM:F',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    WriteStartHubBat;
    WriteHubTokenFile;
    WriteHubEnvFile;
  end;
end;
