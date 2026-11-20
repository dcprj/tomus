#!/usr/bin/env bash
# ==============================================================================
# Script de Build do Tomus para macOS (.app e .dmg)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_NAME="Tomus"
DIST_DIR="${PROJECT_ROOT}/dist"
BUILD_DIR="${PROJECT_ROOT}/build"

# Ler a versão do pyproject.toml
if [ -f "${PROJECT_ROOT}/.venv/bin/python3" ]; then
    VERSION=$("${PROJECT_ROOT}/.venv/bin/python3" -c "import tomllib; print(tomllib.load(open('${PROJECT_ROOT}/pyproject.toml', 'rb'))['project']['version'])" 2>/dev/null || echo "1.3.2")
elif command -v python3 &> /dev/null; then
    VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('${PROJECT_ROOT}/pyproject.toml', 'rb'))['project']['version'])" 2>/dev/null || python3 -c "import tomli; print(tomli.load(open('${PROJECT_ROOT}/pyproject.toml', 'rb'))['project']['version'])" 2>/dev/null || echo "1.3.2")
else
    VERSION="1.3.2"
fi

DMG_NAME="${APP_NAME}-${VERSION}-macOS.dmg"

echo "=========================================================="
echo " Início do Build macOS para ${APP_NAME} v${VERSION}"
echo "=========================================================="

cd "${PROJECT_ROOT}"

# 1. Verificar PyInstaller no ambiente ativo
if ! command -v pyinstaller &> /dev/null; then
    if [ -f ".venv/bin/pyinstaller" ]; then
        PYINSTALLER=".venv/bin/pyinstaller"
    else
        echo "❌ Erro: pyinstaller não encontrado. Instale com: pip install pyinstaller"
        exit 1
    fi
else
    PYINSTALLER="pyinstaller"
fi

# 2. Limpar builds anteriores e configurar cache local
echo "🧹 Limpando pastas dist/ e build/..."
rm -rf "${DIST_DIR}/${APP_NAME}.app" "${DIST_DIR}/${DMG_NAME}" "${BUILD_DIR}"
export PYINSTALLER_CONFIG_DIR="${BUILD_DIR}/pyinstaller_cache"
mkdir -p "${PYINSTALLER_CONFIG_DIR}"

# 3. Executar PyInstaller
echo "⚙️ Compilando bundle macOS (.app) via PyInstaller..."
"${PYINSTALLER}" --clean -y "${SCRIPT_DIR}/pyinstaller.spec"

APP_PATH="${DIST_DIR}/${APP_NAME}.app"
if [ ! -d "${APP_PATH}" ]; then
    echo "❌ Erro: O bundle ${APP_PATH} não foi gerado com sucesso."
    exit 1
fi

echo "✅ Bundle ${APP_PATH} gerado com sucesso!"

# 5. Corrigir caminhos do QtWebEngineProcess (evitar SIGABRT no WebContentsAdapter)
echo "🔧 Configurando caminhos do QtWebEngineProcess..."
FRAMEWORK_DIR="${APP_PATH}/Contents/Frameworks/PySide6/Qt/lib/QtWebEngineCore.framework"
HELPERS_SRC="${FRAMEWORK_DIR}/Versions/A/Helpers/QtWebEngineProcess.app"
HELPERS_DST="${FRAMEWORK_DIR}/Helpers"

# Migrar Versions/Resources para Versions/A se necessário (PyInstaller coloca em Versions/Resources)
if [ -d "${FRAMEWORK_DIR}/Versions/Resources/Helpers" ] && [ ! -d "${FRAMEWORK_DIR}/Versions/A/Helpers" ]; then
    mv "${FRAMEWORK_DIR}/Versions/Resources/Helpers" "${FRAMEWORK_DIR}/Versions/A/Helpers"
fi
if [ -d "${FRAMEWORK_DIR}/Versions/Resources/Resources" ]; then
    mkdir -p "${FRAMEWORK_DIR}/Versions/A/Resources"
    cp -Rn "${FRAMEWORK_DIR}/Versions/Resources/Resources/." "${FRAMEWORK_DIR}/Versions/A/Resources/" || true
