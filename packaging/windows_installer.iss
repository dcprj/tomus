; Script de Instalação Inno Setup para o Tomus (Windows)
; Gera um instalador profissional .exe: Tomus_Setup_v1.1.0_Windows_x64.exe

#define MyAppName "Tomus"
#ifndef MyAppVersion
#define MyAppVersion "1.4.1"
#endif
#define MyAppPublisher "Tomus Open Source Community"
#define MyAppURL "https://github.com/dcprj/tomus"
#define MyAppExeName "Tomus.exe"

[Setup]
AppId={{D37E6F10-B14C-409D-A3D9-974F8175E7B1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=Tomus_Setup_v{#MyAppVersion}_Windows_x64
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
SetupIconFile=icons\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Copiar todo o conteúdo gerado pelo PyInstaller em dist/Tomus
Source: "..\dist\Tomus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Definir ACL restritiva (apenas o usuário atual) nos arquivos de configuração
; e cache do Tomus (C-02/C-03 - proteção de chaves de API em texto plano no Windows).
Filename: icacls; Parameters: "{app}\config.toml /inheritance:r /grant {username}:(F)"; WorkingDir: "{app}"; StatusMsg: "Configurando permissões de config.toml..."; Flags: runhidden skipifsilent
Filename: icacls; Parameters: "{app}\state.db /inheritance:r /grant {username}:(F)"; WorkingDir: "{app}"; StatusMsg: "Configurando permissões de state.db..."; Flags: runhidden skipifsilent
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// C-02/C-03: ACL restritiva (equivalente a chmod 0600 POSIX) para config.toml e state.db no Windows
// Aplica permissões de proprietário único (herança removida, acesso total apenas ao dono)
// nos arquivos de configuração e cache SQLite criados pelo aplicativo.

function ApplyRestrictiveACL(const FilePath: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if not FileExists(FilePath) then
    Exit;
  // Remove herança de ACL e concede acesso total apenas ao proprietário (S-1-3-0 = Everyone, mas restringido ao owner)
  // icacls /inheritance:r remove herança; /grant *S-1-3-0:(F) concede Full Control apenas ao owner atual
  if Exec('cmd.exe', '/c icacls "' + FilePath + '" /inheritance:r /grant *S-1-3-0:(F)', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := ResultCode = 0;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigDir, CacheDir, ConfigFile, StateDbFile: String;
begin
  if CurStep = ssPostInstall then
  begin
    // Caminhos relativos ao diretório de instalação ({app})
    ConfigDir := ExpandConstant('{app}') + '\.config\tomus';
    CacheDir := ExpandConstant('{app}') + '\.cache\tomus';
    ConfigFile := ConfigDir + '\config.toml';
    StateDbFile := CacheDir + '\state.db';

    // Criar pastas se não existirem (o aplicativo também as cria em runtime, mas garantir aqui)
    if not DirExists(ConfigDir) then
      CreateDir(ConfigDir);
    if not DirExists(CacheDir) then
      CreateDir(CacheDir);

    // Aplicar ACL restritiva nas pastas
    if DirExists(ConfigDir) then
      ApplyRestrictiveACL(ConfigDir);
    if DirExists(CacheDir) then
      ApplyRestrictiveACL(CacheDir);

    // Aplicar ACL restritiva nos arquivos se existirem (criados pelo app em runtime)
    if FileExists(ConfigFile) then
      ApplyRestrictiveACL(ConfigFile);
    if FileExists(StateDbFile) then
      ApplyRestrictiveACL(StateDbFile);
  end;
end;
