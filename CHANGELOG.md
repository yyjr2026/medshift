# 更新日志

本文件记录 medshift 的各版本变更，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.2.0] - 2026-10-10

自动排班正式落地：从「手工排 + 机器校验」升级为「机器排 + 人工微调」。

### 新增

- **CP-SAT 自动排班求解器**（`medshift/solver.py`）
  - 基于 OR-Tools CP-SAT，一键排出一周满足全部硬约束的排班表
  - 分层加权目标函数：优先保证岗位最低配置，其次满足期望配置，再优化休息配额、夜班均衡与轮转公平
  - 硬约束：一人一天一班、岗位技能匹配、必需岗位满编、夜班次日值出联动、连续出勤上限
  - 软约束：每人每周休息天数（尽量 2 天，人力不足时 1 天）、夜班次数均衡、可选岗位按人力富余填充
  - 支持「固定格」：已手工调整的排班可作为约束锁定，重排时自动保留
  - 支持求解时限（默认 30 秒）与随机种子
- **CLI 子命令 `medshift solve`**
  - 选项：`--week-start`、`--days`、`--out/-o`、`--time-limit`、`--dry-run`
  - 默认起始日为下一个周一，默认输出到 `assignments/{ISO年}-W{周}.csv`
  - 无解时逐条列出原因并以退出码 1 结束
- **图形界面「一键排一周」按钮**
  - 顶栏一键触发，可设置起始日期、天数、求解时限
  - 勾选「保留改动」即把当前表格中已编辑的格子作为固定约束
  - 求解进度实时显示；无解时给出提示且**不覆盖**现有排班
  - 新增接口 `POST /api/solve`
- **可选岗位机制**（`positions.yaml` 的 `requirement: optional`）
  - 人力富余时才排的岗位（如诊断组的「MR审」「DR审」），人力紧张时不强求
- **示例配置升级为「容县人民医院放射科」口径**
  - 人员 26 人（诊断 9 / 技术 12 / 护理 3 / 进修实习 1 / 离岗 1，均可排班 24 人）
  - 新增班次 `MR_AUDIT`（MR审）、`DR_AUDIT`（DR审）
  - 技术组 `CT2_SCAN` 每日需求调整为 2 人；护理组新增 `NURSE_DAY` 正班
- **新增 46 个测试**：求解器 31 个、GUI 求解接口 9 个、CLI 求解命令 6 个

### 变更

- `rules.yaml` 新增 `target_off_per_week`、`min_off_per_week`、`solve_time_limit_s` 三个字段
- `max_off_per_day` 由硬约束改为**软偏好**（硬上界取「组内人数 − 当日岗位总需求」），避免因人力紧张导致全局无解
- `OFF_QUOTA_EXCEEDED` 由 error 降为 **warning**，与求解器的软处理保持一致
- OR-Tools 与 Flask 由可选依赖提升为**核心依赖**
- 项目状态由 Alpha 提升为 Beta

### 修复

- 修复值出日与「一人一班」约束冲突导致求解必然 INFEASIBLE 的问题（引入独立的 `post_duty` 决策变量）
- 修复技能约束反向推导把通用班次与夜班逼入死路的问题
- 修复非夜班资格人员被错误置为「值出」状态的问题
- 修复 PyInstaller 打包版缺少 OR-Tools 原生库（`ortools/.libs/*.dll`）导致 `solve` 报「未安装 ortools」的问题

### 打包

- `dist/medshift.exe`（免安装版，约 60 MB）与 `dist/medshift-0.2.0-setup.exe`（中文向导安装包，约 61 MB）
- 均内置 OR-Tools 求解引擎，双击即可进图形界面

## [0.1.0] - 2026-09

首个公开版本。

### 新增

- 声明式 YAML 配置：`staff.yaml`、`shifts.yaml`、`positions.yaml`、`rules.yaml`、`calendar.yaml`
- CLI：`init` 生成配置骨架、`validate` 校验配置、`check` 校验排班、`stats` 统计汇总、`export` 导出 Excel、`gui` 启动图形界面
- 排班校验器：一人一天一班、岗位配额、技能匹配、夜班值出联动、连续出勤、休息配额等
- Excel 导出：矩阵周表 + 岗位配置 + 统计三张表
- 本地图形界面（Flask + 原生前端）：表格编辑、实时校验、导出
- 61 个测试用例

[0.2.0]: https://github.com/yyjr2026/medshift/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/yyjr2026/medshift/releases/tag/v0.1.0
