/* medshift 排班器 —— 前端交互（原生 JS，无需构建） */

const $ = (sel) => document.querySelector(sel);

const SHIFT_GROUPS = [
  { kinds: ["day"], label: "出勤" },
  { kinds: ["night"], label: "值班（昼夜连续）" },
  { kinds: ["evening"], label: "中晚班" },
  { kinds: ["backup"], label: "备班" },
  { kinds: ["post_night"], label: "值出（下夜班）" },
  { kinds: ["off"], label: "休息" },
  { kinds: ["other"], label: "其他" },
];

const STATUS_LABELS = { active: "在岗", rotated: "派驻", leave: "长期假", training: "规培" };

const state = {
  config: null,
  files: [],
  currentFile: "",
  days: [],
  weekdayLabels: [],
  assignments: [],
  report: null,
  stats: [],
  dirty: false,
  cells: new Map(),   // "staffId__YYYY-MM-DD" -> {shift_code, position_id, tags}
};

let pickerCtx = null;
let checkTimer = null;
let toastTimer = null;

/* ---------------- 工具 ---------------- */

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function cellKey(staffId, date) { return staffId + "__" + date; }

function splitKey(k) {
  return { staffId: k.slice(0, k.length - 12), date: k.slice(-10) };
}

function shiftByCode(code) {
  return state.config ? state.config.shifts.find((s) => s.code === code) : null;
}

function toast(msg, kind) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast" + (kind ? " " + kind : "");
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
}

/* ---------------- 数据 <-> 单元格 ---------------- */

function rebuildCells() {
  state.cells.clear();
  for (const a of state.assignments) {
    state.cells.set(cellKey(a.staff_id, a.date), {
      shift_code: a.shift_code,
      position_id: a.position_id || "",
      tags: a.tags || [],
    });
  }
}

function cellsToAssignments() {
  const out = [];
  for (const [k, v] of state.cells) {
    const parts = splitKey(k);
    out.push({
      staff_id: parts.staffId,
      date: parts.date,
      shift_code: v.shift_code,
      position_id: v.position_id || "",
      tags: v.tags || [],
    });
  }
  return out;
}

/* ---------------- 渲染：排班表 ---------------- */

function dayInfo(iso) {
  const d = new Date(iso + "T00:00:00");
  const idx = (d.getDay() + 6) % 7;   // 0 = 周一
  const cal = (state.config && state.config.calendar) ||
              { holidays: {}, anchors: {}, adjusted_workdays: [] };
  const holiday = cal.holidays[iso];
  const adjusted = (cal.adjusted_workdays || []).indexOf(iso) >= 0;
  return {
    iso: iso,
    weekday: state.weekdayLabels[idx] || "",
    md: iso.slice(5).replace("-", "/"),
    isRest: !!holiday || (idx >= 5 && !adjusted),
    label: cal.anchors[iso] || holiday || "",
  };
}

