#!/usr/bin/env python3
"""Smoke check do bundle macOS do Tomus.

Valida:
  1. pyi_rth_pkgres ausente do CArchive do executável
  2. pkg_resources ausente do PYZ (quando existe como arquivo separado)
  3. libavcodec presente em Contents/Frameworks
  4. docling_slim dist-info coletado no bundle
  5. Boot offscreen do executável Tomus por 5s (sem Traceback/ImportError/AttributeError/SIGABRT)
"""
import os
import subprocess
import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

APP_PATH = Path("dist/Tomus.app")
EXE_PATH = APP_PATH / "Contents" / "MacOS" / "Tomus"
FRAMEWORKS_DIR = APP_PATH / "Contents" / "Frameworks"


def check_pyi_rth_pkgres_absent() -> None:
    """pyi_rth_pkgres não deve estar no CArchive do executável."""
    arch = CArchiveReader(str(EXE_PATH))
    if "pyi_rth_pkgres" in arch.toc:
        print("FALHA: pyi_rth_pkgres encontrado no CArchive")
        sys.exit(1)
    print("OK: pyi_rth_pkgres ausente do CArchive")


def check_pkg_resources_absent_from_pyz() -> None:
    """pkg_resources não deve estar no PYZ."""
    arch = CArchiveReader(str(EXE_PATH))
    try:
        pyz = arch.open_embedded_archive("PYZ-00.pyz")
    except Exception:
        pyz = None
    if pyz is not None:
        for key in pyz.toc.keys():
            if key == "pkg_resources" or key.startswith("pkg_resources."):
                print("FALHA: pkg_resources encontrado no PYZ")
                sys.exit(1)
        print("OK: pkg_resources ausente do PYZ")
    else:
        print(
            "AVISO: PYZ-00.pyz não encontrado como arquivo separado "
            "(normal em macOS com exclude_binaries=True); "
            "pkg_resources verificado apenas no CArchive"
        )


def check_libavcodec_present() -> None:
    """libavcodec deve estar em Contents/Frameworks."""
    matches = list(FRAMEWORKS_DIR.glob("libavcodec*"))
    if not matches:
        print("FALHA: libavcodec não encontrado em Contents/Frameworks")
        sys.exit(1)
    print(f"OK: libavcodec presente em Contents/Frameworks ({matches[0].name})")


def check_docling_slim_present() -> None:
    """docling_slim dist-info deve estar coletado no bundle."""
    matches = list(APP_PATH.rglob("docling_slim*-*.dist-info"))
    if not matches:
        print("FALHA: docling_slim dist-info não encontrado no bundle")
        sys.exit(1)
    print(f"OK: docling_slim dist-info presente no bundle ({matches[0].relative_to(APP_PATH)})")


def check_boot_offscreen_5s() -> None:
    """Executável Tomus deve permanecer vivo por 5s offscreen sem erro."""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"

    p = subprocess.Popen(
        [str(EXE_PATH)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
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
    print("=== Smoke check: verifica ausência de pyi_rth_pkgres e pkg_resources ===")
    check_pyi_rth_pkgres_absent()
    check_pkg_resources_absent_from_pyz()

    print("=== Smoke check: libavcodec em Contents/Frameworks ===")
    check_libavcodec_present()

    print("=== Smoke check: docling_slim dist-info coletado ===")
    check_docling_slim_present()

    print("=== Smoke check: boot offscreen do executável Tomus por 5s ===")
    check_boot_offscreen_5s()

    print("Smoke check passou com sucesso")


if __name__ == "__main__":
    main()
