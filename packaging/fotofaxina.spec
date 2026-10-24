# -*- mode: python ; coding: utf-8 -*-
# Gera dist/FotoFaxina/FotoFaxina.exe  ->  pyinstaller packaging/fotofaxina.spec --noconfirm
import os

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    (os.path.join(ROOT, "assets", "icon-256.png"), "assets"),
    (os.path.join(ROOT, "assets", "icon.ico"), "assets"),
]
datas += collect_data_files("google_auth_oauthlib")

# credencial OAuth embutida (criada pelo GitHub Actions a partir de um secret; nunca vai para o git)
secret = os.path.join(SPECPATH, "client_secret.json")
if os.path.exists(secret):
    datas.append((secret, "."))

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=["pillow_heif", "google_auth_oauthlib.flow"],
    excludes=[
        # IA local fica de fora do instalador (PyTorch tem ~2 GB); o app usa só as regras
        "torch", "transformers", "tensorflow",
        "tkinter", "matplotlib", "IPython", "pytest", "scipy", "imagehash", "pywt",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtNetwork", "PySide6.QtOpenGL",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FotoFaxina",
    console=False,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="FotoFaxina", upx=False)