fi
rm -rf "${FRAMEWORK_DIR}/Versions/Resources"

# Recriar Helpers com symlink relativo para Versions/A/Helpers
if [ -d "${HELPERS_SRC}" ]; then
    if [ -L "${HELPERS_DST}" ]; then
        rm "${HELPERS_DST}"
    elif [ -d "${HELPERS_DST}" ]; then
        rm -rf "${HELPERS_DST}"
    fi
    ln -s "Versions/A/Helpers" "${HELPERS_DST}"
    echo "✓ Symlink criado (relativo): ${HELPERS_DST} -> Versions/A/Helpers"
fi

# Recriar QtWebEngineProcess com symlink relativo
MACOS_DST="${APP_PATH}/Contents/MacOS/QtWebEngineProcess"
if [ -f "${HELPERS_SRC}/Contents/MacOS/QtWebEngineProcess" ]; then
    if [ -L "${MACOS_DST}" ]; then
        rm "${MACOS_DST}"
    elif [ -f "${MACOS_DST}" ]; then
        rm "${MACOS_DST}"
    fi
    ln -s "../Frameworks/PySide6/Qt/lib/QtWebEngineCore.framework/Versions/A/Helpers/QtWebEngineProcess.app/Contents/MacOS/QtWebEngineProcess" "${MACOS_DST}"
    echo "✓ Symlink criado (relativo): ${MACOS_DST}"
fi

# 6. Assinatura Ad-Hoc (para execução local sem crash de assinatura)
echo "🔏 Aplicando assinatura ad-hoc (codesign)..."
# Remover assinaturas antigas para evitar conflitos com frameworks embutidos
codesign --remove-sign "${APP_PATH}" 2>/dev/null || true
codesign --force --deep --sign - "${APP_PATH}"

# 5. Criar Imagem de Disco (.dmg) com atalho para /Applications
echo "📦 Criando imagem de disco ${DMG_NAME}..."
DMG_TEMP_DIR="${BUILD_DIR}/dmg_staging"
rm -rf "${DMG_TEMP_DIR}"
mkdir -p "${DMG_TEMP_DIR}"

# Copiar .app para a pasta temporária do DMG
cp -R "${APP_PATH}" "${DMG_TEMP_DIR}/"

# Gerar arquivo .dmg final: tentar create-dmg primeiro (melhor UX), senão hdiutil
if command -v create-dmg &> /dev/null; then
    echo "🎨 Usando create-dmg para DMG com layout profissional..."
    create-dmg \
        --volname "${APP_NAME}" \
        --volicon "${SCRIPT_DIR}/icons/icon.icns" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "${APP_NAME}.app" 150 150 \
        --hide-extension "${APP_NAME}.app" \
        --app-drop-link 450 150 \
        --overwrite \
        "${DIST_DIR}/${DMG_NAME}" \
        "${DMG_TEMP_DIR}/" || true
fi

# Se create-dmg não criou ou não está disponível, usar hdiutil nativo com link simbólico manual
if [ ! -f "${DIST_DIR}/${DMG_NAME}" ]; then
    echo "💿 Usando hdiutil nativo do macOS..."
    if [ ! -L "${DMG_TEMP_DIR}/Applications" ]; then
        ln -s /Applications "${DMG_TEMP_DIR}/Applications"
    fi
    hdiutil create \
        -volname "${APP_NAME}" \
        -srcfolder "${DMG_TEMP_DIR}" \
        -ov \
        -format UDZO \
        "${DIST_DIR}/${DMG_NAME}"
fi

rm -rf "${DMG_TEMP_DIR}"

echo "=========================================================="
echo "🎉 Build concluído com sucesso!"
echo "📁 Bundle: ${APP_PATH}"
echo "💿 Imagem DMG: ${DIST_DIR}/${DMG_NAME}"
echo "=========================================================="
