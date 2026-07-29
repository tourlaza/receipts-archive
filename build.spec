# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec — φτιάχνει ένα αυτόνομο .exe (δεν χρειάζεται Python).
# Χρήση:  pyinstaller build.spec
#
# Όλες οι διαδρομές είναι σχετικές ως προς αυτό το αρχείο, ώστε το build να
# δουλεύει σε οποιονδήποτε υπολογιστή.

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('webview')
# Το keyring φορτώνει τα backends του δυναμικά — χωρίς αυτό, το .exe δεν
# βρίσκει το Windows Credential Locker και ο κωδικός email δεν αποθηκεύεται.
hiddenimports += collect_submodules('keyring')

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('templates', 'templates'), ('static', 'static')],
    hiddenimports=hiddenimports,
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
    name='Αρχείο Αποδείξεων',
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
    icon=['icon.ico'],
)
