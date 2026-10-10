# 安装指南

本文说明 **medshift v0.1** 的安装前提、详细步骤与安装验证方法。
全部命令均在 Python 3.13 + Windows 上实测通过（同一套步骤适用于 macOS / Linux）。

---

## 一、安装前提条件

### 1.1 必需环境

| 项目 | 要求 | 说明 |
|---|---|---|
| Python | **>= 3.10** | 支持 3.10 / 3.11 / 3.12 / 3.13；实测 3.13.12 |
| pip | 随 Python 自带 | 建议先 `python -m pip install --upgrade pip` |
| 操作系统 | Windows / macOS / Linux | 纯 Python 实现，无平台相关代码 |
| 网络 | 可访问 PyPI | 用于下载依赖包 |
| Git | 仅"从 GitHub 克隆"时需要 | 下载源码压缩包则不需要 |

检查 Python 版本：

```bash
python --version          # 需 >= 3.10
# 若系统只装了 py 启动器，可用：py -0  列出已装版本
```

### 1.2 不需要具备

- **不需要数据库**：配置与排班数据都是纯文本文件（YAML / CSV），没有服务端。
- **不需要 Docker、不需要 GPU**。
- **不需要预装 Office**：导出 `.xlsx` 用的是纯 Python 的 openpyxl，不调用 Excel。
- **v0.1 不需要 OR-Tools**：CP-SAT 求解器是 v0.2 的内容，作为可选依赖单独提供。

### 1.3 依赖清单（安装时自动拉取）

**运行时依赖**（`dependencies`）：

| 包 | 版本 | 用途 |
|---|---|---|
| pydantic | >= 2.5 | 数据模型定义与字段校验 |
| PyYAML | >= 6.0 | 读取 YAML 配置 |
| openpyxl | >= 3.1 | 导出 Excel 周表 |
| typer | >= 0.9 | 命令行入口 |

**开发/测试依赖**（`optional-dependencies.dev`）：

| 包 | 版本 | 用途 |
|---|---|---|
| pytest | >= 7.4 | 测试框架 |
| pytest-cov | >= 4.1 | 覆盖率统计 |
| ruff | >= 0.4 | 静态检查与格式化 |

**可选依赖**（`optional-dependencies.solver`，v0.2 求解器使用）：

| 包 | 版本 | 用途 |
|---|---|---|
| ortools | >= 9.8 | CP-SAT 约束求解 |

---

## 二、安装步骤

### 方式 A：从 GitHub 克隆（首次使用者推荐）

```bash
git clone https://github.com/yyjr2026/medshift.git
cd medshift
```

### 方式 B：使用本地源码 / 解压后的压缩包

```bash
cd <源码所在路径>/medshift
```

> 方式 A、B 拿到源码后，以下步骤完全一致。

### 第 1 步：创建虚拟环境

```bash
python -m venv .venv
```

**为什么要建虚拟环境**：把 medshift 的依赖（pydantic、openpyxl 等）装进独立目录，
不污染系统 Python，也避免与其他项目的版本互相冲突。卸载时删掉 `.venv/` 即干净。

### 第 2 步：激活虚拟环境

```bash
# Windows — Git Bash / cmd
.venv\Scripts\activate

# Windows — PowerShell
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

激活成功后，命令行提示符前会出现 `(.venv)`。

> **PowerShell 报"禁止运行脚本"**：当前会话临时放开即可 —
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`，或改用 `.venv\Scripts\activate.bat`。

### 第 3 步：安装项目

```bash
pip install -e ".[dev]"
```

三个参数的含义：

- `-e`（editable，可编辑安装）：以"链接"方式安装，源码改动立即生效，**无需重装**，
  适合后续按本科室情况改代码或调试；
- `.`：从当前目录安装；
- `[dev]`：额外安装测试与代码检查工具。**只使用功能**可省略，改为 `pip install -e .`。

> 若 `pip` 命令不可用，等价写法：`python -m pip install -e ".[dev]"`。

### 方式 C：只当命令行工具用（pipx 全局隔离安装）

