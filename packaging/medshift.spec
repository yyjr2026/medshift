# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 生成单文件命令行程序。

在仓库根目录运行：

    pyinstaller packaging/medshift.spec --noconfirm --clean

产物：``dist/medshift.exe``（Windows）/ ``dist/medshift``（macOS、Linux）。
"""

from pathlib import Path

# SPECPATH 是本 spec 文件所在目录（仓库的 packaging/），其父目录即仓库根
ROOT = Path(SPECPATH).resolve().parent  # noqa: F821

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    # 把内置示例配置一并打进包里，供 `medshift init` 复制模板使用
    datas=[
        (str(ROOT / "examples" / "radiology"), "examples/radiology"),
        # 图形界面：模板与静态资源必须随包分发，否则冻结后页面 404
        (str(ROOT / "medshift" / "gui" / "templates"), "medshift/gui/templates"),
        (str(ROOT / "medshift" / "gui" / "static"), "medshift/gui/static"),
    ],
    hiddenimports=[
        "typer",
        "click",
        "pydantic",
        "pydantic_core",
        "openpyxl",
        "yaml",
        # Flask 及其依赖：PyInstaller 对 Flask 的自动探测不完整，显式列出
        "flask",
        "jinja2",
        "werkzeug",
        "itsdangerous",
        "markupsafe",
        "blinker",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除明显用不到的重型库，压缩体积
    excludes=["tkinter", "pytest", "numpy", "pandas", "matplotlib", "IPython"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="medshift",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,  # 命令行程序，保留控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "packaging" / "medshift.ico"),
)
