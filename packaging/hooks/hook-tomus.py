"""PyInstaller hook para o Tomus.

Suprime coleta de binários dinâmicos do OpenSSL embarcados no opencv-python-headless
(cv2/.dylibs/libssl*, cv2/.dylibs/libcrypto*, cv2/__dot__dylibs/libssl*,
cv2/__dot__dylibs/libcrypto*) para evitar sobrescrever o OpenSSL 3 do sistema
em Contents/Frameworks/, o que quebraria "import ssl" no boot do app.

Os symlinks de libavcodec/libavformat/libavutil/libswscale são preservados para
que `import cv2` funcione corretamente dentro do bundle.
"""
bindepend_symlink_suppression = [
    "**/cv2/.dylibs/libssl*",
    "**/cv2/.dylibs/libcrypto*",
    "**/cv2/__dot__dylibs/libssl*",
    "**/cv2/__dot__dylibs/libcrypto*",
]
