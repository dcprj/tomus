# build_windows.ps1 - Empacotamento Windows do Tomus (PyInstaller + Inno Setup)
# Executa: PyInstaller build, smoke check e compilação do instalador .exe
# Uso: .\packaging\build_windows.ps1

$ErrorActionPreference = "Stop"
$ROOT = (Get-Location).Path
$PY = Join-Path $ROOT ".venv\Scripts\python.exe"
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

# 2) Inno Setup 7
if (-not $ISCC -and (Test-Path "C:\Program Files\Inno Setup 7\ISCC.exe")) {
    $ISCC = "C:\Program Files\Inno Setup 7\ISCC.exe"
    Write-Host "ISCC encontrado (Inno Setup 7): $ISCC"
}

# 3) Inno Setup 6
if (-not $ISCC -and (Test-Path "C:\Program Files\Inno Setup 6\ISCC.exe")) {
    $ISCC = "C:\Program Files\Inno Setup 6\ISCC.exe"
    Write-Host "ISCC encontrado (Inno Setup 6): $ISCC"
}

if (-not $ISCC) {
    Write-Error "ISCC.exe não encontrado (PATH, Inno Setup 7 ou Inno Setup 6)"
    exit 1
}

Write-Host "=== [4/4] Compilação do instalador Inno Setup ===" -ForegroundColor Cyan
& $ISCC $ISS
if ($LASTEXITCODE -ne 0) {
    Write-Error "Inno Setup falhou com código $LASTEXITCODE"
    exit 1
}

Write-Host "=== Build Windows concluído com sucesso ===" -ForegroundColor Green
Write-Host "Executável: $EXE"
Write-Host "Instalador: $(Join-Path $ROOT "dist\Tomus_Setup_v1.3.1_Windows_x64.exe")"
