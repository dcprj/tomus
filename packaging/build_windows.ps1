# build_windows.ps1 - Empacotamento Windows do Tomus (PyInstaller + Inno Setup)
# Executa: PyInstaller build, smoke check e compilação do instalador .exe
# Uso: .\packaging\build_windows.ps1

$ErrorActionPreference = "Stop"
$ROOT = (Get-Location).Path
$PY = Join-Path $ROOT ".venv\Scripts\python.exe"
$VERSION = "1.4.3"
try {
    $VERSION = & $PY -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
} catch {
    Write-Host "Não foi possível ler a versão de pyproject.toml; usando fallback 1.4.3"
}
$SPEC = Join-Path $ROOT "packaging\pyinstaller.spec"
$ISS = Join-Path $ROOT "packaging\windows_installer.iss"
$DIST_TOMLUS = Join-Path $ROOT "dist\Tomus"
$EXE = Join-Path $DIST_TOMLUS "Tomus.exe"

Write-Host "=== [1/4] PyInstaller build (--clean --noconfirm) ===" -ForegroundColor Cyan
& $PY -m PyInstaller --clean --noconfirm $SPEC
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller falhou com código $LASTEXITCODE"
    exit 1
}

if (-not (Test-Path $EXE)) {
    Write-Error "Executável não encontrado: $EXE"
    exit 1
}

Write-Host "=== [2/4] Smoke check Windows ===" -ForegroundColor Cyan
& $PY $ROOT\packaging\smoke_check_windows.py
if ($LASTEXITCODE -ne 0) {
    Write-Error "Smoke check falhou com código $LASTEXITCODE"
    exit 1
}

Write-Host "=== [3/4] Detecção do ISCC.exe (Inno Setup) ===" -ForegroundColor Cyan
$ISCC = $null

# 1) No PATH
$cmd = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($cmd) {
    $ISCC = $cmd.Source
    Write-Host "ISCC encontrado no PATH: $ISCC"
}

# 2) Inno Setup 7 (x64)
if (-not $ISCC -and (Test-Path "C:\Program Files\Inno Setup 7\ISCC.exe")) {
    $ISCC = "C:\Program Files\Inno Setup 7\ISCC.exe"
    Write-Host "ISCC encontrado (Inno Setup 7 x64): $ISCC"
}
# 3) Inno Setup 7 (x86)
if (-not $ISCC -and (Test-Path "C:\Program Files (x86)\Inno Setup 7\ISCC.exe")) {
    $ISCC = "C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
    Write-Host "ISCC encontrado (Inno Setup 7 x86): $ISCC"
}
# 4) Inno Setup 6 (x64)
if (-not $ISCC -and (Test-Path "C:\Program Files\Inno Setup 6\ISCC.exe")) {
    $ISCC = "C:\Program Files\Inno Setup 6\ISCC.exe"
    Write-Host "ISCC encontrado (Inno Setup 6 x64): $ISCC"
}
# 5) Inno Setup 6 (x86)
if (-not $ISCC -and (Test-Path "C:\Program Files (x86)\Inno Setup 6\ISCC.exe")) {
    $ISCC = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    Write-Host "ISCC encontrado (Inno Setup 6 x86): $ISCC"
}

if (-not $ISCC) {
    Write-Error "ISCC.exe não encontrado (PATH, Inno Setup 7 ou Inno Setup 6)"
    exit 1
}

Write-Host "=== [4/4] Compilação do instalador Inno Setup ===" -ForegroundColor Cyan
$INSTALLER = Join-Path $ROOT "dist\Tomus_Setup_v${VERSION}_Windows_x64.exe"
& $ISCC $ISS /DMyAppVersion=$VERSION
if ($LASTEXITCODE -ne 0) {
    Write-Error "Inno Setup falhou com código $LASTEXITCODE"
    exit 1
}

if (-not (Test-Path $INSTALLER)) {
    Write-Error "Instalador não encontrado: $INSTALLER"
    exit 1
}

# C-02/C-03: Definir ACL restritiva (apenas o usuário atual) nos arquivos de
# configuração e cache no diretório de instalação, para proteger chaves de API
# armazenadas em texto plano contra acesso por outros usuários do Windows.
Write-Host "=== [5/5] Aplicando ACL restritiva nos arquivos de configuração ===" -ForegroundColor Cyan
$configToml = Join-Path $DIST_TOMLUS "config.toml"
$stateDb = Join-Path $DIST_TOMLUS "state.db"
$currentUser = [System.Security.Principal.WindowsIdentity]::Current.Name

foreach ($file in @($configToml, $stateDb)) {
    if (Test-Path $file) {
        try {
            # Remover herança de ACL e conceder controle total apenas ao usuário atual
            icacls $file /inheritance:r /grant "${currentUser}:(F)" | Out-Null
            Write-Host "ACL aplicada em: $file" -ForegroundColor Green
        } catch {
            Write-Warning "Não foi possível aplicar ACL em ${file}: $_"
        }
    }
}

Write-Host "=== Build Windows concluído com sucesso ===" -ForegroundColor Green
Write-Host "Executável: $EXE"
Write-Host "Instalador: $INSTALLER"