function renderBoard() {
  const table = $("#board");
  table.innerHTML = "";
  const cfg = state.config;
  if (!cfg) return;

  const days = state.days;
  const thead = document.createElement("thead");
  const hrow = document.createElement("tr");

  const nameTh = document.createElement("th");
  nameTh.className = "col-name";
  nameTh.textContent = "人员";
  hrow.appendChild(nameTh);

  for (const iso of days) {
    const info = dayInfo(iso);
    const th = document.createElement("th");
    th.className = "col-day" + (info.isRest ? " rest" : "") + (info.label ? " holiday" : "");
    th.innerHTML = esc(info.weekday) + "<br>" + esc(info.md);
    if (info.label) th.title = info.label;
    hrow.appendChild(th);
  }
  thead.appendChild(hrow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");

  if (!days.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.className = "empty-cell";
    td.textContent = "当前周文件没有数据。";
    tr.appendChild(td);
    tbody.appendChild(tr);
    table.appendChild(tbody);
    return;
  }

  for (const g of cfg.groups) {
    const members = cfg.staff.filter((s) => s.group === g.value);

    const gr = document.createElement("tr");
    gr.className = "group-row";
    const gtd = document.createElement("td");
    gtd.colSpan = days.length + 1;
    gtd.className = "group-cell";

    const glabel = document.createElement("span");
    glabel.className = "group-label";
    glabel.textContent = g.label + "（" + members.length + " 人）";
    gtd.appendChild(glabel);

    const gadd = document.createElement("button");
    gadd.className = "btn-mini btn-add-person";
    gadd.type = "button";
    gadd.textContent = "+ 新增人员";
    gadd.title = "在本组新增一名人员";
    gadd.addEventListener("click", () => openStaffForm(g.value));
    gtd.appendChild(gadd);

    gr.appendChild(gtd);
    tbody.appendChild(gr);

    if (!members.length) {
      const er = document.createElement("tr");
      er.className = "empty-group-row";
      const etd = document.createElement("td");
      etd.colSpan = days.length + 1;
      etd.className = "empty-cell";
      etd.textContent = "本组暂无人员，点上方「+ 新增人员」添加。";
      er.appendChild(etd);
      tbody.appendChild(er);
      continue;
    }

    for (const person of members) {
      const tr = document.createElement("tr");
      if (!person.rosterable) tr.classList.add("inactive");

      const ntd = document.createElement("td");
      ntd.className = "col-name";
      let html = '<span class="nm">' + esc(person.name) + "</span>";
      if (person.is_trainee) html += '<span class="tag trainee">进修</span>';
      if (!person.rosterable) {
        html += '<span class="tag inactive">' +
                esc(STATUS_LABELS[person.status] || person.status) + "</span>";
      }
      ntd.innerHTML = html;

      const del = document.createElement("button");
      del.className = "btn-mini btn-del-person";
      del.type = "button";
      del.textContent = "×";
      del.title = "删除「" + person.name + "」";
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        deletePerson(person);
      });
      ntd.appendChild(del);

      tr.appendChild(ntd);

      for (const iso of days) {
        const td = document.createElement("td");
        td.className = "cell";
        const cell = state.cells.get(cellKey(person.id, iso));
        if (cell) {
          const shift = shiftByCode(cell.shift_code);
          td.classList.add("filled");
          if (shift) {
            td.textContent = shift.name;
            if (shift.color) td.style.background = "#" + shift.color;
          } else {
            td.textContent = cell.shift_code;
            td.classList.add("unknown");
          }
        }
        applyIssue(td, person.id, iso);
        td.addEventListener("click", () => openPicker(person, iso));
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
  }

  table.appendChild(tbody);
}

function applyIssue(td, staffId, date) {
  const r = state.report;
  if (!r) return;
  const hits = r.errors.concat(r.warnings).filter(
    (v) => v.staff_id === staffId && v.date === date
  );
  if (!hits.length) return;
  const hasError = hits.some((v) => v.severity === "error");
  td.classList.add(hasError ? "issue-error" : "issue-warn");
  td.title = hits.map((v) => v.message).join("\n");
}

/* ---------------- 渲染：侧栏 ---------------- */

function issueHtml(v) {
  return '<div class="iss ' + v.severity + '">' +
    '<div class="iss-code">' + esc(v.code) + (v.date ? " · " + esc(v.date) : "") + "</div>" +
    '<div class="iss-msg">' + esc(v.message) + "</div>" +
    "</div>";
}

function renderReport() {
  const box = $("#tab-issues");
  const r = state.report;
  if (!r) { box.innerHTML = '<div class="empty">暂无校验结果</div>'; return; }

  const parts = [];
  parts.push('<div class="summary ' + (r.ok ? "ok" : "bad") + '">' + esc(r.summary) + "</div>");

  if (r.errors.length) {
    parts.push('<div class="iss-head err">错误（' + r.errors.length + "）</div>");
    parts.push(r.errors.map(issueHtml).join(""));
  }
  if (r.warnings.length) {
    parts.push('<div class="iss-head warn">提醒（' + r.warnings.length + "）</div>");
    parts.push(r.warnings.map(issueHtml).join(""));
  }
  if (!r.errors.length && !r.warnings.length) {
    parts.push('<div class="empty">未发现任何问题 🎉</div>');
  }
  box.innerHTML = parts.join("");
}

function renderStats() {
  const box = $("#tab-stats");
  const rows = state.stats || [];
  if (!rows.length) { box.innerHTML = '<div class="empty">暂无统计数据</div>'; return; }

  let html = "<table class='mini'><thead><tr>" +
    "<th>姓名</th><th>组别</th><th>出勤</th><th>休息</th><th>夜班</th><th>值出</th><th>加权分</th>" +
    "</tr></thead><tbody>";
  for (const s of rows) {
    html += "<tr>" +
      "<td>" + esc(s.name) + "</td>" +
      "<td>" + esc(s.group) + "</td>" +
      "<td>" + s.work_days + "</td>" +
      "<td>" + s.off_days + "</td>" +
      "<td class='" + (s.night_count >= 3 ? "hot" : "") + "'>" + s.night_count + "</td>" +
      "<td>" + s.post_night_count + "</td>" +
      "<td>" + Number(s.weighted_score).toFixed(1) + "</td>" +
      "</tr>";
  }
  html += "</tbody></table>";
  box.innerHTML = html;
}

function renderShifts() {
  const box = $("#tab-shifts");
  const cfg = state.config;
  if (!cfg) return;
  let html = "<table class='mini'><thead><tr>" +
    "<th>代码</th><th>名称</th><th>时间</th><th>权重</th></tr></thead><tbody>";
  for (const s of cfg.shifts) {
    const time = s.start ? (s.start + "—" + s.end) : "—";
    html += "<tr>" +
      "<td>" + esc(s.code) + "</td>" +
      "<td>" + esc(s.name) + "</td>" +
      "<td>" + esc(time) + "</td>" +
      "<td>" + Number(s.weight).toFixed(1) + "</td>" +
      "</tr>";
  }
  html += "</tbody></table>";
  box.innerHTML = html;
}

function renderStatus() {
  const bar = $("#statusbar");
  const r = state.report;
  bar.className = "statusbar";
  if (!r) {
    $("#status-text").textContent = "加载中…";
  } else if (!r.ok) {
    bar.classList.add("bad");
    $("#status-text").textContent = r.summary;
  } else if (r.warnings.length) {
    bar.classList.add("warn");
    $("#status-text").textContent = r.summary;
  } else {
    bar.classList.add("ok");
    $("#status-text").textContent = r.summary;
  }
  $("#dirty-flag").textContent = state.dirty ? "· 有未保存的改动" : "";
}

function renderFileSelect() {
  const sel = $("#file-select");
  sel.innerHTML = "";
  for (const f of state.files) {
    const opt = document.createElement("option");
    opt.value = f.name;
    opt.textContent = f.label;
    if (f.name === state.currentFile) opt.selected = true;
    sel.appendChild(opt);
  }
  if (!state.files.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "（无周文件）";
    sel.appendChild(opt);
  }
}

function renderAll() {
  if (state.config) $("#dept-name").textContent = state.config.name;
  renderFileSelect();
  renderBoard();
  renderReport();
  renderStats();
  renderShifts();
  renderStatus();
}

/* ---------------- 班次选择器 ---------------- */

function openPicker(person, date) {
  pickerCtx = { person: person, date: date };
  const cur = state.cells.get(cellKey(person.id, date));

  $("#picker-title").textContent = person.name + " · " + date;

  const list = $("#picker-list");
  list.innerHTML = "";

  const clear = document.createElement("button");
  clear.className = "pick-item clear";
  clear.textContent = "— 清空此格 —";
  clear.addEventListener("click", () => { setCell(person.id, date, null); closePicker(); });
  list.appendChild(clear);

  for (const grp of SHIFT_GROUPS) {
    const shifts = state.config.shifts.filter((s) => grp.kinds.indexOf(s.kind) >= 0);
    if (!shifts.length) continue;

    const head = document.createElement("div");
    head.className = "pick-group";
    head.textContent = grp.label;
    list.appendChild(head);

    for (const s of shifts) {
      const btn = document.createElement("button");
      btn.className = "pick-item";
      if (cur && cur.shift_code === s.code) btn.classList.add("active");
      if (s.color) btn.style.borderLeftColor = "#" + s.color;
      btn.innerHTML = '<span class="pi-name">' + esc(s.name) + '</span>' +
                      '<span class="pi-code">' + esc(s.code) + "</span>";
      btn.addEventListener("click", () => { setCell(person.id, date, s.code); closePicker(); });
      list.appendChild(btn);
    }
  }

  $("#mask").hidden = false;
  $("#picker").hidden = false;
  hideShiftForm();
}

function closePicker() {
  pickerCtx = null;
  hideShiftForm();
  $("#mask").hidden = true;
  $("#picker").hidden = true;
}

/* ---------------- 新增班次 ---------------- */

function showShiftForm() {
  $("#picker-list").hidden = true;
  $("#picker-foot").hidden = true;

  // 类别下拉按需填充（数据来自后端 shift_kinds）
  const sel = $("#sa-kind");
  if (!sel.options.length) {
    for (const k of state.config.shift_kinds || []) {
      const opt = document.createElement("option");
      opt.value = k.value;
      opt.textContent = k.label;
      sel.appendChild(opt);
    }
    sel.value = "day";
  }

  $("#sa-error").hidden = true;
  $("#sa-name").value = "";
  $("#sa-start").value = "";
  $("#sa-end").value = "";
  $("#sa-weight").value = "1.0";
  $("#shift-add-form").hidden = false;
  $("#sa-name").focus();
}

function hideShiftForm() {
  const form = $("#shift-add-form");
  if (!form || form.hidden) return;
  form.hidden = true;
  $("#picker-list").hidden = false;
  $("#picker-foot").hidden = false;
}

function showShiftError(msg) {
  const box = $("#sa-error");
  box.textContent = msg;
  box.hidden = false;
}

async function submitShiftForm() {
  const name = $("#sa-name").value.trim();
  if (!name) { showShiftError("请填写班次名称"); return; }

  const payload = {
    name: name,
    kind: $("#sa-kind").value,
    start: $("#sa-start").value.trim(),
    end: $("#sa-end").value.trim(),
    weight: Number($("#sa-weight").value || 1.0),
  };

  let data;
  try {
    const res = await fetch("/api/shift", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ("HTTP " + res.status));
  } catch (e) {
    showShiftError(e.message);
    return;
  }

  // 后端已写回 shifts.yaml：把新班次并入本地配置，
  // 并直接填进触发新增的那个格子
  state.config.shifts.push(data.shift);
  hideShiftForm();
  toast("已新增班次「" + data.shift.name + "」，已写入 " + data.file, "ok");

  if (pickerCtx) {
    setCell(pickerCtx.person.id, pickerCtx.date, data.shift.code);
    closePicker();
  } else {
    closePicker();
  }
}

/* ---------------- 新增 / 删除人员 ---------------- */

function openStaffForm(group) {
  const form = $("#staff-add-form");
  // 组别下拉与状态下拉按需填充（数据来自后端）
  const gsel = $("#sf-group");
  if (!gsel.options.length) {
    for (const g of state.config.staff_groups || []) {
      const opt = document.createElement("option");
      opt.value = g.value;
      opt.textContent = g.label;
      gsel.appendChild(opt);
    }
  }
  const ssel = $("#sf-status");
  if (!ssel.options.length) {
    for (const s of state.config.staff_statuses || []) {
      const opt = document.createElement("option");
      opt.value = s.value;
      opt.textContent = s.label;
      ssel.appendChild(opt);
    }
    ssel.value = "active";
  }
  gsel.value = group || "other";

  // 技能标签快捷勾选（来自 positions.yaml 的技能并集）
  const box = $("#sf-skills");
  box.innerHTML = "";
  for (const sk of state.config.skill_options || []) {
    const id = "sf-sk-" + sk;
    const wrap = document.createElement("label");
    wrap.className = "sf-skill";
    wrap.innerHTML =
      '<input type="checkbox" id="' + esc(id) + '" value="' + esc(sk) + '">' +
      "<span>" + esc(sk) + "</span>";
    box.appendChild(wrap);
  }

  // 带教老师下拉（仅在职、非进修人员可选）
  const sup = $("#sf-supervisor");
  sup.innerHTML = '<option value="">（无）</option>';
  for (const s of state.config.staff) {
    if (s.is_trainee) continue;
    if (!s.rosterable) continue;
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = s.name + "（" + s.id + "）";
    sup.appendChild(opt);
  }

  $("#sf-error").hidden = true;
  $("#sf-name").value = "";
  $("#sf-id").value = "";
  $("#sf-title").value = "";
  $("#sf-night").checked = false;
  sup.value = "";
  $("#sf-note").value = "";
  $("#staff-add-mask").hidden = false;
  form.hidden = false;
  $("#sf-name").focus();
}

function closeStaffForm() {
  $("#staff-add-form").hidden = true;
  $("#staff-add-mask").hidden = true;
}

function showStaffError(msg) {
  const box = $("#sf-error");
  box.textContent = msg;
  box.hidden = false;
}

async function submitStaffForm() {
  const name = $("#sf-name").value.trim();
  if (!name) { showStaffError("请填写姓名"); return; }

  const payload = {
    name: name,
    id: $("#sf-id").value.trim(),
    group: $("#sf-group").value,
    title: $("#sf-title").value.trim(),
    skills: Array.from(document.querySelectorAll("#sf-skills input:checked"))
      .map((el) => el.value),
    night_eligible: $("#sf-night").checked,
    status: $("#sf-status").value,
    supervisor_id: $("#sf-supervisor").value,
    note: $("#sf-note").value.trim(),
  };

  let data;
  try {
    const res = await fetch("/api/staff", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ("HTTP " + res.status));
  } catch (e) {
    showStaffError(e.message);
    return;
  }

  state.config.staff.push(data.staff);
  closeStaffForm();
  renderBoard();
  renderStatus();
  scheduleCheck();
  toast("已新增人员「" + data.staff.name + "」（" + data.staff.id + "），已写入 " + data.file, "ok");
}

async function deletePerson(person) {
  const msg = "确定删除「" + person.name + "（" + person.id + "）」吗？\n\n" +
    "· 会从 staff.yaml 中移除该人员\n" +
    "· 其已有的排班记录会一并清除（点「保存」后落盘）\n" +
    "此操作不可撤销。";
  if (!confirm(msg)) return;

  let data;
  try {
    const res = await fetch("/api/staff/" + encodeURIComponent(person.id), {
      method: "DELETE",
    });
    data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ("HTTP " + res.status));
  } catch (e) {
    toast("删除失败：" + e.message, "error");
    return;
  }

  // 本地同步：移除人员、清掉其排班格子，并解除被释放的进修人员标记
  state.config.staff = state.config.staff.filter((s) => s.id !== person.id);
  for (const k of Array.from(state.cells.keys())) {
    if (k.slice(0, k.length - 12) === person.id) state.cells.delete(k);
  }
  for (const id of data.released_trainees || []) {
    const t = state.config.staff.find((s) => s.id === id);
    if (t) { t.supervisor_id = ""; t.is_trainee = false; t.can_hold_position = t.rosterable; }
  }
  state.dirty = true;
  renderBoard();
  renderStatus();
  scheduleCheck();

  let extra = "";
  if ((data.released_trainees || []).length) {
    extra = "，并解除了 " + data.released_trainees.length + " 名进修人员的挂靠";
  }
  toast("已删除「" + (data.deleted_name || person.name) + "」" + extra, "ok");
}

