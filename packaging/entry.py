"""打包入口（Graphical Launcher）。

行为约定：

* **双击运行（不带任何参数）** → 直接打开图形界面，无须敲命令。
  配置文件放在用户可写的工作目录：``%LOCALAPPDATA%\\medshift``
  （非 Windows 或取不到该变量时退化为 ``~/.medshift``）。
  首次运行时自动从随包分发的示例配置初始化该目录，之后改动都留在那里。
* **带参数运行** → 走正常命令行，例如 ``medshift.exe check -c my-dept -a x.csv``。

之所以单独写这个入口文件，而不直接把 ``medshift/cli.py`` 当脚本打包，
是因为后者用的是相对导入（``from .config_loader import ...``），
作为顶层脚本运行时包上下文会丢失。
"""

import os
import shutil
import sys
from pathlib import Path

ENV_OVERRIDE = "MEDSHIFT_HOME"  # 允许高级用户自定工作目录


def _workspace_dir() -> Path:
    """返回可写的用户工作目录（不创建）。"""
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return Path(override).expanduser()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "medshift"
    return Path.home() / ".medshift"


def _seed_workspace(workspace: Path) -> bool:
    """首次运行：把内置示例配置复制到工作目录，作为可编辑的起点。

    返回是否真的复制了内容。已存在 ``staff.yaml`` 时视为已初始化，直接跳过。
    """
    if (workspace / "staff.yaml").exists():
        return False

    from medshift.cli import _resource_path

    source = _resource_path("examples", "radiology")
    if not source.is_dir():
        return False

    workspace.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name.startswith("__"):
            continue
        target = workspace / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
    return True


def run() -> None:
    """入口：决定是打开图形界面还是执行命令行。"""
    from medshift.cli import main

    if len(sys.argv) == 1:
        # 双击场景：直接进图形界面
        workspace = _workspace_dir()
        try:
            fresh = _seed_workspace(workspace)
        except OSError as exc:
            print(f"初始化工作目录失败：{exc}", file=sys.stderr)
            fresh = False

        if fresh:
            print(f"已初始化工作目录：{workspace}")
        else:
            print(f"工作目录：{workspace}")

        sys.argv = [sys.argv[0], "gui", "--config", str(workspace)]
        print("正在打开图形界面…关闭本窗口即可退出程序。")

    main()


if __name__ == "__main__":
    run()
