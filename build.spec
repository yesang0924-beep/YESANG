# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— Relay Console

要点（pywebview 官方建议）：
  - Windows 下走 EdgeChromium（WebView2），PyQt/PySide/tkinter 都用不到，
    全部 exclude 掉，否则 PyInstaller 会把它们误打进包里，体积白涨几十 MB。
  - datas 把 web/ 前端资源打进包；运行时通过 sys._MEIPASS 读取。
  - onefile + noconsole：单文件、无黑窗。
"""

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('web', 'web')],
    hiddenimports=[
        'clr_loader', 'pythonnet',
        # pywebview 的平台后端是按系统动态选择的，PyInstaller 静态分析抓不到，
        # 不显式声明会在冻结后启动即崩（无窗口、无报错）。
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        # tray.py 里是函数内延迟导入，静态分析同样抓不到
        'pystray', 'pystray._win32',
        'PIL', 'PIL.Image', 'PIL.ImageDraw',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'tkinter', 'matplotlib', 'numpy', 'pandas',
        'unittest', 'pydoc_data',
    ],
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
    name='RelayConsole',
    debug=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    console=False,          # 无控制台（pythonw 行为），不会闪黑窗
    icon=None,
)