function setCell(staffId, date, shiftCode) {
  const k = cellKey(staffId, date);
  if (!shiftCode) {
    state.cells.delete(k);
  } else {
    const pos = state.config.positions.find((p) => p.shift_code === shiftCode);
    state.cells.set(k, {
      shift_code: shiftCode,
      position_id: pos ? pos.id : "",
      tags: [],
    });
  }
  state.dirty = true;
  renderBoard();
  renderStatus();
  scheduleCheck();
}

/* ---------------- 与后端交互 ---------------- */

/* ---------------- 一键排一周（CP-SAT 求解） ---------------- */

function openSolvePanel() {
  const start = $("#solve-start");
  const days = $("#solve-days");
  const err = $("#solve-error");
  const prog = $("#solve-progress");
  err.hidden = true;
  prog.hidden = true;
  if (!start.value) {
    const d = state.days && state.days.length ? state.days[0] : null;
    if (d) {
      start.value = d;
    } else {
      const t = new Date();
      const monday = new Date(t.getTime() - ((t.getDay() + 6) % 7) * 86400000);
      start.value = monday.toISOString().slice(0, 10);
    }
  }
  if (!days.value) days.value = (state.days && state.days.length) || 7;
  $("#solve-lock").checked = false;
  $("#solve-panel").hidden = false;
  $("#solve-mask").hidden = false;
}

