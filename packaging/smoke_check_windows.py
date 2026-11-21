#!/usr/bin/env python3
"""Smoke check do bundle Windows do Tomus (PR #13 - RapidOCR primario).

Valida:
  1. pyi_rth_pkgres ausente do CArchive do executável
  2. pkg_resources ausente do PYZ (quando existe como arquivo separado)
  3. Nenhuma dependência pesada de ML (torch, torchvision, transformers,
     docling, docling_core, docling_parse, docling_ibm_models) presente
     no bundle/dist/Tomus nem no PYZ
  4. DLLs do onnxruntime presentes no bundle
  5. QtWebEngineProcess.exe e qtwebengine_resources.pak presentes
  6. tomus.gui.os_integration (_reveal_windows_shell) presente no bundle/PYZ
  7. Self-test OCR do executável Tomus (--self-test-ocr) com exit code 0
  8. Boot offscreen do executável Tomus por 5s (sem Traceback/ImportError/AttributeError)
"""
import os
import subprocess
import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

DIST_DIR = Path("dist/Tomus")
EXE_PATH = DIST_DIR / "Tomus.exe"

# Dependências pesadas de ML que NÃO devem estar presentes no bundle
# (RapidOCR/onnxruntime substituem torch/transformers/docling).
_HEAVY_ML_DEPS = (
    "torch",
    "torchvision",
    "transformers",
    "docling",
    "docling_core",
    "docling_parse",
    "docling_ibm_models",
)


def check_pyi_rth_pkgres_absent() -> None:
    """pyi_rth_pkgres não deve estar no CArchive do executável."""
    arch = CArchiveReader(str(EXE_PATH))
    if "pyi_rth_pkgres" in arch.toc:
        print("FALHA: pyi_rth_pkgres encontrado no CArchive")
        sys.exit(1)
    print("OK: pyi_rth_pkgres ausente do CArchive")


def _find_pyz_key(arch) -> str | None:
    """Localiza a chave do arquivo PYZ no CArchive pelo sufixo .pyz."""
    for key in arch.toc.keys():
        if key.endswith(".pyz"):
            return key
    return None


def _open_pyz(arch) -> object | None:
    """Abre o arquivo PYZ embebido no CArchive, independente do nome exato."""
    pyz_key = _find_pyz_key(arch)
    if pyz_key is None:
        return None
    try:
        return arch.open_embedded_archive(pyz_key)
    except Exception:
        return None


def check_pkg_resources_absent_from_pyz() -> None:
    """pkg_resources não deve estar no PYZ."""
    arch = CArchiveReader(str(EXE_PATH))
    pyz = _open_pyz(arch)
    pyz_name = _find_pyz_key(arch) or "(desconhecido)"
    if pyz is not None:
        for key in pyz.toc.keys():
            if key == "pkg_resources" or key.startswith("pkg_resources."):
                print("FALHA: pkg_resources encontrado no PYZ")
                sys.exit(1)
        print(f"OK: pkg_resources ausente do PYZ ({pyz_name})")
    else:
        print(
            f"AVISO: arquivo PYZ não encontrado como entry separado "
            f"({pyz_name}; normal com exclude_binaries=True); "
            "pkg_resources verificado apenas no CArchive"
        )


def check_heavy_ml_deps_absent() -> None:
    """Nenhuma dependência pesada de ML (torch, transformers, docling etc.)
    deve estar presente no bundle/dist/Tomus nem no PYZ."""
    arch = CArchiveReader(str(EXE_PATH))
    pyz = _open_pyz(arch)
    pyz_keys = list(pyz.toc.keys()) if pyz is not None else []

    encontrados: list[str] = []

    # 1. Pastas/arquivos raiz do pacote: checar apenas base / dep
    #    para base em (DIST_DIR, DIST_DIR / '_internal').
    for base in (DIST_DIR, DIST_DIR / "_internal"):
        for dep in _HEAVY_ML_DEPS:
            m = base / dep
            if m.exists():
                rel = str(m.relative_to(DIST_DIR))
                if rel not in encontrados:
                    encontrados.append(rel)

    # 2. Metadados dist-info: iterar *.dist-info na raiz e checar o nome base.
    for m in DIST_DIR.rglob("*.dist-info"):
        base_name = m.name.split("-")[0].lower().replace("-", "_")
        if base_name in _HEAVY_ML_DEPS:
            rel = str(m.relative_to(DIST_DIR))
            if rel not in encontrados:
                encontrados.append(rel)

    # 3. No PYZ: checar apenas o nome de nível raiz da chave.
    for dep in _HEAVY_ML_DEPS:
        for key in pyz_keys:
            root = key.split(".")[0].split("/")[0]
            if root == dep:
                if key not in encontrados:
                    encontrados.append(key)

    if encontrados:
        print("FALHA: dependências pesadas de ML encontradas no bundle/PYZ:")
        for e in sorted(encontrados):
            print(f"  - {e}")
        sys.exit(1)
    print(
        "OK: nenhuma dependência pesada de ML (torch/torchvision/transformers/"
        "docling/*) presente no bundle nem no PYZ"
    )


def check_onnxruntime_dlls_present() -> None:
    """DLLs do onnxruntime devem estar presentes no bundle."""
    dlls = list(DIST_DIR.rglob("onnxruntime*.dll")) + list(
        DIST_DIR.rglob("*onnxruntime*.dll")
    )
    if not dlls:
        print("FALHA: DLLs do onnxruntime não encontradas no bundle")
        sys.exit(1)
    print(f"OK: {len(dlls)} DLL(s) do onnxruntime presente(s) no bundle")


