from pathlib import Path


project_root = Path(SPECPATH).parent
app_dir = project_root / "app"
icon = app_dir / "assets" / "ProxmoxLxcSshManager_logo.ico"

a = Analysis(
    [str(app_dir / "ProxmoxLxcSshManager.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(icon), "assets")],
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
    name="ProxmoxLxcSshManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon),
)