function closeSolvePanel() {
  $("#solve-panel").hidden = true;
  $("#solve-mask").hidden = true;
}

function showSolveError(msg) {
  const box = $("#solve-error");
  box.textContent = msg;
  box.hidden = false;
}

async function runSolve() {
  const start = $("#solve-start").value;
  if (!start) { showSolveError("请选择起始日期"); return; }

  const payload = {
    week_start: start,
    days_count: parseInt($("#solve-days").value, 10) || 7,
  };

  // 保留改动：把界面上已手工调整的格子作为固定项发给后端
  if ($("#solve-lock").checked) {
    const fixed = [];
    for (const [k, v] of state.cells) {
      const parts = splitKey(k);
      fixed.push({ staff_id: parts.staffId, date: parts.date, shift_code: v.shift_code });
    }
    payload.fixed = fixed;
  }

  $("#solve-progress").hidden = false;
  $("#solve-error").hidden = true;
  $("#solve-run").disabled = true;

  let data;
  try {
    const res = await fetch("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ("HTTP " + res.status));
  } catch (e) {
    $("#solve-progress").hidden = true;
    $("#solve-run").disabled = false;
    showSolveError("求解失败：" + e.message);
    return;
  }

  $("#solve-progress").hidden = true;
  $("#solve-run").disabled = false;

  if (!data.ok) {
    // 无解：把原因展示出来，不动现有排班
    const reason = (data.warnings || []).join(" ") || ("状态：" + data.status);
    showSolveError("未能排出可行排班。" + reason);
    return;
  }

  // 求解成功：把结果替换到当前周
  state.days = Array.from(
    new Set((data.assignments || []).map((a) => a.date))
  ).sort();
  state.assignments = data.assignments || [];
  rebuildCells();
  state.dirty = true;
  renderAll();
  scheduleCheck();
  closeSolvePanel();

  const offs = Object.values(data.off_by_staff || {});
  const offInfo = offs.length
    ? `，每人休息 ${Math.min(...offs)}–${Math.max(...offs)} 天`
    : "";
  const optional = data.stats && data.stats.optional_filled
    ? Object.entries(data.stats.optional_filled)
        .filter(([, n]) => n > 0)
        .map(([k, n]) => `${k} ${n} 天`)
        .join("、")
    : "";
  toast(
    "已排好 " + data.week_start + " 起 " + data.days + " 天" + offInfo +
      (optional ? "（可选岗位：" + optional + "）" : "") +
      "，记得点「保存」",
    "ok"
  );
}

async function loadState(file) {
  let data;
  try {
    const url = "/api/state" + (file ? "?file=" + encodeURIComponent(file) : "");
    const res = await fetch(url);
    data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ("HTTP " + res.status));
  } catch (e) {
    toast("加载失败：" + e.message, "error");
    return;
  }
  state.config = data.config;
  state.files = data.files;
  state.currentFile = data.current_file;
  state.days = data.days;
  state.weekdayLabels = data.weekday_labels;
  state.assignments = data.assignments;
  state.report = data.report;
  state.stats = data.stats;
  state.dirty = false;
  rebuildCells();
  renderAll();
}

