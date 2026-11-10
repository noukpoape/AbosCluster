# -*- mode: python ; coding: utf-8 -*-
# Recette PyInstaller d'AbosCluster (Windows, macOS, Linux).
# Depuis la racine du depot :  pyinstaller --noconfirm --clean installer/aboscluster.spec
#   Windows / Linux : dist/AbosCluster/ (executable + _internal/)
#   macOS           : dist/AbosCluster.app (tous les fichiers dans le paquet .app)
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files

RACINE = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(RACINE, "aboscluster")
ICONES = os.path.join(SPECPATH, "icons")
VERSION = os.environ.get("ABOS_VERSION", "1.0.0")

datas = [(os.path.join(SRC, "ABOS"), "ABOS")]          # icones + manuels (ABOS/manuals)
binaries = []
hiddenimports = ["openpyxl", "xlrd", "docx", "PIL._tkinter_finder", "tkmacosx"]
for paquet in ("pypdfium2", "pypdfium2_raw", "tkmacosx"):  # bibliotheque pdfium et donnees
    try:
        d, b, h = collect_all(paquet)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass
datas += collect_data_files("docx")                    # modele Word par defaut

a = Analysis(
    [os.path.join(SRC, "AbosCluster.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "jupyter", "notebook", "pytest"],
    noarchive=False,
)
# icones de l'application macOS (dossier ABOS/macOS) : inutiles dans le programme
a.datas = [x for x in a.datas if "macOS" not in x[0].replace("\\", "/").split("/")]

pyz = PYZ(a.pure)

if sys.platform == "win32":
    icone = os.path.join(ICONES, "AbosCluster.ico")
elif sys.platform == "darwin":
    icone = os.path.join(ICONES, "AbosCluster.icns")
else:
    icone = None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AbosCluster",
    console=False,                                     # pas de fenetre console
    icon=icone,
    upx=False,
    strip=False,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AbosCluster")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="AbosCluster.app",
        icon=icone,
        bundle_identifier="fr.inria.aboscluster",
        version=VERSION,
        info_plist={
            "CFBundleName": "AbosCluster",
            "CFBundleDisplayName": "AbosCluster",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "CFBundleDevelopmentRegion": "fr",
            "CFBundleLocalizations": ["fr", "en"],
        },
    )