不想管虚拟环境、只想随时敲 `medshift` 命令：

```bash
pipx install "medshift[dev] @ git+https://github.com/yyjr2026/medshift.git"
```

> 该方式安装的是快照，不随源码更新；需要"改代码立即生效"仍请用方式 A/B。

---

## 三、验证安装是否成功

按顺序做下面几步，全部通过即安装成功。

### 第 0 步：确认命令已就绪

```bash
medshift --help
```

能看到 `init / validate / check / export / stats` 子命令列表即为正常。

### 第 1 步：运行测试套件（最可靠的验证）

```bash
pytest -q
```

**期望结果**：`46 passed`（46 个用例全部通过）。出现任何 failed 即为环境异常。

### 第 2 步：校验示例科室配置

```bash
medshift validate -c examples/radiology
```

**期望输出**：

```
配置合法：示例医院放射科
  人员 25 人（可排班 23、进修实习 1、离岗 1）
  班次 16 个｜岗位 12 个｜节假日 33 天
```

### 第 3 步：校验排班数据

```bash
medshift check -c examples/radiology -a examples/radiology/assignments/2026-W42.csv
```

**期望输出**：`校验通过：未发现任何问题。`

### 第 4 步：导出一份 Excel

```bash
medshift export -c examples/radiology -a examples/radiology/assignments/2026-W42.csv -o out/2026-W42.xlsx
```

**期望输出**：`已导出：out/2026-W42.xlsx`，并提示记录条数。用 Excel 打开可看到
"排班矩阵 + 岗位配置 + 统计"三张表。

### 第 5 步：查看统计

```bash
medshift stats -c examples/radiology -a examples/radiology/assignments/2026-W42.csv
```

**期望输出**：一张按人汇总的表（姓名 / 组别 / 出勤 / 休息 / 夜班 / 值出 / 加权分）。

### 附加：Python API 冒烟测试

在已激活环境的 Python 中：

```python
from medshift import Scheduler

scheduler = Scheduler.from_config_dir("examples/radiology")
items = scheduler.load_assignments("examples/radiology/assignments/2026-W42.csv")

print(scheduler.check(items).ok)          # True 表示无违规
print(len(scheduler.stats(items)))        # 参与排班的人数
```

### 一条命令跑完所有验证

```bash
medshift --help && pytest -q && medshift validate -c examples/radiology && medshift check -c examples/radiology -a examples/radiology/assignments/2026-W42.csv
```

---

## 四、常见问题

**Q1：Windows 下中文输出乱码或报 `UnicodeEncodeError`**
先设编码再运行：

```bash
export PYTHONIOENCODING=utf-8     # Git Bash
set PYTHONIOENCODING=utf-8        # cmd
$env:PYTHONIOENCODING="utf-8"     # PowerShell
```

或把终端切到 UTF-8：`chcp 65001`。

**Q2：提示 `medshift: command not found`**
多数是虚拟环境未激活。确认提示符有 `(.venv)`；仍不行可用模块方式兜底：
`python -m medshift.cli --help`。

**Q3：YAML 里写的 `OFF` 怎么变成布尔值了？**
这是 YAML 1.1 的历史包袱（`OFF/ON/YES/NO` 被当布尔）。v0.1 已在配置加载器里
做了处理（只认 `true/false`），按项目模板写无需担心；若自己另写 YAML，
给 `OFF` 加引号写成 `"OFF"` 亦可。

**Q4：需要单独安装 OR-Tools 吗？**
不需要。OR-Tools 是 medshift 的核心依赖，`pip install -e ".[dev]"` 时会自动装好。
若只想要最小运行时，也可 `pip install ortools` 单独补齐。

**Q5：怎么卸载？**
退出虚拟环境后直接删除 `.venv/` 目录即可，不留任何系统残留。

---

## 五、下一步

安装验证通过后，参见：

- [`README.md`](../README.md) —— 快速开始与命令说明
- [`docs/configuration.md`](configuration.md) —— 五份 YAML 配置的字段逐项说明
- `medshift init my-dept` —— 生成一份可改的配置骨架，开始按本科室情况填写