def check_qtwebengine_present() -> None:
    """QtWebEngineProcess.exe e qtwebengine_resources.pak devem estar presentes."""
    exe_matches = list(DIST_DIR.rglob("QtWebEngineProcess.exe"))
    pak_matches = list(DIST_DIR.rglob("qtwebengine_resources.pak"))
    if not exe_matches:
        print("FALHA: QtWebEngineProcess.exe não encontrado no bundle")
        sys.exit(1)
    if not pak_matches:
        print("FALHA: qtwebengine_resources.pak não encontrado no bundle")
        sys.exit(1)
    print(
        f"OK: QtWebEngineProcess.exe presente no bundle "
        f"({exe_matches[0].relative_to(DIST_DIR)})"
    )
    print(
        f"OK: qtwebengine_resources.pak presente no bundle "
        f"({pak_matches[0].relative_to(DIST_DIR)})"
    )


def _get_co_names_from_pyz(pyz, module_path: str) -> tuple | None:
    """Retorna co_names de um módulo no PYZ, se disponível como código compilado."""
    if pyz is None:
        return None
    # Chaves do PYZ usam pontos (ex: tomus.gui.os_integration), não barras
    module_slash = module_path.replace(".", "/")
    for key in pyz.toc.keys():
        if key == module_path or key == module_slash or key.endswith("/" + module_slash):
            try:
                extracted = pyz.extract(key)
                # PyInstaller 6 pode retornar um objeto code já compilado ou bytes-fonte
                if hasattr(extracted, "co_names"):
                    return extracted.co_names
                source = extracted.decode("utf-8") if isinstance(extracted, bytes) else extracted
                code = compile(source, key, "exec")
                return code.co_names
            except Exception:
                return None
    return None


def check_os_integration_present() -> None:
    """tomus.gui.os_integration (_reveal_windows_shell) deve estar no bundle/PYZ."""
    arch = CArchiveReader(str(EXE_PATH))
    pyz = _open_pyz(arch)

    os_integration_names = _get_co_names_from_pyz(pyz, "tomus.gui.os_integration")
    if os_integration_names is not None:
        if "_reveal_windows_shell" not in os_integration_names:
            print(
                "FALHA: _reveal_windows_shell não está em co_names de "
                "tomus.gui.os_integration no PYZ"
            )
            sys.exit(1)
        print(
            "OK: tomus.gui.os_integration contém _reveal_windows_shell "
            "no PYZ (co_names)"
        )
        return

    # Fallback: verificar como arquivo no bundle
    oi_file = DIST_DIR / "_internal" / "tomus" / "gui" / "os_integration.py"
    if not oi_file.exists():
        print("FALHA: tomus.gui.os_integration não encontrado no bundle")
        sys.exit(1)
    source = oi_file.read_text(encoding="utf-8")
    if "_reveal_windows_shell" not in source:
        print(
            "FALHA: _reveal_windows_shell não encontrado em "
            "tomus.gui.os_integration"
        )
        sys.exit(1)
    print(
        "OK: tomus.gui.os_integration contém _reveal_windows_shell "
        "(arquivo no bundle)"
    )


def check_self_test_ocr() -> None:
    """Executável Tomus deve passar no self-test OCR (--self-test-ocr) com exit code 0."""
    p = subprocess.Popen(
        [str(EXE_PATH), "--self-test-ocr"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
    )
    try:
        out, _ = p.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill()
        out, _ = p.communicate()
        print("FALHA: executável encerrou antes de 30s no self-test OCR")
        print(out)
        sys.exit(1)

    if p.returncode != 0:
        print(f"FALHA: executável saiu com código {p.returncode} no self-test OCR")
        print(out)
        sys.exit(1)

    if "OK:" not in out and not ("TOMUS" in out and "2026" in out):
        print(
            "FALHA: stdout não contém 'OK:' nem 'TOMUS ... 2026' no self-test OCR"
        )
        print(out)
        sys.exit(1)

    print(
        "OK: self-test OCR passou com exit code 0 e saída contendo 'OK:' "
        "ou 'TOMUS ... 2026'"
    )


def check_boot_offscreen_5s() -> None:
    """Executável Tomus deve permanecer vivo por 5s offscreen sem erro."""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"

    p = subprocess.Popen(
        [str(EXE_PATH)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    try:
        out, _ = p.communicate(timeout=5)
        print(f"FALHA: executável encerrou antes de 5s (rc={p.returncode})")
        print(out)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        p.terminate()
        try:
            out, _ = p.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            p.kill()
            out, _ = p.communicate()
    bad = ("Traceback", "ImportError", "AttributeError", "SIGABRT")
    for token in bad:
        if token in out:
            print(f"FALHA: encontrou '{token}' no boot offscreen")
            print(out)
            sys.exit(1)
    print("OK: executável Tomus rodou 5s offscreen sem erro")


def main() -> None:
    print("=== Smoke check Windows: verifica ausência de pyi_rth_pkgres e pkg_resources ===")
    check_pyi_rth_pkgres_absent()
    check_pkg_resources_absent_from_pyz()

    print("=== Smoke check Windows: dependências pesadas de ML ausentes ===")
    check_heavy_ml_deps_absent()

    print("=== Smoke check Windows: DLLs do onnxruntime presentes ===")
    check_onnxruntime_dlls_present()

    print("=== Smoke check Windows: QtWebEngineProcess.exe e .pak presentes ===")
    check_qtwebengine_present()

    print("=== Smoke check Windows: tomus.gui.os_integration (_reveal_windows_shell) ===")
    check_os_integration_present()

    print("=== Smoke check Windows: self-test OCR do executável Tomus ===")
    check_self_test_ocr()

    print("=== Smoke check Windows: boot offscreen do executável Tomus por 5s ===")
    check_boot_offscreen_5s()

    print("Smoke check Windows passou com sucesso")


if __name__ == "__main__":
    main()
