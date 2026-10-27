# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Cartoon Print Studio
# Entry: gui.py (PyWebView native window, NOT browser-launcher)

import os
from pathlib import Path

# Resolve the project root from this spec file so a build always packages the
# checkout it was started from, not a hard-coded directory.
SPEC_DIR = Path(globals()["SPECPATH"]).resolve() if "SPECPATH" in globals() else Path.cwd().resolve()
ROOT = SPEC_DIR.parent if SPEC_DIR.name == "installer" else SPEC_DIR

block_cipher = None

# API credentials are per-device configuration and must never enter a build.
data_pairs = [
    (str(ROOT / "backend"), "backend"),
    (str(ROOT / "frontend"), "frontend"),
    (str(ROOT / "installer" / "demo"), os.path.join("data", "demo")),
]

a = Analysis(
    [str(ROOT / "gui.py")],
    pathex=[str(ROOT), str(ROOT / "backend")],
    binaries=[],
    datas=data_pairs,
    hiddenimports=[
        # uvicorn + fastapi
        "uvicorn", "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
        "uvicorn.protocols", "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto", "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi", "fastapi.middleware", "fastapi.middleware.cors",
        "fastapi.staticfiles", "fastapi.responses", "fastapi.routing",
        "fastapi.exceptions", "fastapi.encoders", "fastapi.params",
        "fastapi.dependencies", "fastapi.security", "fastapi.openapi",
        "fastapi.utils", "fastapi.background", "starlette", "starlette.applications",
        "starlette.routing", "starlette.responses", "starlette.staticfiles",
        "starlette.middleware", "starlette.middleware.cors", "starlette.exceptions",
        "pydantic", "pydantic.fields", "pydantic.main", "multipart",
        # imaging / 3d
        "PIL", "PIL.Image",
        "trimesh", "shapely", "rtree", "networkx",
        # networking
        "requests", "certifi", "charset_normalizer", "urllib3", "idna",
        "anyio",
        "scipy", "scipy.ndimage", "scipy.ndimage.filters", "scipy.spatial",
        "skimage", "skimage.measure", "skimage.morphology",
        "xatlas", "yaml",
        # PyWebView + Windows backend (Edge WebView2)
        "webview", "pywebview",
        "pywebview.platforms", "pywebview.platforms.winforms",
        "pywebview.platforms.edgechromium",
        "bottle", "bottle", "cffi",
        "pythonnet", "clr_loader",
        "win32gui", "win32com",
        # our helpers
        "progress",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "torch.*", "torchvision", "torchvision.*", "torchaudio", "torchaudio.*", "torchmcubes", "torchmcubes_skimage", "rmbg_remove", "briarmbg", "tsr", "hy3dgen", "hy3dgen.*", "diffusers", "transformers", "xformers", "tensorflow", "onnxruntime", "timm", "pydub", "matplotlib", "pandas", "IPython", "jupyter", "pytest", "tkinter", "test", "cv2", "skimage.draw", "skimage.filters", "skimage.exposure"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CartoonPrintStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # keep console in dev for log visibility
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CartoonPrintStudio",
)
