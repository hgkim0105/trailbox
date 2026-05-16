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
#define MyAppVersion   "0.2.2"
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
Source: "{#DistDir}\Trailbox.exe";     DestDir: "{app}"; Flags: ignoreversion; Components: gui
Source: "{#DistDir}\Trailbox-mcp.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: mcp
Source: "{#DistDir}\Trailbox-hub.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: hub

[Dirs]
; Make sure the GUI's output dir + Hub data dir exist.
Name: "{app}\output";   Components: gui
Name: "{app}\hub_data"; Components: hub

[Icons]
Name: "{group}\Trailbox";       Filename: "{app}\Trailbox.exe";       Components: gui
Name: "{group}\Trailbox Hub";   Filename: "{app}\start-hub.bat";      WorkingDir: "{app}"; IconFilename: "{app}\Trailbox-hub.exe"; Components: hub
Name: "{group}\Uninstall Trailbox"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Trailbox"; Filename: "{app}\Trailbox.exe"; Tasks: desktopicon; Components: gui

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

procedure InitializeWizard;
var
  Y: Integer;
begin
  HubConfigPage := CreateCustomPage(
    wpSelectComponents,
    'Hub 연결 설정',
    'Trailbox 클라이언트가 사용할 Hub 주소와 API 토큰을 입력하세요.' + #13#10 +
    'Hub 를 설치하는 경우 «Generate» 로 새 토큰을 만들고 팀원에게 공유. ' +
    '클라이언트만 설치하는 경우 admin 한테 받은 토큰을 붙여넣으세요.');

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
    '• Hub URL: 단일-PC 환경이면 그대로 두세요. 팀 공유 환경이면 Hub 서버 호스트로 변경 ' +
    '(예: http://hub.local:8765).' + #13#10 +
    '• Token: 비어두면 Hub 인증이 꺼집니다 (LAN 전용 권장). 보안이 필요하면 «Generate».' + #13#10 +
    '• 설치 후 Trailbox 의 «허브 설정» 다이얼로그에서 언제든 변경 가능.');
  LabelHubHelp.AutoSize := False;
  LabelHubHelp.Width := HubConfigPage.SurfaceWidth;
  LabelHubHelp.Height := 80;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (PageID = HubConfigPage.ID) and (not NeedsHubConfigPage) then
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
    'REM Edit TRAILBOX_HUB_TOKEN to rotate the token (keep clients in sync).' + #13#10 +
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

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    WriteStartHubBat;
    WriteHubTokenFile;
  end;
end;
