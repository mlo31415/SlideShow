# -*- mode: python ; coding: utf-8 -*-
import os

a = Analysis(
    ['SlideShow.py'],
    # FaceGeometry, the face circle shared with PhotosEditor, lives in HelpersPackage
    pathex=[os.path.join(SPECPATH, '..', 'HelpersPackage')],
    binaries=[],
    # Built in so they are there whatever folder the .exe is run from.  Everything the
    # *user* keeps -- the settings, the shows, the state, the output logs -- is not
    # bundled: SlideShow looks for those beside the .exe itself.
    datas=[('SlideShow.ico', '.'),
           ('face_detection_yunet_2023mar.onnx', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SlideShow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # A console window behind a public display helps nobody
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['SlideShow.ico'],
)
