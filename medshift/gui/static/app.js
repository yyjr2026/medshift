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
    if (!members.length) continue;

    const gr = document.createElement("tr");
    gr.className = "group-row";
    const gtd = document.createElement("td");
    gtd.colSpan = days.length + 1;
    gtd.textContent = g.label + "（" + members.length + " 人）";
    gr.appendChild(gtd);
    tbody.appendChild(gr);

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
}

function closePicker() {
  pickerCtx = null;
  $("#mask").hidden = true;
  $("#picker").hidden = true;
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
  $("#mask").addEventListener("click", closePicker);

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
      closePicker();
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
