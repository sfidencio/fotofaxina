# -*- mode: python ; coding: utf-8 -*-
# Gera dist/FotoFaxina/FotoFaxina.exe  ->  pyinstaller packaging/fotofaxina.spec --noconfirm
import os

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    (os.path.join(ROOT, "assets", "icon-256.png"), "assets"),
    (os.path.join(ROOT, "assets", "icon.ico"), "assets"),
    (os.path.join(ROOT, "assets", "mascote-128.png"), "assets"),
]
# IA leve (gerada por packaging/build_model.py); sem ela o app usa só as regras
models = os.path.join(ROOT, "models")
for name in ("clip_image.onnx", "clip_text.npy", "clip_labels.json"):
    if os.path.exists(os.path.join(models, name)):
        datas.append((os.path.join(models, name), "models"))
datas += collect_data_files("google_auth_oauthlib")

# credencial OAuth embutida (criada pelo GitHub Actions a partir de um secret; nunca vai para o git)
secret = os.path.join(SPECPATH, "client_secret.json")
if os.path.exists(secret):
    datas.append((secret, "."))

# Informações de versão no .exe (Propriedades → Detalhes). Executáveis sem isso parecem mais
# suspeitos para antivírus e para o SmartScreen.
import re
import sys

_version_file = None
if sys.platform == "win32":  # recurso de versão só existe em .exe do Windows

    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )

    _ver = re.search(r'__version__ = "(.+?)"', open(os.path.join(ROOT, "app", "__init__.py")).read()).group(1)
    _nums = tuple(int(x) for x in re.findall(r"\d+", _ver)[:3]) + (0,)
    _nums = (_nums + (0, 0, 0, 0))[:4]
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=_nums, prodvers=_nums, mask=0x3F, flags=0x0, OS=0x40004,
                          fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("041604B0", [
                StringStruct("CompanyName", "Fidencio"),
                StringStruct("FileDescription", "FotoFaxina - organiza fotos e envia ao Google Fotos"),
                StringStruct("FileVersion", _ver),
                StringStruct("InternalName", "FotoFaxina"),
                StringStruct("LegalCopyright", "Copyright (c) Fidencio. Código aberto: github.com/sfidencio/fotofaxina"),
                StringStruct("OriginalFilename", "FotoFaxina.exe"),
                StringStruct("ProductName", "FotoFaxina"),
                StringStruct("ProductVersion", _ver),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
        ],
    )
    _version_file = os.path.join(workpath, "version_info.txt")
    os.makedirs(workpath, exist_ok=True)
    with open(_version_file, "w", encoding="utf-8") as fh:
        fh.write(str(version_info))

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=["pillow_heif", "google_auth_oauthlib.flow"],
    excludes=[
        # a IA roda com ONNX Runtime; PyTorch/transformers só são usados para gerar o modelo
        "torch", "transformers", "tensorflow", "onnx",
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
    version=_version_file,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="FotoFaxina", upx=False)
