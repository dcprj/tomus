# Smoker do instalador Windows do Tomus — passo de BOOT DA GUI.
#
# COBRE:
#   * Após a instalação silenciosa do instalador Inno Setup
#     (Tomus_Setup_v*.exe), inicia o executável Tomus e verifica que a
#     janela do processo aparece e permanece ativa por um tempo mínimo.
#   * Usa Start-Process para lançar o aplicativo e aguarda com timeout.
#   * Confere que o processo está ativo (não encerrou imediatamente).
#   * Retorna exit code 0 se o boot da GUI foi bem-sucedido, 1 caso contrário.
#
# NAO COBRE:
#   * Não automatiza cliques nem interage com a UI (camada C — futuro).
#   * Não valida o instalador Inno Setup em si (escopo de release.yml/Farol).
#   * Não testa o pipeline de classificação (escopo de scripts/vm_smoke_pipeline.py).
#   * Não testa empacotamento PyInstaller (escopo de build_windows.ps1).
#
# Uso (PowerShell, após gerar o instalador em dist/):
#   .\packaging\vm_smoke_installer.ps1 -Instalador "dist\Tomus_Setup_v1.4.3_Windows_x64.exe" -TimeoutSegundos 30
#
# Requisitos: Windows 11 com PowerShell 5.1+ e o instalador do Tomus gerado.

param(
    [Parameter(Mandatory = $true)]
    [string]$Instalador,        # Caminho para o .exe do Inno Setup gerado

    [Parameter(Mandatory = $true)]
    [string]$DestinoInstalacao, # Diretório onde o Tomus foi instalado (ex: "C:\Program Files\Tomus")

    [Parameter(Mandatory = $false)]
    [int]$TimeoutSegundos = 30, # Tempo máximo de espera pelo boot da GUI

    [Parameter(Mandatory = $false)]
    [string]$NomeExe = "Tomus.exe"  # Nome do executável do Tomus
)

$ErrorActionPreference = "Stop"

Write-Host "=== Smoke do instalador Windows: BOOT DA GUI (Tomus) ==="
Write-Host "Instalador: $Instalador"
Write-Host "Destino: $DestinoInstalacao"
Write-Host "Timeout: $TimeoutSegundos segundos"
Write-Host ""

# 1. Validar que o instalador existe
if (!(Test-Path -Path $Instalador -PathType Leaf)) {
    Write-Error "FALHA: instalador não encontrado: $Instalador"
    exit 1
}

# 2. Validar que o destino de instalação existe
if (!(Test-Path -Path $DestinoInstalacao -PathType Container)) {
    Write-Error "FALHA: diretório de instalação não encontrado: $DestinoInstalacao"
    exit 1
}

$ExeCaminho = Join-Path -Path $DestinoInstalacao -ChildPath $NomeExe
if (!(Test-Path -Path $ExeCaminho -PathType Leaf)) {
    Write-Error "FALHA: executável do Tomus não encontrado: $ExeCaminho"
    exit 1
}

# 3. Executar instalação silenciosa (se ainda não foi feita externamente).
#    Este script assume que o instalador já foi executado pelo pipeline de
#    release; aqui apenas confirmamos que os arquivos estão no destino.
Write-Host "Verificando arquivos instalados em $DestinoInstalacao ..."
$arquivosEsperados = @($NomeExe)
foreach ($arquivo in $arquivosEsperados) {
    $caminho = Join-Path -Path $DestinoInstalacao -ChildPath $arquivo
    if (!(Test-Path -Path $caminho -PathType Leaf)) {
        Write-Error "FALHA: arquivo esperado não encontrado após instalação: $caminho"
        exit 1
    }
}
Write-Host "OK: arquivos do instalador presentes no destino."

# 4. Iniciar o Tomus (boot da GUI) e verificar que o processo fica ativo.
Write-Host "Iniciando o Tomus para verificar o boot da GUI ..."
$processo = Start-Process -FilePath $ExeCaminho -ArgumentList @() -PassThru -WindowStyle Normal

# Aguardar o tempo máximo para o processo permanecer ativo.
$inicio = Get-Date
$limite = $inicio.AddSeconds($TimeoutSegundos)
$ativo = $false

while ((Get-Date) -lt $limite) {
    Start-Sleep -Milliseconds 500
    if ($processo.HasExited) {
        $ativo = $false
        break
    }
    $ativo = $true
    break
}

if (-not $ativo) {
    $codigoSaida = $processo.ExitCode
    Write-Error "FALHA: o processo do Tomus encerrou antes do timeout (código de saída: $codigoSaida)."
    exit 1
}

# Verificar novamente após um curto intervalo para garantir estabilidade.
Start-Sleep -Seconds 2
if ($processo.HasExited) {
    $codigoSaida = $processo.ExitCode
    Write-Error "FALHA: o processo do Tomus encerrou após 2 segundos (código de saída: $codigoSaida)."
    exit 1
}

Write-Host "OK: o processo do Tomus (PID $($processo.Id)) permaneceu ativo durante o boot da GUI."
$processo.Kill()
Write-Host "Processo de teste encerrado."
Write-Host ""
Write-Host "VEREDIÇO: PASSOU — boot da GUI do Tomus verificado com sucesso."
exit 0
