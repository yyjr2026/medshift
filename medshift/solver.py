"""CP-SAT 自动排班求解器（v0.2）。

把「一周排班」建模成约束满足 + 目标优化问题，用 OR-Tools 的 CP-SAT 求解。

模型总览
--------
**决策变量**

* ``x[p, d, s]`` —— 人员 p 在第 d 天上 s 班（布尔）
* ``y[p, d, pos]`` —— 人员 p 在第 d 天占住岗位 pos（布尔）
* ``off[p, d]`` —— 人员 p 在第 d 天休息（布尔，由 x 推导）

**硬约束**（必须满足，否则无解）

1. 每人每天至多一个班次；
2. 每个**必排**岗位每天凑够 ``daily_need`` 人；
3. 占岗者须具备该岗位所需技能、且属于该岗位指定的组别；
4. 非在岗人员（派驻／长期假／规培）不排班；进修实习人员不占岗；
5. 夜班只排给 ``night_eligible`` 的人；
6. 值班次日必须排联动班次（值出），当日不再排其它班次；
7. 连续出勤不超过 ``max_consecutive_work_days``；
8. 每天每组必须留够覆盖岗位需求的人（``max_off_per_day`` 只作物理上界，
   即该组休息人数不得超过「组内人数 − 当日岗位总需求」）。

**软约束 / 目标**（分层加权，量级拉开以保证优先级）

1. 首要（权重最大）：每人不低于 ``min_off_per_week`` 天休息（至少休一天）；
2. 次要：每人尽量达到 ``target_off_per_week``（尽量休两天）；
3. 再次：夜间人员的休息天数也要向 target 靠拢；
4. 再次：``max_off_per_day`` 尽量不被突破（均衡地摊开休息）；
5. 再次：夜班在符合条件的人之间尽量均衡；
6. 最后：可选岗位（MR审／DR审）有人力富余时尽量排满。

> 关键设计：``max_off_per_day`` **不是硬约束**。真实的排班需求是
> 「尽量休两天，人手不够就休一天」，因此它只是一种偏好。若把它当硬约束，
> 当「日岗位需求 + 值班 + 值出」已经占满人力时，模型会立刻无解。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .models import Assignment, DeptConfig, Shift, ShiftKind, Staff

try:  # pragma: no cover - 依赖可选
    from ortools.sat.python import cp_model
except ImportError:  # pragma: no cover
    cp_model = None  # type: ignore[assignment]


__all__ = ["SolveResult", "Solver", "SolverUnavailableError", "solve_week"]


# 目标函数各分层的权重。刻意用数量级拉开差距：
# 「离 min 的缺口」（至少休一天）> 「离 target 的缺口」（尽量休两天）
# > 「突破 max_off_per_day 的次数」> 「夜班均衡」> 「可选岗位」。
W_MIN_SHORTFALL = 1_000_000
W_TARGET_SHORTFALL = 100_000
W_OFF_QUOTA_OVER = 10_000
W_NIGHT_IMBALANCE = 100
W_OPTIONAL_FILLED = 10
W_WEEKEND_UNFAIR = 50
W_ROTATION = 1


class SolverUnavailableError(RuntimeError):
    """未安装 ortools 时抛出。"""


@dataclass
class SolveResult:
    """求解结果。"""

    assignments: list[Assignment] = field(default_factory=list)
    status: str = "UNKNOWN"
    objective: float = 0.0
    off_by_staff: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in ("OPTIMAL", "FEASIBLE")


class _Context:
    """求解过程共享的中间状态。"""

    def __init__(
        self,
        config: DeptConfig,
        dates: list[dt.date],
        fixed: list[Assignment],
    ) -> None:
        self.config = config
        self.rules = config.rules
        self.dates = dates
        self.fixed = fixed

        # 参与排班的人：在岗且非进修实习
        self.people: list[Staff] = [s for s in config.staff if s.can_hold_position]
        self.by_id: dict[str, Staff] = {s.id: s for s in self.people}

        self.shifts: list[Shift] = list(config.shifts)
        self.shift_by_code: dict[str, Shift] = {s.code: s for s in self.shifts}
        # 不参与自动分配的班次：休息、值出（由值班推导）、其他（如派驻）
        self.schedulable: list[Shift] = [
            s
            for s in self.shifts
            if s.kind in (ShiftKind.DAY, ShiftKind.NIGHT, ShiftKind.EVENING, ShiftKind.BACKUP)
        ]

        self.positions: list = [p for p in config.positions if p.daily_need > 0]
        self.required_positions = [p for p in self.positions if p.is_required]
        self.optional_positions = [p for p in self.positions if p.is_optional]

        self.x: dict[tuple[str, dt.date, str], object] = {}
        self.y: dict[tuple[str, dt.date, str], object] = {}
        self.off_var: dict[tuple[str, dt.date], object] = {}
        self.work_var: dict[tuple[str, dt.date], object] = {}
        self.night_var: dict[tuple[str, dt.date], object] = {}
        # 值出：前一天值了夜班，当天休息性上班（不占岗位）
        self.post_duty_var: dict[tuple[str, dt.date], object] = {}
        # 固定（不参与求解）的格子
        self.fixed_cells: dict[tuple[str, dt.date], str] = {
            (a.staff_id, a.date): a.shift_code for a in fixed
        }

        # 每个岗位的候选人员（技能匹配 + 组别匹配）
        self._candidates: dict[str, list[Staff]] = {}
        for position in self.positions:
            self._candidates[position.id] = [
                p
                for p in self.people
                if p.can_take(*position.required_skills)
                and (position.group is None or p.group is position.group)
            ]

        # 每组每天的最低在岗人数（= 该组必排岗位的 daily_need 合计）
        self._group_demand: dict[str, int] = {}
        for position in self.required_positions:
            if position.group is None:
                continue
            self._group_demand[position.group.value] = (
                self._group_demand.get(position.group.value, 0)
                + position.daily_need
            )

    # ---------- 查询辅助 ----------

    def group_daily_demand(self, group: str) -> int:
        """某组每天必须留出的在岗人数（覆盖必排岗位）。

        只统计「岗位」本身的 ``daily_need``。夜班次日值出所占用的人力
        由 ``_constrain_night_follow`` 在班次层面处理，不在这里重复计入，
        否则会人为把上界压得过低，导致明明排得出来却判无解。
        """
        total = 0
        for position in self.required_positions:
            if position.group is None or position.group.value != group:
                continue
            total += position.daily_need
        return total

    def candidates(self, position) -> list[Staff]:
        return self._candidates.get(position.id, [])

    def can_work(self, person: Staff, shift_code: str) -> bool:
        """该人能否上该班次（技能 / 夜班资格 / 是否可排班）。"""
        shift = self.shift_by_code.get(shift_code)
        if shift is None or shift.kind is ShiftKind.OFF:
            return False
        if shift.kind is ShiftKind.POST_NIGHT:
            return False  # 由值班联动推导，不单独决策
        if shift.kind is ShiftKind.OTHER:
            return False
        if shift.kind is ShiftKind.NIGHT and not person.night_eligible:
            return False
        if (person.id, shift_code) in self._deny():
            return False
        return True

    def _deny(self) -> set[tuple[str, str]]:
        return getattr(self, "_deny_cache", set())

    def set_deny(self, pairs: set[tuple[str, str]]) -> None:
        """记录被岗位技能约束排除的 (人员, 班次) 组合。"""
        self._deny_cache = pairs


class Solver:
    """一周排班求解器。"""

    def __init__(self, config: DeptConfig) -> None:
        self.config = config
        self.rules = config.rules

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    def solve_week(
        self,
        week_start: dt.date,
        *,
        days: int = 7,
        time_limit_s: int | None = None,
        seed: int = 0,
        fixed: list[Assignment] | None = None,
    ) -> SolveResult:
        """求解从 ``week_start`` 起 ``days`` 天（默认一周）的排班。"""
        if cp_model is None:
            raise SolverUnavailableError(
                "未安装 ortools，无法使用自动排班。请先安装：\n"
                '    pip install "medshift[solver]"\n'
                "（打包版 exe 已内置，无需单独安装。）"
            )

        dates = [week_start + dt.timedelta(days=i) for i in range(days)]
        model = cp_model.CpModel()
        ctx = _Context(self.config, dates, fixed or [])

        self._build_variables(model, ctx)
        self._add_hard_constraints(model, ctx)
        objective_terms = self._add_soft_constraints(model, ctx)
        model.Minimize(sum(objective_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(
            time_limit_s or self.rules.solve_time_limit_s
        )
        solver.parameters.random_seed = seed
        solver.parameters.num_search_workers = 8

        status = solver.Solve(model)
        status_name = solver.StatusName(status)

        result = SolveResult(status=status_name)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            result.warnings.append(
                "在当前约束下未找到可行解，可能是人力不足或约束过紧。"
            )
            if status == cp_model.INFEASIBLE:
                result.warnings.append(
                    "问题被判定为无解（INFEASIBLE）——请检查各组人数是否低于"
                    "每日岗位总需求，或每日休息上限是否过小。"
                )
            return result

        result.objective = float(solver.ObjectiveValue())
        result.assignments = self._extract(solver, ctx)
        result.off_by_staff = {
            p.id: sum(
                1
                for d in dates
                if solver.Value(ctx.off_var[(p.id, d)]) == 1
            )
            for p in ctx.people
        }
        result.stats = self._collect_stats(solver, ctx, result)
        return result

    # ------------------------------------------------------------------
    # 建模：变量
    # ------------------------------------------------------------------

    def _build_variables(self, model, ctx: _Context) -> None:
        for person in ctx.people:
            for day in ctx.dates:
                for shift in ctx.schedulable:
                    if not ctx.can_work(person, shift.code):
                        continue
                    ctx.x[(person.id, day, shift.code)] = model.NewBoolVar(
                        f"x_{person.id}_{day:%m%d}_{shift.code}"
                    )
                # 休息 / 出勤汇总变量
                ctx.off_var[(person.id, day)] = model.NewBoolVar(
                    f"off_{person.id}_{day:%m%d}"
                )
                ctx.work_var[(person.id, day)] = model.NewBoolVar(
                    f"work_{person.id}_{day:%m%d}"
                )
                ctx.night_var[(person.id, day)] = model.NewBoolVar(
                    f"night_{person.id}_{day:%m%d}"
                )
                ctx.post_duty_var[(person.id, day)] = model.NewBoolVar(
                    f"post_{person.id}_{day:%m%d}"
                )

        for position in ctx.positions:
            for day in ctx.dates:
                for person in ctx.candidates(position):
                    ctx.y[(person.id, day, position.id)] = model.NewBoolVar(
                        f"y_{person.id}_{day:%m%d}_{position.id}"
                    )

    # ------------------------------------------------------------------
    # 建模：硬约束
    # ------------------------------------------------------------------

    def _add_hard_constraints(self, model, ctx: _Context) -> None:
        self._constrain_one_shift_per_day(model, ctx)
        self._constrain_position_staffing(model, ctx)
        self._constrain_skills(model, ctx)
        self._constrain_night_follow(model, ctx)
        self._constrain_off_quota(model, ctx)
        self._constrain_consecutive_work(model, ctx)
        self._constrain_fixed(model, ctx)

    def _constrain_one_shift_per_day(self, model, ctx: _Context) -> None:
        """每人每天至多一个班次，并据此定义出勤/休息/夜班/值出汇总变量。

        ``work_var`` 的定义很关键：它必须包含「值出」这种**不占岗位但在上班**
        的状态，否则值班次日会出现「work_var 被强制为 1、但所有班次变量为 0」
        的矛盾，模型直接无解。
        """
        for person in ctx.people:
            for day in ctx.dates:
                day_shifts = [
                    ctx.x[(person.id, day, s.code)]
                    for s in ctx.schedulable
                    if (person.id, day, s.code) in ctx.x
                ]

                # 已被固定的人：工作日以固定格子为准
                fixed_code = ctx.fixed_cells.get((person.id, day))
                post = ctx.post_duty_var[(person.id, day)]

                if day_shifts:
                    model.Add(sum(day_shifts) <= 1)
                    work_terms = day_shifts
                else:
                    work_terms = []

                if fixed_code:
                    shift = ctx.shift_by_code.get(fixed_code)
                    # 固定为非休息班次 → 当天算作出勤
                    if shift is not None and shift.kind is not ShiftKind.OFF:
                        model.Add(ctx.work_var[(person.id, day)] == 1)
                        model.Add(ctx.off_var[(person.id, day)] == 0)
                        model.Add(post == 0)
                        if shift.kind is ShiftKind.NIGHT:
                            model.Add(ctx.night_var[(person.id, day)] == 1)
                        else:
                            model.Add(ctx.night_var[(person.id, day)] == 0)
                        continue

                # 出勤 = 上了某个班次 或 处于值出日
                if work_terms:
                    model.Add(
                        ctx.work_var[(person.id, day)]
                        == sum(work_terms) + post
                    )
                else:
                    model.Add(ctx.work_var[(person.id, day)] == post)
                model.Add(
                    ctx.off_var[(person.id, day)]
                    == 1 - ctx.work_var[(person.id, day)]
                )

                night_terms = [
                    ctx.x[(person.id, day, s.code)]
                    for s in ctx.schedulable
                    if s.kind is ShiftKind.NIGHT
                    and (person.id, day, s.code) in ctx.x
                ]
                if night_terms:
                    model.Add(ctx.night_var[(person.id, day)] == sum(night_terms))
                else:
                    model.Add(ctx.night_var[(person.id, day)] == 0)

    def _constrain_position_staffing(self, model, ctx: _Context) -> None:
        """必排岗位每天凑够人数；岗位人数合计不超过当天出勤人数。"""
        for day in ctx.dates:
            # 每个岗位：当天被占用的次数 = daily_need
            for position in ctx.required_positions:
                vars_ = [
                    ctx.y[(p.id, day, position.id)]
                    for p in ctx.candidates(position)
                    if (p.id, day, position.id) in ctx.y
                ]
                model.Add(sum(vars_) >= position.daily_need)

            # 可选岗位：至多 daily_need（能排就排，由目标函数驱动）
            for position in ctx.optional_positions:
                vars_ = [
                    ctx.y[(p.id, day, position.id)]
                    for p in ctx.candidates(position)
                    if (p.id, day, position.id) in ctx.y
                ]
                model.Add(sum(vars_) <= position.daily_need)

            # 一个人当天至多占一个岗位
            for person in ctx.people:
                own = [
                    ctx.y[(person.id, day, pos.id)]
                    for pos in ctx.positions
                    if (person.id, day, pos.id) in ctx.y
                ]
                if own:
                    model.Add(sum(own) <= 1)
                # 占岗 ⇒ 当天出勤
                if own:
                    model.Add(sum(own) <= ctx.work_var[(person.id, day)])

    def _constrain_skills(self, model, ctx: _Context) -> None:
        """占岗 ⇔ 同期上对应班次（把岗位变量与班次变量绑在一起）。

        只需 ``y[p,d,pos] ⇒ x[p,d,pos.shift_code]`` 这一个方向：
        岗位需求由 ``_constrain_position_staffing`` 保证，
        而占岗一定意味着当天上这个班。**不能**反过来要求
        「上某班次的人 ≥ 岗位需求」——那会把通用班次（如「正班」）
        和夜班（值出占用次日）逼进死路，正是此前的无解根因。
        """
        for position in ctx.positions:
            for day in ctx.dates:
                for person in ctx.candidates(position):
                    y = ctx.y.get((person.id, day, position.id))
                    if y is None:
                        continue
                    x = ctx.x.get((person.id, day, position.shift_code))
                    if x is None:
                        # 该人无法上该班次 → 不能占这个岗
                        model.Add(y == 0)
                    else:
                        model.Add(y <= x)

    def _constrain_night_follow(self, model, ctx: _Context) -> None:
        """值班次日必须有值出（或该值班声明的联动班次）。

        做法：若某人当天值了夜班，则

        1. 次日不得再排任何班次（``x == 0``）；
        2. 次日置为**值出日**（``post_duty_var == 1``）——这天算上班、
           不占岗位，并由提取阶段写入联动班次（默认 ``POST_DUTY``）。

        值出是**推导**出来的状态，不能凭空出现，因此对每个人都加一条
        「值出 ⇒ 前一天值夜班」的约束。这条约束必须对所有人生效，
        否则不具备夜班资格的人（如护士）会被求解器塞进值出状态。
        """
        for person in ctx.people:
            eligible = person.night_eligible
            for i, day in enumerate(ctx.dates):
                # ---- 反向：值出日的头一天必须是夜班 ----
                # 若该人根本不能值夜班（或当天是周期首日没有前一天），
                # 则其值出变量恒为 0。
                if i == 0 or not eligible:
                    model.Add(ctx.post_duty_var[(person.id, day)] == 0)
                else:
                    prev_day = ctx.dates[i - 1]
                    prev_night = ctx.night_var[(person.id, prev_day)]
                    model.Add(ctx.post_duty_var[(person.id, day)] <= prev_night)

                if not eligible or i + 1 >= len(ctx.dates):
                    continue  # 周期末日的次日在下一周文件里，本周期不判定

                # ---- 正向：今晚值夜班 ⇒ 明天值出 ----
                has_night = ctx.night_var[(person.id, day)]
                next_day = ctx.dates[i + 1]
                model.Add(
                    ctx.post_duty_var[(person.id, next_day)] == 1
                ).OnlyEnforceIf(has_night)
                # 次日不得再排任何班次（值出不占可排班次）
                for s in ctx.schedulable:
                    var = ctx.x.get((person.id, next_day, s.code))
                    if var is not None:
                        model.Add(var == 0).OnlyEnforceIf(has_night)

    def _constrain_off_quota(self, model, ctx: _Context) -> None:
        """休息人数的**物理上界**（硬约束）。

        ``max_off_per_day`` 本身是软偏好，在目标函数里罚；这里只加一条
        绝不能越过的红线：当天该组休息人数不得超过
        「组内人数 − 当天该组岗位总需求」。

        这样既保证了岗位一定排得出来（值出占用的人力已计入需求），
        又不会像以前那样把 ``max_off_per_day`` 当硬约束导致无解。
        """
        for day in ctx.dates:
            by_group: dict[str, list] = {}
            for person in ctx.people:
                by_group.setdefault(person.group.value, []).append(
                    ctx.off_var[(person.id, day)]
                )
            for group, vars_ in by_group.items():
                headcount = len(vars_)
                need = ctx.group_daily_demand(group)
                # 物理上界：至少留「岗位需求」个人上班
                physical_cap = headcount - need
                if physical_cap < 0:
                    # 人数本身就不够，给 0，让求解器直接判定无解并给出提示
                    physical_cap = 0
                model.Add(sum(vars_) <= physical_cap)

    def _constrain_consecutive_work(self, model, ctx: _Context) -> None:
        """连续出勤天数不超过上限。"""
        limit = ctx.rules.max_consecutive_work_days
        if not limit or limit <= 0:
            return
        n = len(ctx.dates)
        if limit >= n:
            return
        for person in ctx.people:
            work = [ctx.work_var[(person.id, d)] for d in ctx.dates]
            for start in range(0, n - limit):
                window = work[start : start + limit + 1]
                model.Add(sum(window) <= limit)

    def _constrain_fixed(self, model, ctx: _Context) -> None:
        """已被固定的格子（如手工排好的夜班）保持不动。"""
        for (staff_id, day), code in ctx.fixed_cells.items():
            if day not in ctx.dates:
                continue
            shift = ctx.shift_by_code.get(code)
            if shift is None:
                continue
            if shift.kind is ShiftKind.OFF:
                model.Add(ctx.work_var[(staff_id, day)] == 0)
                continue
            # 固定的是可排班次 → 强制该变量为 1
            var = ctx.x.get((staff_id, day, code))
            if var is not None:
                model.Add(var == 1)

    # ------------------------------------------------------------------
    # 建模：软约束 / 目标
    # ------------------------------------------------------------------

    def _add_soft_constraints(self, model, ctx: _Context) -> list:
        terms: list = []
        n_days = len(ctx.dates)
        target = ctx.rules.target_off_per_week
        minimum = ctx.rules.min_off_per_week

        # ---- 1) 休息天数目标（首要 + 次要，权重拉开）----
        for person in ctx.people:
            off_sum = sum(ctx.off_var[(person.id, d)] for d in ctx.dates)

            # 距 minimum 的缺口：权重最大，保证「至少休一天」优先于一切
            if minimum > 0:
                short_min = model.NewIntVar(0, minimum, f"sm_{person.id}")
                model.Add(short_min >= minimum - off_sum)
                terms.append(W_MIN_SHORTFALL * short_min)

            # 距 target 的缺口：每差一天都罚，鼓励尽量休满两天
            if target > 0 and target <= n_days:
                short_target = model.NewIntVar(0, target, f"st_{person.id}")
                model.Add(short_target >= target - off_sum)
                terms.append(W_TARGET_SHORTFALL * short_target)

        # ---- 2) ``max_off_per_day`` 软偏好：超出配额就罚 ----
        # 把休息尽量均匀摊到每天、别都堆在同一天。
        for day in ctx.dates:
            by_group: dict[str, list] = {}
            for person in ctx.people:
                by_group.setdefault(person.group.value, []).append(
                    ctx.off_var[(person.id, day)]
                )
            for group, vars_ in by_group.items():
                quota = ctx.rules.off_quota(group)
                if quota is None:
                    continue
                headcount = len(vars_)
                # 只有当配额确实大于物理下界时，才谈得上「软偏好」，
                # 否则配额本身不可达，不该惩罚。
                need = ctx.group_daily_demand(group)
                if quota >= headcount - need:
                    continue
                over = model.NewIntVar(
                    0, headcount, f"offover_{group}_{day:%m%d}"
                )
                model.Add(over >= sum(vars_) - quota)
                terms.append(W_OFF_QUOTA_OVER * over)

        # ---- 3) 夜班均衡：让每人夜班次数的极差最小 ----
        night_totals = []
        for person in ctx.people:
            if not person.night_eligible:
                continue
            total = sum(ctx.night_var[(person.id, d)] for d in ctx.dates)
            night_totals.append(total)

        if len(night_totals) >= 2:
            max_night = model.NewIntVar(0, n_days, "max_night")
            min_night = model.NewIntVar(0, n_days, "min_night")
            model.AddMaxEquality(max_night, night_totals)
            model.AddMinEquality(min_night, night_totals)
            spread = model.NewIntVar(0, n_days, "night_spread")
            model.Add(spread == max_night - min_night)
            terms.append(W_NIGHT_IMBALANCE * spread)

        # ---- 4) 可选岗位（MR审 / DR审）：有人力就尽量排满 ----
        for position in ctx.optional_positions:
            for day in ctx.dates:
                for person in ctx.candidates(position):
                    y = ctx.y.get((person.id, day, position.id))
                    if y is None:
                        continue
                    # 未排该岗 = 1 - y，作为惩罚项
                    miss = model.NewIntVar(
                        0, 1, f"miss_{person.id}_{day:%m%d}_{position.id}"
                    )
                    model.Add(miss == 1 - y)
                    terms.append(W_OPTIONAL_FILLED * miss)

        return terms

    # ------------------------------------------------------------------
    # 结果提取
    # ------------------------------------------------------------------

    def _extract(self, solver, ctx: _Context) -> list[Assignment]:
        out: list[Assignment] = []

        # 岗位归属：先建索引，便于给班次带上 position_id
        pos_of: dict[tuple[str, dt.date, str], str] = {}
        for (staff_id, day, pos_id), var in ctx.y.items():
            if solver.Value(var) == 1:
                pos_of[(staff_id, day)] = pos_id

        for person in ctx.people:
            for day in ctx.dates:
                # 固定的格子优先
                fixed_code = ctx.fixed_cells.get((person.id, day))
                if fixed_code:
                    shift = ctx.shift_by_code.get(fixed_code)
                    out.append(
                        Assignment(
                            staff_id=person.id,
                            date=day,
                            shift_code=fixed_code,
                            position_id=pos_of.get((person.id, day)),
                        )
                    )
                    continue

                worked = False
                for shift in ctx.schedulable:
                    var = ctx.x.get((person.id, day, shift.code))
                    if var is not None and solver.Value(var) == 1:
                        pos_id = pos_of.get((person.id, day))
                        # 只保留与该班次对应的岗位（避免错配）
                        if pos_id is not None:
                            pos = self.config.position_by_id(pos_id)
                            if pos is None or pos.shift_code != shift.code:
                                pos_id = None
                        out.append(
                            Assignment(
                                staff_id=person.id,
                                date=day,
                                shift_code=shift.code,
                                position_id=pos_id,
                            )
                        )
                        worked = True
                        break

                if not worked:
                    # 未排任何班次：若被标为值出日，则写入值出班次
                    if solver.Value(ctx.post_duty_var[(person.id, day)]) == 1:
                        post = self._post_night_code(ctx)
                        if post:
                            out.append(
                                Assignment(
                                    staff_id=person.id,
                                    date=day,
                                    shift_code=post,
                                )
                            )
                            continue
                    out.append(
                        Assignment(
                            staff_id=person.id,
                            date=day,
                            shift_code=self._off_code(ctx),
                        )
                    )

        out.sort(key=lambda a: (a.date, a.staff_id))
        return out

    @staticmethod
    def _off_code(ctx: _Context) -> str:
        for s in ctx.config.shifts:
            if s.kind is ShiftKind.OFF:
                return s.code
        return "OFF"

    @staticmethod
    def _post_night_code(ctx: _Context) -> str | None:
        for s in ctx.config.shifts:
            if s.kind is ShiftKind.POST_NIGHT:
                return s.code
        return None

    def _collect_stats(self, solver, ctx: _Context, result: SolveResult) -> dict:
        off_counts = list(result.off_by_staff.values()) or [0]
        n_days = len(ctx.dates)
        # 统计每天各组休息人数
        off_by_day_group: dict[str, int] = {}
        for person in ctx.people:
            for day in ctx.dates:
                if solver.Value(ctx.off_var[(person.id, day)]) == 1:
                    key = f"{day.isoformat()} {person.group.value}"
                    off_by_day_group[key] = off_by_day_group.get(key, 0) + 1

        # 可选岗位实际排上几天
        optional_filled: dict[str, int] = {}
        for position in ctx.optional_positions:
            filled = sum(
                1
                for day in ctx.dates
                for person in ctx.candidates(position)
                if (person.id, day, position.id) in ctx.y
                and solver.Value(ctx.y[(person.id, day, position.id)]) == 1
            )
            optional_filled[position.name] = filled

        return {
            "days": n_days,
            "people": len(ctx.people),
            "off_min": min(off_counts),
            "off_max": max(off_counts),
            "off_total": sum(off_counts),
            "optional_filled": optional_filled,
            "off_by_day_group": off_by_day_group,
        }


def solve_week(
    config: DeptConfig,
    week_start: dt.date,
    **kwargs,
) -> SolveResult:
    """便捷函数：等价于 ``Solver(config).solve_week(week_start, **kwargs)``。"""
    return Solver(config).solve_week(week_start, **kwargs)
