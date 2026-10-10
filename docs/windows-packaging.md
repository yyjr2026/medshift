# Windows 打包与分发

本文说明把 medshift 做成 Windows 可分发程序的方式、实测结果与注意事项。
**文中所有命令与产物均在 2026-10-10 实测通过。**

---

## 一、两种分发形态（均已实测产出）

| 形态 | 文件 | 用户拿到的东西 | 适用 |
|---|---|---|---|
| **免安装版** | `dist\medshift.exe`（约 18 MB） | 单文件，拷过去就能用 | 自己用、临时用 |
| **安装包** | `dist\medshift-0.2.0-setup.exe`（约 20 MB） | 中文向导安装、开始菜单/桌面快捷方式、控制面板可卸载 | 给科室同事装 |

两个都是**同一个程序**：双击运行直接打开图形界面（浏览器排班板）；
带参数运行则是命令行（`validate / check / export / stats` 等）。

> 双击即用的实现：打包入口 `packaging/entry.py` 在"无参数启动"时自动
> 打开图形界面。配置文件放在用户可写目录 `%LOCALAPPDATA%\medshift`，
> 首次运行自动从内置示例初始化，之后改动都留在那里。
> 可用环境变量 `MEDSHIFT_HOME` 改工作目录、`MEDSHIFT_NO_BROWSER=1`
> 禁止自动开浏览器（自动化/CI 场景）。

---

## 二、复现步骤

### 前提

- Python ≥ 3.10（打包机需要；**用户电脑不需要**）
- PyInstaller：`pip install pyinstaller`
- Inno Setup 6（仅制作安装包需要）：https://jrsoftware.org/isdl.php
  本机已装在 `%LOCALAPPDATA%\Programs\Inno Setup 6`

### 出免安装版 exe

```bash
pyinstaller packaging/medshift.spec --noconfirm --clean
# 产物 dist/medshift.exe
```

### 出安装包

```bash
# 1. 先出 exe（同上）
# 2. 编译安装脚本（ISCC 是 Inno Setup 的命令行编译器）
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\medshift.iss
# 产物 dist/medshift-0.2.0-setup.exe
```

中文安装向导已自包含：语言文件随项目放在 `packaging\ChineseSimplified.isl`，
不依赖 Inno Setup 安装目录里有没有中文包。

---

## 三、安装包实测记录（2026-10-10）

| 步骤 | 结果 |
|---|---|
| 静默安装到临时目录 `/DIR=...` | ✅ 退出码 0，装出 `medshift.exe`、`README.md`、`docs\gui.md`、`unins000.*` |
| 安装后的 exe 运行 `--help` | ✅ 正常 |
| 静默卸载 `unins000.exe /VERYSILENT` | ✅ 安装目录完全移除 |
| 双击 exe（无参数） | ✅ 自动初始化工作目录（7 个文件）→ 图形界面 HTTP 200 |

安装脚本要点（`packaging/medshift.iss`）：

- 装到 `%LOCALAPPDATA%\Programs\medshift`，**免管理员权限**
- 快捷方式直接指向 exe（即直接进图形界面），另留一个"命令行（帮助）"入口
- 卸载后**不**自动删除用户数据目录 `%LOCALAPPDATA%\medshift`（避免误删排班数据）

程序图标 `packaging\medshift.ico`（日历＋医疗十字）同时嵌入了 exe 与安装向导。

---

## 四、注意事项

| 问题 | 说明与对策 |
|---|---|
| **首次启动慢** | 单文件模式每次启动要解压到临时目录，约 1—3 秒。可改 `--onedir` 目录模式 |
| **杀毒软件误报** | PyInstaller 程序常被国产杀软拦截。正式分发建议代码签名（OV/EV 证书），否则 SmartScreen 提示"未知发布者" |
| **只支持 64 位** | 64 位 Python 打出 64 位 exe；需要 32 位得换 32 位 Python 重打 |
| **不用装 Python** | 这正是打包的意义——科室电脑无需 Python、pip 或任何依赖 |
| **数据仍在本地** | 配置（YAML）与排班（CSV）是普通文件；程序只监听 127.0.0.1，不联网 |
| **进程占用** | 重新打包前先退出正在运行的 medshift.exe，否则 PyInstaller 删旧文件会失败 |
| **OR-Tools 必须打钩子** | 自动排班依赖 OR-Tools，其原生库（`ortools.dll`、`abseil_dll.dll`、`libprotobuf.dll` 等）放在 `ortools/.libs/` 下，**PyInstaller 自动探测认不出**。缺了它们的表现是：exe 能启动，但 `medshift solve` 报「未安装 ortools」。本项目用 `packaging/hooks/hook-ortools.py` 显式收集，并在 spec 的 `hookspath` 指向该目录 |
| **excludes 不能排除 numpy/pandas** | OR-Tools 依赖 numpy 与 pandas，若在 spec 的 `excludes` 里排除它们，冻结后求解器会崩 |
| **体积变大** | v0.2 因内置 OR-Tools，单文件 exe 从约 18 MB 增至约 40 MB，属正常 |

### 重新打包检查清单

1. 确认没有 `medshift.exe` 进程在跑（`netstat -ano | grep :8765` 找 PID → `taskkill`）；
2. `pytest` 全绿；
3. `pyinstaller packaging/medshift.spec --noconfirm --clean`；
4. **实测求解**（这一步最容易漏，也是 OR-Tools 打包问题的唯一验证手段）：
   ```bash
   dist\medshift.exe solve -c examples\radiology --week-start 2026-11-02 --dry-run
   ```
   看到「求解成功：OPTIMAL」才算打包成功；
5. 需要安装包时再跑 `ISCC.exe packaging\medshift.iss`。
