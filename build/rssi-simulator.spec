# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/home/ahubert/prj-veille/rssi-game/main.py'],
    pathex=[],
    binaries=[],
    datas=[('/home/ahubert/prj-veille/rssi-game/scenarios', 'scenarios'), ('/home/ahubert/prj-veille/rssi-game/data', 'data'), ('/home/ahubert/prj-veille/rssi-game/assets', 'assets')],
    hiddenimports=['ui.screens.main_menu', 'ui.screens.org_selection', 'ui.screens.dashboard', 'ui.screens.incident_room', 'ui.screens.ebios_workshop', 'ui.screens.audit_screen', 'ui.screens.budget_screen', 'ui.screens.game_over', 'ui.screens.operations', 'ui.screens.lobby', 'sqlalchemy.dialects.sqlite'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['llama_cpp', 'tkinter', 'unittest', 'pytest', 'numpy', 'IPython', 'matplotlib', 'PIL'],
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
    name='rssi-simulator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['/home/ahubert/prj-veille/rssi-game/assets/images/icon.ico'],
)
