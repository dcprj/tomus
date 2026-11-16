"""PyInstaller hook para o Tomus.

Suprime coleta de binários dinâmicos do OpenSSL embarcados no opencv-python-headless
(cv2/.dylibs e cv2/__dot__dylibs) para evitar sobrescrever o OpenSSL 3 do sistema
em Contents/Frameworks/, o que quebraria "import ssl" no boot do app.
"""
bindepend_symlink_suppression = [
    "**/cv2/.dylibs/*",
    "**/cv2/__dot__dylibs/*",
]
