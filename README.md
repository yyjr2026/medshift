# medshift · 医技科室排班器

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776ab.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-133%20passed-brightgreen.svg)](#开发)
[![Status](https://img.shields.io/badge/status-beta-orange.svg)](CHANGELOG.md)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#安装)

> 用一套声明式 YAML 描述「人员、班次、岗位、规则」，  
> 让「每天谁在哪个岗位、谁值班、谁休息」变得**可校验、可导出、可复现**。

面向放射科、超声科、检验科、病理科、内镜中心等**多岗位 + 值班制**的医院科室。  
当前版本 **v0.2**（Beta）：配置校验 + **自动排班（CP-SAT）** + 排班检查 + Excel 出表 + 统计汇总 + 本地图形界面。

**不用装 Python 也能用**：到 [Releases](https://github.com/yyjr2026/medshift/releases) 下载
`medshift-0.2.0-setup.exe`，双击安装，打开即进图形界面。

---

## 它解决什么

| 痛点                              | medshift 的做法                                |
| ------------------------------- | ------------------------------------------- |
| 岗位多（10+ 个）、约束多（值班必须配值出、每天休息有上限） | 全部写进 `rules.yaml` / `positions.yaml`，机器逐条核对 |
| 手工 Excel 排一周要 1—2 小时         | `solve` 一键排出满足全部硬约束的一周，图形界面点一下就行          |
| 改一处牵动全身，容易漏                | 配置与数据分离，改完立刻 `check` 出问题清单                  |
| 夜班、节假日公平性靠人脑记，容易有争议             | 求解器均衡夜班；`stats` 一键出夜班次数、休息天数、加权分            |
| 出表格式依赖个人习惯                      | 导出结构固定的 Excel 周表（矩阵 + 岗位配置 + 统计）            |

---

## 快速开始

### 1. 安装

```bash
git clone https://github.com/yyjr2026/medshift.git
cd medshift
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

> 前提条件（Python ≥ 3.10）、三种安装方式、以及安装后的验证步骤，  
> 详见 **[docs/installation.md](docs/installation.md)**。

### 2. 生成配置骨架

```bash
medshift init my-dept
```

### 3. 按科室实际改配置

编辑 `my-dept/` 下的 5 个 YAML：`staff.yaml`、`shifts.yaml`、`positions.yaml`、  
`rules.yaml`、`calendar.yaml`。字段含义见 [docs/configuration.md](docs/configuration.md)。

### 4. 校验配置

```bash
medshift validate --config my-dept
```

```
配置合法：示例医院放射科
  人员 26 人（可排班 24、进修实习 1、离岗 1）
  班次 18 个｜岗位 15 个｜节假日 33 天
```

### 5. 一键自动排一周（v0.2 新增）

```bash
medshift solve -c my-dept --week-start 2026-11-02
```

```
正在求解 2026-11-02 起 7 天的排班（示例医院放射科，24 名可排班人员）…
求解成功：OPTIMAL（目标值 1101460）
  排班记录 168 条
  每人休息天数：最少 1 天，最多 2 天
  可选岗位：MR审 2 天、DR审 1 天
已写入：my-dept/assignments/2026-W45.csv
```

求解器按各岗位的每日需求排班：

* 护士每天保证**一个登记**、**一个正班**；
* DR 投照每天 **2 名技师**、CT2 每天 **2 名技师**；
* 诊断组人力富余时补排 **MR 审 / DR 审**（可选岗位，人力不够就留空）；
* 每人**尽量休两天**，人手不够时**至少休一天**；
* 值班次日自动配**值出**，夜班在符合条件的人之间均衡分配。

`--dry-run` 只算不落盘；`--days` 可排几天；`--time-limit` 控制求解时限。  
若模型无解，会以退出码 1 结束并说明原因（通常是某组人数少于每日岗位需求）。

### 6. 检查排班数据并出表

```bash
medshift check  -c my-dept -a my-dept/assignments/2026-W45.csv --verbose
medshift export -c my-dept -a my-dept/assignments/2026-W45.csv -o 2026-W45.xlsx
medshift stats  -c my-dept -a my-dept/assignments/2026-W45.csv
```

```
校验通过：未发现任何问题。
已导出：2026-W45.xlsx
  共 168 条排班记录
```

`check` 发现问题时以退出码 1 结束、逐条列出，方便接进 CI。

---

## 图形界面（浏览器排班）

不想敲命令行，可以直接打开本地网页界面：

```bash
pip install -e ".[dev]"
medshift gui -c my-dept          # 浏览器自动打开 http://127.0.0.1:8765/
```

点格子选班次、改完自动校验、右侧看统计、一键导出 Excel。  
工具栏的**「一键排一周」**按钮直接调求解器排好整周，勾选「保留改动」可锁定已手工调整的格子。  
数据仍在本地文件，服务仅监听 `127.0.0.1`。详见 **[docs/gui.md](docs/gui.md)**。

---

## 校验项

| 代码                      | 级别      | 含义             |
| ----------------------- | ------- | -------------- |
| `UNKNOWN_STAFF`         | error   | 排给了配置里不存在的人    |
| `UNKNOWN_SHIFT`         | error   | 使用了未定义的班次代码    |
| `UNKNOWN_POSITION`      | error   | 引用了未定义的岗位      |
| `INACTIVE_STAFF`        | error   | 给规培／产假／派驻人员排了班 |
| `DUPLICATE_ASSIGNMENT`  | error   | 同一人同一天被排了多个班次  |
| `SKILL_MISMATCH`        | error   | 人员技能不满足岗位要求    |
| `POSITION_UNDERSTAFFED` | error   | 某岗位某天人数不足      |
| `OFF_QUOTA_EXCEEDED`    | warning | 某组某天休息人数超出期望上限 |
| `NIGHT_NOT_FOLLOWED`    | error   | 值班次日没有排值出      |
| `GROUP_MISMATCH`        | warning | 人员在非本组岗位       |
| `NIGHT_NOT_ELIGIBLE`    | warning | 未登记参与夜班的人被排了夜班 |

> 单周数据中，周日值班的下夜班自然落在下一周的文件里，因此不作判定。

---

## Python API

```python
from medshift import Scheduler

scheduler = Scheduler.from_config_dir("my-dept")
items = scheduler.load_assignments("my-dept/assignments/2026-W42.csv")

report = scheduler.check(items)
if not report.ok:
    for violation in report.errors:
        print(violation)

scheduler.export_excel(items, "2026-W45.xlsx")
for row in scheduler.stats(items):
    print(row.name, row.work_days, row.night_count, row.weighted_score)
```

自动排一周：

```python
import datetime as dt
from medshift import Scheduler

scheduler = Scheduler.from_config_dir("my-dept")
result = scheduler.solve(dt.date(2026, 11, 2), days=7)
if result.ok:
    print(result.status, len(result.assignments))
    print("每人休息天数：", result.off_by_staff)
    scheduler.save_assignments(result.assignments, "my-dept/assignments/2026-W45.csv")
else:
    print("无解：", result.warnings)
```

也可直接调底层求解器，用 `fixed` 锁定手工排好的格子：

```python
from medshift import load_config
from medshift.models import Assignment
from medshift.solver import Solver

result = Solver(load_config("my-dept")).solve_week(
    dt.date(2026, 11, 2),
    fixed=[Assignment(staff_id="D01", date=dt.date(2026, 11, 4), shift_code="OFF")],
)
```

---

## 项目结构

```
medshift/
├── medshift/
│   ├── models/          # 数据模型：Staff / Shift / Position / Assignment / Rules / Calendar
│   ├── config_loader.py # YAML → DeptConfig，含交叉引用校验
│   ├── validator.py     # 排班校验器
│   ├── solver.py        # CP-SAT 自动排班求解器（v0.2 核心）
│   ├── scheduler.py     # 门面：加载 → 求解／校验 → 统计 → 导出
│   ├── stats.py         # 统计口径的唯一实现
│   ├── gui/             # 图形界面：Flask 应用 + 页面模板 + 静态资源
│   ├── exporters/       # CSV 读写 + Excel 周表导出
│   └── cli.py           # 命令行入口
├── examples/radiology/  # 可直接运行的脱敏示例（含一整周排班数据）
├── tools/               # 示例数据生成器、开发辅助脚本
├── docs/                # 配置字段说明
└── tests/               # pytest，133 个用例
```

---

## 核心接口

| 对象                                           | 说明                                    |
| -------------------------------------------- | ------------------------------------- |
| `load_config(dir) -> DeptConfig`             | 加载并校验配置，失败抛 `ConfigError`             |
| `Scheduler.from_config_dir(dir)`             | 构造排班器                                 |
| `Scheduler.solve(week_start, days=7)`        | **v0.2**：自动求解，返回 `SolveResult`        |
| `Solver(cfg).solve_week(...)`                | 底层求解器，可传 `fixed` 锁定格子                 |
| `Scheduler.save_assignments(items, path)`    | 写出 CSV 排班数据                           |
| `Scheduler.load_assignments(path)`           | 读取 CSV 排班数据                           |
| `Scheduler.check(items) -> ValidationReport` | 执行全部硬约束校验                             |
| `Scheduler.stats(items) -> list[StaffStat]`  | 按人汇总                                  |
| `Scheduler.export_excel(items, out)`         | 导出 Excel 周表                           |

> 自动求解依赖 OR-Tools，已随 `pip install -e ".[dev]"` 一并装好；打包版 exe 亦已内置。

---

## 自动排班模型（v0.2）

**硬约束**（必须满足，否则无解）

1. 每人每天至多一个班次；
2. 每个**必排**岗位每天凑够 `daily_need` 人；
3. 占岗者必须具备该岗位所需技能、且属于该岗位指定的组别；
4. 非在岗人员（派驻／长期假／规培）不排班；进修实习人员不占岗；
5. 夜班只排给 `night_eligible` 的人；
6. 值班次日必须排**值出**（`follow_shift`），当日不再排其它班次；
7. 连续出勤不超过 `max_consecutive_work_days`；
8. 每天每组必须留够覆盖岗位需求的人。

**软目标**（分层加权，优先级从高到低）

1. 每人不低于 `min_off_per_week` 天休息（至少休一天）；
2. 每人尽量达到 `target_off_per_week`（尽量休两天）；
3. `max_off_per_day` 尽量不被突破（休息均衡摊开）；
4. 夜班在符合条件的人之间尽量均衡；
5. 可选岗位（MR 审／DR 审）有人力富余时尽量排满。

> `max_off_per_day` **不是硬约束**。真实需求是「尽量休两天，人手不够就休一天」，
> 若当成硬约束，当「日岗位 + 值班 + 值出」已占满人力时会立刻无解。

---

## 示例科室

`examples/radiology/` 是一份可直接运行的配置：

- 诊断组 9 人、技术组 12 人、护理组 3 人，另有 1 名进修医师（随带教，不占岗）、1 名派驻介入导管室人员
- 每日必排岗位：诊断 6 个（CT诊断×2、DR诊断、MR诊断、审CT、诊断值班），技术 8 个（CT1扫描、CT2扫描×2、MR扫描、DR投照×2、CT值班、DR值班），护理 2 个（登记、护理正班）
- 可选岗位：诊断组的 **MR 审 / DR 审**，人力富余时才排
- 值班与值出显式联动：`follow_shift: POST_DUTY`
- 一整周 168 条排班数据，由求解器生成，**校验零违规**

> 姓名与编号均为虚构占位符。**请勿把真实姓名、工号、患者信息写进配置文件。**

---

## 开发

```bash
pytest -q                    # 运行测试
pytest --cov=medshift        # 覆盖率
ruff check .                 # 静态检查
python tools/generate_example_week.py   # 重新生成示例周数据
```

---

## 打包为 Windows 程序

```bash
pip install pyinstaller
pyinstaller packaging/medshift.spec --noconfirm --clean    # 产出 dist/medshift.exe（约 18 MB）
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\medshift.iss   # 再产出 dist/medshift-0.2.0-setup.exe
```

两种形态都已实测产出：**免安装单文件 exe** 与 **中文向导安装包**（免管理员权限、可卸载）。
目标机器无需安装 Python，OR-Tools 求解器已打进包内。**双击 exe 或安装后的快捷方式，直接打开图形界面**；
带参数运行则为命令行。完整说明见 **[docs/windows-packaging.md](docs/windows-packaging.md)**。

---

## Roadmap

| 版本         | 内容                                                |
| ---------- | ------------------------------------------------- |
| **v0.1** ✅ | 数据模型、配置校验、排班校验、Excel 导出、统计                        |
| **v0.2** ✅ | OR-Tools CP-SAT 自动求解（岗位配额、值班值出、休息目标、夜班均衡、可选审片岗） |
| **v0.3**   | 公平性引擎（除夕／中秋轮值）、调班助手、ICS 日历导出                      |
| **v0.4**   | Web 排班板 —— ✅ **本地网页版已完成**（点选排班、一键排一周、实时校验、统计、导出）；拖拽调班待做 |
| **v1.0**   | 多科室模板（超声／检验／内镜）、完善文档                              |

---

## 免责声明

本工具是**排班辅助工具**，输出结果仅供参考，最终排班须由科室负责人审核确认。  
本项目不处理患者数据，也不承担任何医疗责任。

## 许可

[MIT](LICENSE)
