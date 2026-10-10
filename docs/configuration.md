# 配置字段说明

一个科室的配置是一个目录，含 5 个文件：

```
my-dept/
├── dept.yaml         # 科室名（可选）
├── staff.yaml        # 人员名册
├── shifts.yaml       # 班次字典
├── positions.yaml    # 岗位需求
├── rules.yaml        # 排班规则
└── calendar.yaml     # 节假日（可选）
```

每个文件既可以写裸列表／裸字典，也可以带顶层键（`staff:` / `shifts:` / `positions:`）。

---

## dept.yaml

```yaml
name: 某某医院放射科
description: 说明文字（可选）
```

## staff.yaml

```yaml
staff:
  - id: D01                    # 唯一编号，排班数据引用它
    name: 医师1                # 显示名
    group: diagnosis           # diagnosis / technician / nursing / other
    title: 主任医师            # 职称，自由文本
    skills: [CT_DIAG, MR_DIAG] # 技能标签，对应 positions.required_skills
    night_eligible: true       # 是否参与夜班轮值
    rotation_offset: 0         # 整组平移轮岗的偏移量
    status: active             # active / rotated / leave / training
    supervisor_id: null        # 进修、实习人员填写带教老师 id
    note: null                 # 备注，会显示在导出的表上
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ | 全局唯一 |
| `name` | ✅ | —— |
| `group` | | 决定适用哪条每日休息上限 |
| `skills` | | 岗位技能校验依据；留空表示什么岗都能干 |
| `night_eligible` | | 为 `false` 却被排夜班 → 产生 `NIGHT_NOT_ELIGIBLE` 提醒 |
| `status` | | 非 `active` 不参与排班，被排班 → `INACTIVE_STAFF` |
| `supervisor_id` | | 非空即视为进修／实习人员：**不占岗、不参与统计** |

## shifts.yaml

```yaml
shifts:
  - code: DUTY_DIAG            # 班次代码，全局唯一
    name: 诊断值班            # 显示名
    kind: night                # day / night / evening / post_night / backup / off / other
    start: "12:00"             # HH:MM，可留空
    end: "08:00+1"             # "+1" 表示跨夜到次日
    is_night: true             # 是否计入夜班次数
    weight: 3.0                # 加权分（可对接绩效分值）
    color: F8CBAD              # 导出 Excel 的填充色（6 位十六进制）
    follow_shift: POST_DUTY    # 本班次必须在它之后的次日出现
```

**`kind` 的语义**

| kind | 含义 | 计入 |
|---|---|---|
| `day` | 日班 | 出勤 |
| `night` | 值班（含夜间） | 出勤 + 夜班 |
| `evening` | 中晚班，不通宵 | 出勤 |
| `post_night` | 值出（下夜班） | 值出 |
| `backup` | 备班（床边待命） | 出勤 |
| `off` | 休息 | 休息 |
| `other` | 其他状态（如派驻） | 不计 |

> **YAML 坑**：YAML 1.1 会把裸写的 `OFF`、`on`、`yes` 解析成布尔值。
> medshift 的加载器已修正这一点，但为兼容其他工具，建议班次代码统一加引号：`code: "OFF"`。

## positions.yaml

```yaml
positions:
  - id: CT_DIAG
    name: CT诊断
    shift_code: CT_DIAG          # 必须是 shifts.yaml 里存在的代码
    daily_need: 2                # 每天需要的人数，校验配额的依据
    required_skills: [CT_DIAG]   # 胜任条件
    group: diagnosis             # 建议承担的组别，留空表示不限
    priority: 0                  # 数值越大越先被满足（v0.2 求解器用）
```

`daily_need` 为 0 的岗位不参与配额校验（可用于临时停诊）。

## rules.yaml

```yaml
max_off_per_day:        # 【硬约束】每组每天最多几人休息
  diagnosis: 3
  technician: 4
  nursing: 1

min_night_eligible:     # 各组至少几人参与夜班（人力评估用）
  diagnosis: 6
  technician: 8

max_night_per_month: 6        # 【v0.2】每人每月夜班上限
min_rest_gap_h: 12            # 【v0.2】两次值班最小间隔（小时）
max_consecutive_work_days: 6  # 【v0.2】连续出勤上限
night_balance_weight: 10      # 【v0.2】夜班均衡权重
holiday_weight: 2             # 【v0.2】节假日值班加权倍数

rotation:
  technician: weekly          # 【v0.2】技术组按周轮岗
  attach_students: true       # 【v0.2】进修生随带教同格显示
```

> v0.1 只有 `max_off_per_day` 参与校验，其余字段先按管理口径填好，供求解器使用。

## calendar.yaml

```yaml
holidays:                 # 法定节假日
  2026-10-01: 国庆节
  2026-10-02: 国庆节

adjusted_workdays:        # 调休上班日（周末但需正常上班）
  - 2026-09-20
  - 2026-10-10

anchors:                  # 需单独安排值班、并逐年登记轮值的节点
  2026-02-16: 除夕
  2026-09-25: 中秋节
```

日期写法为 `YYYY-MM-DD`，YAML 会自动解析成日期类型。
`anchors` 的标签会覆盖 `holidays` 的标签，并显示在导出表的表头。

---

## 排班数据（assignments CSV）

```csv
staff_id,date,shift_code,position_id,tags
D01,2026-10-12,DUTY_DIAG,DUTY_DIAG,
D02,2026-10-12,CT_DIAG,CT_DIAG,backup|makeup
```

| 列 | 必填 | 说明 |
|---|---|---|
| `staff_id` | ✅ | 对应 `staff.yaml` 的 id |
| `date` | ✅ | `YYYY-MM-DD` |
| `shift_code` | ✅ | 对应 `shifts.yaml` 的 code |
| `position_id` | | 占用的岗位；留空表示不占岗 |
| `tags` | | 叠加状态标记，用 `|` 分隔 |

一人一天只应出现一行（可用 `tags` 表达「休/床边」这类叠加状态）。