function scheduleCheck() {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(runCheck, 400);
}

async function runCheck() {
  let data;
  try {
    const res = await fetch("/api/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assignments: cellsToAssignments() }),
    });
    data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ("HTTP " + res.status));
  } catch (e) {
    toast("校验失败：" + e.message, "error");
    return;
  }
  state.report = data;
  renderBoard();
  renderReport();
  renderStatus();
}

async function doSave() {
  let data;
  try {
    const res = await fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: state.currentFile, assignments: cellsToAssignments() }),
    });
    data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ("HTTP " + res.status));
  } catch (e) {
    toast("保存失败：" + e.message, "error");
    return;
  }
  state.currentFile = data.file;
  state.dirty = false;
  renderStatus();
  toast("已保存 " + data.file + "（" + data.count + " 条）", "ok");
}

async function doExport() {
  let data;
  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: state.currentFile, assignments: cellsToAssignments() }),
    });
    data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ("HTTP " + res.status));
  } catch (e) {
    toast("导出失败：" + e.message, "error");
    return;
  }
  toast("已导出 " + data.name, "ok");
  window.location.href = data.url;
}

/* ---------------- 事件绑定 ---------------- */

function bindEvents() {
  $("#btn-check").addEventListener("click", runCheck);
  $("#btn-save").addEventListener("click", doSave);
  $("#btn-export").addEventListener("click", doExport);
  $("#picker-cancel").addEventListener("click", closePicker);
  $("#picker-add").addEventListener("click", showShiftForm);
  $("#sa-cancel").addEventListener("click", hideShiftForm);
  $("#mask").addEventListener("click", closePicker);

  $("#sf-cancel").addEventListener("click", closeStaffForm);
  $("#staff-add-mask").addEventListener("click", closeStaffForm);
  $("#staff-add-form").addEventListener("submit", (e) => {
    e.preventDefault();
    submitStaffForm();
  });

  $("#shift-add-form").addEventListener("submit", (e) => {
    e.preventDefault();
    submitShiftForm();
  });

  // 一键排一周
  $("#btn-solve").addEventListener("click", openSolvePanel);
  $("#solve-cancel").addEventListener("click", closeSolvePanel);
  $("#solve-mask").addEventListener("click", closeSolvePanel);
  $("#solve-run").addEventListener("click", runSolve);

  $("#file-select").addEventListener("change", (e) => {
    if (state.dirty && !confirm("当前有未保存的改动，切换文件会丢失。确定继续？")) {
      e.target.value = state.currentFile;
      return;
    }
    loadState(e.target.value);
  });

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const name = tab.dataset.tab;
      ["issues", "stats", "shifts"].forEach((n) => {
        $("#tab-" + n).classList.toggle("hidden", n !== name);
      });
    });
  });

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      doSave();
    } else if (e.key === "Escape") {
      // 求解面板 > 人员表单 > 班次表单退回列表 > 弹窗
      if (!$("#solve-panel").hidden) {
        closeSolvePanel();
      } else if (!$("#staff-add-form").hidden) {
        closeStaffForm();
      } else if (!$("#shift-add-form").hidden) {
        hideShiftForm();
      } else {
        closePicker();
      }
    }
  });

  window.addEventListener("beforeunload", (e) => {
    if (state.dirty) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  loadState();
});
