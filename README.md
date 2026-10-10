# medshift · 医技科室排班器

> 用一套声明式 YAML 描述「人员、班次、岗位、规则」，  
> 让「每天谁在哪个岗位、谁值班、谁休息」变得**可校验、可导出、可复现**。

面向放射科、超声科、检验科、病理科、内镜中心等**多岗位 + 值班制**的医院科室。  
当前版本 **v0.1**（Alpha）：配置校验 + 排班检查 + Excel 出表 + 统计汇总。  
自动求解（CP-SAT）在 v0.2。

---

## 它解决什么

| 痛点                              | medshift 的做法                                |
| ------------------------------- | ------------------------------------------- |
| 岗位多（10+ 个）、约束多（值班必须配值出、每天休息有上限） | 全部写进 `rules.yaml` / `positions.yaml`，机器逐条核对 |
| 手工 Excel 排一周要 1—2 小时，改一处牵动全身    | 配置与数据分离，改完立刻 `check` 出问题清单                  |
| 夜班、节假日公平性靠人脑记，容易有争议             | `stats` 一键出夜班次数、休息天数、加权分                    |
| 出表格式依赖个人习惯                      | 导出结构固定的 Excel 周表（矩阵 + 岗位配置 + 统计）            |

---

## 快速开始

### 1. 安装

```bash
git clone https://github.com/your-org/medshift.git
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
  人员 25 人（可排班 23、进修实习 1、离岗 1）
  班次 16 个｜岗位 12 个｜节假日 33 天
```

### 5. 检查排班数据并出表

排班数据用 CSV 描述（v0.1 由人工在 Excel 里排好后导出）：

```csv
staff_id,date,shift_code,position_id,tags
D01,2026-10-12,DUTY_DIAG,DUTY_DIAG,
D02,2026-10-12,CT_DIAG,CT_DIAG,
D07,2026-10-12,OFF,,
```

```bash
medshift check  -c my-dept -a my-dept/assignments/2026-W42.csv --verbose
medshift export -c my-dept -a my-dept/assignments/2026-W42.csv -o 2026-W42.xlsx
medshift stats  -c my-dept -a my-dept/assignments/2026-W42.csv
```

```
校验通过：未发现任何问题。
已导出：2026-W42.xlsx
  共 161 条排班记录
```

`check` 发现问题时以退出码 1 结束、逐条列出，方便接进 CI。

---

## 图形界面（浏览器排班）

不想敲命令行，可以直接打开本地网页界面：

```bash
pip install "medshift[gui]"
medshift gui -c my-dept          # 浏览器自动打开 http://127.0.0.1:8765/
```

点格子选班次、改完自动校验、右侧看统计、一键导出 Excel。  
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
| `OFF_QUOTA_EXCEEDED`    | error   | 某组某天休息人数超上限    |
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

scheduler.export_excel(items, "2026-W42.xlsx")
for row in scheduler.stats(items):
    print(row.name, row.work_days, row.night_count, row.weighted_score)
```

---

## 项目结构

```
medshift/
├── medshift/
│   ├── models/          # 数据模型：Staff / Shift / Position / Assignment / Rules / Calendar
│   ├── config_loader.py # YAML → DeptConfig，含交叉引用校验
│   ├── validator.py     # 排班校验器（v0.1 核心）
│   ├── scheduler.py     # 门面：加载 → 校验 → 统计 → 导出
│   ├── stats.py         # 统计口径的唯一实现
│   ├── gui/             # 图形界面：Flask 应用 + 页面模板 + 静态资源
│   ├── exporters/       # CSV 读写 + Excel 周表导出
│   └── cli.py           # 命令行入口
├── examples/radiology/  # 可直接运行的脱敏示例（含一整周排班数据）
├── tools/               # 示例数据生成器、开发辅助脚本
├── docs/                # 配置字段说明
└── tests/               # pytest，46 个用例
```

---

## 核心接口

| 对象                                           | 说明                                    |
| -------------------------------------------- | ------------------------------------- |
| `load_config(dir) -> DeptConfig`             | 加载并校验配置，失败抛 `ConfigError`             |
| `Scheduler.from_config_dir(dir)`             | 构造排班器                                 |
| `Scheduler.load_assignments(path)`           | 读取 CSV 排班数据                           |
| `Scheduler.check(items) -> ValidationReport` | 执行全部硬约束校验                             |
| `Scheduler.stats(items) -> list[StaffStat]`  | 按人汇总                                  |
| `Scheduler.export_excel(items, out)`         | 导出 Excel 周表                           |
| `Scheduler.solve(week_start)`                | **v0.2**：自动求解，当前抛 `NotSupportedError` |

---

## 示例科室

`examples/radiology/` 是一份可直接运行的配置：

- 诊断组 9 人、技术组 12 人、护理组 2 人，另有 1 名进修医师（随带教，不占岗）、1 名派驻介入导管室人员
- 每日岗位：诊断 6 个（CT诊断×2、DR诊断、MR诊断、审CT、诊断值班）、技术 7 个（CT1扫描、CT2扫描、MR扫描、DR投照×2、CT值班、DR值班）、登记 1 个
- 值班与值出显式联动：`follow_shift: POST_DUTY`
- 一整周 161 条排班数据，**校验零违规**

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
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\medshift.iss   # 再产出 dist/medshift-0.1.0-setup.exe
```

两种形态都已实测产出：**免安装单文件 exe** 与 **中文向导安装包**（免管理员权限、可卸载）。
目标机器无需安装 Python。**双击 exe 或安装后的快捷方式，直接打开图形界面**；
带参数运行则为命令行。完整说明见 **[docs/windows-packaging.md](docs/windows-packaging.md)**。

---

## Roadmap

| 版本         | 内容                                                |
| ---------- | ------------------------------------------------- |
| **v0.1** ✅ | 数据模型、配置校验、排班校验、Excel 导出、统计                        |
| **v0.2**   | OR-Tools CP-SAT 自动求解（岗位配额、值班值出、休息上限、夜班均衡）         |
| **v0.3**   | 公平性引擎（除夕／中秋轮值）、调班助手、ICS 日历导出                      |
| **v0.4**   | Web 排班板 —— ✅ **本地网页版已完成**（点选排班、实时校验、统计、导出）；拖拽调班待做 |
| **v1.0**   | 多科室模板（超声／检验／内镜）、完善文档                              |

---

## 免责声明

本工具是**排班辅助工具**，输出结果仅供参考，最终排班须由科室负责人审核确认。  
本项目不处理患者数据，也不承担任何医疗责任。

## 许可

[MIT](LICENSE)
