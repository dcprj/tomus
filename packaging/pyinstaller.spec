# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file multiplataforma para o Tomus (macOS e Windows).

Gera:
- macOS: Tomus.app (bundle nativo sem console)
- Windows: Tomus.exe (GUI noconsole com ícone)
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    collect_dynamic_libs,
    collect_all,
    copy_metadata,
)

block_cipher = None

# Raiz do projeto (no PyInstaller spec, SPECPATH contém o diretório do arquivo .spec)
try:
    SPEC_DIR = Path(SPECPATH).resolve()
except NameError:
    SPEC_DIR = Path.cwd() / "packaging"

ROOT_DIR = SPEC_DIR.parent
SRC_DIR = ROOT_DIR / "src"
ICONS_DIR = ROOT_DIR / "packaging" / "icons"

# Dados estáticos obrigatórios
datas = [
    (str(SRC_DIR / "tomus" / "gui" / "web"), "tomus/gui/web"),
    (str(SRC_DIR / "tomus" / "gui" / "resources"), "tomus/gui/resources"),
    (str(SRC_DIR / "tomus" / "core" / "resources"), "tomus/core/resources"),
]

# Hidden imports essenciais para PySide6 WebEngine, dependências dinâmicas e OCR Docling
hiddenimports = [
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "fitz",
    "rapidfuzz",
    "rapidfuzz.distance",
    "tenacity",
    "stdnum",
    "stdnum.isbn",
    "stdnum.doi",
    "tomli_w",
    "rich",
    "typer",
    "pydantic",
    "pydantic_settings",
    "google.genai",
    "httpx",
    "rapidocr",
    "onnxruntime",
    # Módulo do projeto com interações específicas do Windows (Prisma: _reveal_windows_shell)
    "tomus.gui.os_integration",
]

# Coletar binários/DLLs do onnxruntime (essenciais no Windows para RapidOCR)
binaries = []
binaries += collect_dynamic_libs("onnxruntime")

# Coletar submódulos e arquivos de dados do RapidOCR e onnxruntime (essenciais
# para modelos .onnx e configs no bundle .app/.exe). Docling, torch, torchvision
# e transformers permanecem removidos (RapidOCR agora primário).
for pkg in ["rapidocr", "onnxruntime"]:
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

# Coletar TODOS os arquivos do QtWebEngine (QtWebEngineProcess.app, .pak, icudtl.dat)
# Essenciais para evitar crash SIGABRT no WebContentsAdapter em bundles congelados
webengine_data = collect_all("PySide6.QtWebEngineCore")
webengine_widgets_data = collect_all("PySide6.QtWebEngineWidgets")
datas += webengine_data[0] if isinstance(webengine_data, tuple) else webengine_data
binaries += webengine_data[1] if isinstance(webengine_data, tuple) else []
hiddenimports += webengine_data[2] if isinstance(webengine_data, tuple) else []
datas += webengine_widgets_data[0] if isinstance(webengine_widgets_data, tuple) else webengine_widgets_data
binaries += webengine_widgets_data[1] if isinstance(webengine_widgets_data, tuple) else []
hiddenimports += webengine_widgets_data[2] if isinstance(webengine_widgets_data, tuple) else []

# Coletar binários do QtWebEngineProcess (macOS)
if sys.platform == "darwin":
    qwebengine_process_binaries = collect_dynamic_libs("PySide6.QtWebEngineCore")
    binaries += qwebengine_process_binaries

try:
    hiddenimports += collect_submodules("tomus")
except Exception:
    pass

a = Analysis(
    [str(SRC_DIR / "tomus" / "gui" / "app.py")],
    pathex=[str(SRC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(SPEC_DIR / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "notebook", "pkg_resources",
              "torch", "torchvision", "transformers", "docling", "docling_core",
              "docling_parse", "docling_ibm_models", "huggingface_hub", "accelerate",
              "tokenizers", "safetensors"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Filtrar binários duplicados do OpenCV que sobrescreveriam o OpenSSL 3 do sistema.
# No macOS, libsrt.1.5.3.dylib usa @rpath/@loader_path e resolve diretamente para
# Contents/Frameworks/, então devemos evitar copiar libcrypto.3.dylib e libssl.3.dylib
# de cv2/.dylibs/ ou cv2/__dot__dylibs/ para o topo do bundle.
# Cada entry em a.binaries eh 3-tupla: (dest, src, typecode)
if sys.platform == "darwin":
    _cv2_libs_to_exclude = {"libcrypto.3.dylib", "libssl.3.dylib"}
    a.binaries = [
        e for e in a.binaries
        if not (
            Path(e[0]).name in _cv2_libs_to_exclude
            and (
                e[0].startswith("cv2/.dylibs/")
                or e[0].startswith("cv2/__dot__dylibs/")
            )
        )
    ]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Configuração de Ícone (se presente)
icon_macos = str(ICONS_DIR / "icon.icns")
icon_win = str(ICONS_DIR / "icon.ico")

icon_target = None
if sys.platform == "darwin" and os.path.exists(icon_macos):
    icon_target = icon_macos
elif sys.platform == "win32" and os.path.exists(icon_win):
    icon_target = icon_win

# Modo diretório (melhor para aplicações ricas com QtWebEngine)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Tomus",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=sys.platform != "win32",  # UPX desativado apenas no Windows
    console=False,  # Sem janela de terminal/prompt de comando preta
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_target,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=sys.platform != "win32",  # UPX desativado apenas no Windows
    upx_exclude=[],
    name="Tomus",
)

# No macOS, encapsula o diretório em um bundle .app nativo com metadados Apple
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Tomus.app",
        icon=icon_target,
        bundle_identifier="org.tomus.app",
        info_plist={
            "CFBundleName": "Tomus",
            "CFBundleDisplayName": "Tomus — Organizador Acadêmico de PDFs",
            "CFBundleVersion": "1.4.3",
            "CFBundleShortVersionString": "1.4.3",
            "CFBundlePackageType": "APPL",
            "CFBundleSignature": "????",
            "LSMinimumSystemVersion": "12.0.0",
            "NSHighResolutionCapable": True,
            "NSSupportsAutomaticGraphicsSwitching": True,
            "LSApplicationCategoryType": "public.app-category.education",
            "NSHumanReadableCopyright": "Copyright © 2026 Tomus. Licença Gratuita.",
        },
    )
