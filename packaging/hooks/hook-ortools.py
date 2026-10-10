"""PyInstaller 钩子：完整收集 OR-Tools（CP-SAT 求解器）。

OR-Tools 的运行时由三部分组成，PyInstaller 的自动探测**只认得出 .pyd**：

1. Python 扩展模块 ``*.pyd``（在 ``ortools/`` 各子目录下，自动探测能认出部分）；
2. **原生共享库** ``ortools/.libs/*.dll``（Windows）／``*.so``（Linux）
   —— ``ortools.dll``、``abseil_dll.dll``、``libprotobuf.dll`` 等，
   这些是 ``_pywrapcp.pyd`` 的动态依赖，PyInstaller **认不出**，
   必须手动放进 ``binaries`` 才会被打包；
3. 少量数据文件（如 ``*.pyi``、LICENSE）。

若缺少第 2 部分，冻结后的程序 import ortools 不报错，但真正调用
``cp_model.CpSolver().Solve()`` 时会因 DLL 找不到而失败；本项目的
表现是 ``medshift solve`` 提示「未安装 ortools」。

钩子用法：把本文件所在目录加进 spec 的 ``hookspath``。
"""

import os
import glob
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs


def _ortools_dir() -> str | None:
    try:
        import ortools  # noqa: PLC0415
    except ImportError:
        return None
    return os.path.dirname(ortools.__file__)


datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = []

_root = _ortools_dir()

if _root:
    # ---- 1) 原生共享库：整个 .libs 目录 ----
    libs_dir = Path(_root) / ".libs"
    if libs_dir.is_dir():
        for dll in glob.glob(str(libs_dir / "*")):
            # 目标目录放 ortools/.libs，与源码树布局一致，
            # 这样 pyd 里记录的相对加载路径仍然有效
            binaries.append((dll, "ortools/.libs"))
    # 兜底：collect_dynamic_libs 再扫一遍（覆盖不同平台的布局差异）
    binaries += collect_dynamic_libs("ortools")

    # ---- 2) 所有 .pyd 扩展模块，确保子包都在 ----
    for pyd in glob.glob(str(Path(_root) / "**" / "*.pyd"), recursive=True):
        rel = os.path.relpath(pyd, _root)
        binaries.append((pyd, os.path.join("ortools", os.path.dirname(rel))))

    # ---- 3) 显式列出 CP-SAT 依赖链上的 Python 模块 ----
    hiddenimports += [
        "ortools",
        "ortools.init",
        "ortools.init.python",
        "ortools.init.python.init",
        "ortools.sat",
        "ortools.sat.python",
        "ortools.sat.python.cp_model",
        "ortools.sat.python.cp_model_helper",
        "ortools.constraint_solver",
        "ortools.constraint_solver.pywrapcp",
        "ortools.util",
        "ortools.util.python",
        "ortools.util.python.helpers",
        "ortools.util.python.sorted_interval_list",
        "ortools.linear_solver",
        "ortools.linear_solver.pywraplp",
        "ortools.algorithms",
        "ortools.algorithms.python",
        "ortools.algorithms.python.knapsack_solver",
        "ortools.graph",
        "ortools.graph.python",
        "ortools.graph.python.max_flow",
        "ortools.graph.python.min_cost_flow",
        "ortools.graph.python.linear_sum_assignment",
    ]

# ortools 依赖 numpy / pandas / protobuf，PyInstaller 会顺着 import 自动收集，
# 这里只做提示：不要在 spec 的 excludes 里排除它们。
