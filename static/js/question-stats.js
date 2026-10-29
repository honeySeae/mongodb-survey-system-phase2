// 单题跨问卷统计：合并后的结果 + 各问卷的结果；可以按版本、按问卷筛选（如比较“去年的问卷”和“今年的问卷”）。
// 筛选项来自不筛选时的结果（只有参与统计的版本和问卷可选）；全部选中等于不筛选。
import { api, requireLogin, withQuery } from "./api.js";
import { el, errorNotice, formatTime, pathSegment, POLICY_LABELS, renderTopbar, statusBadge } from "./layout.js";
import { filterParam, formatNumber, percent, versionBadge } from "./library-common.js";
import { TYPE_LABELS } from "./render.js";

const $ = (id) => document.getElementById(id);
const questionId = pathSegment(1);
const ITEMS_PAGE = 20;

let all = null;          // 不筛选时的结果：提供筛选项
let current = null;      // 当前显示的结果
let requestNo = 0;       // 筛选连续变化时，只采用最后一次请求的结果
const chosen = { versions: [], surveys: [] };

if (requireLogin()) {
  renderTopbar("questions");
  $("back-link").href = `/questions/${encodeURIComponent(questionId)}`;
  init();
}

function statsPath(extra = {}) {
  const params = new URLSearchParams();
  const versions = filterParam(chosen.versions, allVersions());
  const surveys = filterParam(chosen.surveys, all.surveys.map((s) => s.surveyId));
  for (const v of versions || []) params.append("versionId", v);
  for (const s of surveys || []) params.append("surveyId", s);
  for (const [k, v] of Object.entries(extra)) params.set(k, String(v));
  const q = params.toString();
  return `/api/questions/${encodeURIComponent(questionId)}/stats${q ? `?${q}` : ""}`;
}

/** 参与统计的版本（按版本号）：[{ id, version }]。 */
function allVersions() {
  const byId = new Map(all.surveys.map((s) => [s.questionId, s.version]));
  return [...byId.entries()].sort((a, b) => a[1] - b[1]).map(([id]) => id);
}

async function init() {
  try {
    all = await api("GET", `/api/questions/${encodeURIComponent(questionId)}/stats`);
  } catch (err) {
    $("title").textContent = err.status === 404 ? "题目不存在" : "加载失败";
    $("message").replaceChildren(errorNotice(err.status === 404 ? { message: "题目不存在，或没有共享给你" } : err));
    return;
  }
  document.title = `${all.title} · 跨问卷统计`;
  $("title").textContent = `「${all.title}」跨问卷统计`;
  $("meta").textContent = `${TYPE_LABELS[all.type] || all.type} · 同一道题的各个版本按选项合并统计`;
  chosen.versions = allVersions();
  chosen.surveys = all.surveys.map((s) => s.surveyId);
  renderFilters();
  current = all;
  render();
  $("content").hidden = false;
}

// ---------- 筛选 ----------
function checkboxGroup(label, items, key) {
  return el("div", { class: "cross-filter" },
    el("span", { class: "field-label", text: label }),
    el("div", { class: "editor-checks" }, items.map(([id, text]) => el("label", { class: "check" },
      el("input", { type: "checkbox", value: id, checked: chosen[key].includes(id), onchange: (e) => {
        chosen[key] = e.target.checked ? [...chosen[key], id] : chosen[key].filter((x) => x !== id);
        reload();
      } }), text))));
}

function renderFilters() {
  if (!all.surveys.length) { $("filters").replaceChildren(); return; }
  const versionText = new Map(all.surveys.map((s) => [s.questionId, `v${s.version}`]));
  $("filters").replaceChildren(
    checkboxGroup("版本", allVersions().map((id) => [id, versionText.get(id)]), "versions"),
    checkboxGroup("问卷", all.surveys.map((s) => [s.surveyId, s.title]), "surveys"),
    el("div", { class: "help", text: "全部勾选等于不筛选。同时按版本和问卷筛选时取两者都满足的问卷。" }));
}

async function reload() {
  if (!chosen.versions.length || !chosen.surveys.length) {
    $("message").replaceChildren(el("div", { class: "notice warn", text: "版本和问卷都至少要选择一项" }));
    return;
  }
  $("message").replaceChildren();
  const no = ++requestNo;
  try {
    const result = await api("GET", statsPath());
    if (no !== requestNo) return;
    current = result;
    render();
  } catch (err) {
    if (no === requestNo) $("message").replaceChildren(errorNotice(err));
  }
}

// ---------- 显示 ----------
function number(value, label) {
  return el("div", { class: "stat-number" }, el("b", { text: String(value) }), el("span", { text: label }));
}

function render() {
  const o = current.overall;
  $("totals").replaceChildren(number(o.surveyCount, "问卷数"), number(o.answerCount, "答卷数"),
    number(o.respondentCount, "作答人数"));
  $("totals-note").textContent = o.surveyCount
    ? "答卷数是各问卷相加；作答人数按人去重（同一个人填了两份问卷算 1 人）。"
    : "";
  if (!all.surveys.length) {
    $("overall").replaceChildren(el("div", { class: "empty", text: "还没有你的已发布或已关闭的问卷使用这道题" }));
    $("surveys").replaceChildren();
    return;
  }
  $("overall").replaceChildren(...resultBody(o, current.type, true));
  $("surveys").replaceChildren(...(current.surveys.length ? current.surveys.map(surveyCard)
    : [el("div", { class: "muted", text: "没有符合筛选条件的问卷" })]));
}

/** 选项柱状条（与第一阶段统计页相同的样式）；合并结果中只在旧版本中出现的选项加标注。 */
function bars(options, answerCount, type) {
  const unit = type === "multiple_choice" ? "次" : "人";
  return options.map((op) => {
    const p = percent(op.count, answerCount);
    const fill = el("div", { class: "bar-fill" });
    fill.style.width = `${p}%`;
    return el("div", { class: "bar-row" },
      el("div", { class: "bar-label" }, op.text,
        op.onlyInOldVersions ? el("span", { class: "badge closed old-option", title: "这个选项在参与统计的最新版本中已被删除；用旧版本的问卷里选了它的答案照常计数", text: "仅出现在旧版本中" }) : null),
      el("div", { class: "bar-track", title: `${p}%` }, fill),
      el("div", { class: "bar-value", text: `${op.count} ${unit}（${p}%）` }));
  });
}

function resultBody(r, type, merged) {
  const nodes = [];
  if (r.options) {
    nodes.push(...bars(r.options, r.answerCount, type));
    if (type === "multiple_choice" && r.answerCount) {
      nodes.push(el("div", { class: "help", text: "多选题：百分比 = 选择该项的答卷 ÷ 答卷数，各项之和可能超过 100%" }));
    }
    if (!r.answerCount) nodes.push(el("div", { class: "muted", text: "还没有人作答" }));
  }
  if (type === "number") {
    nodes.push(el("div", { class: "stat-average" }, el("span", { class: "muted", text: merged ? "平均值（全部答案） " : "平均值 " }),
      el("b", { text: formatNumber(r.average) })));
  }
  if (merged && r.items) nodes.push(itemsList(r));
  return nodes;
}

/** 合并后的填空内容：附所在问卷，不附填写人；可加载更多。 */
function itemsList(r) {
  const list = el("div", { class: "stat-items" });
  const more = el("button", { class: "btn small link", type: "button" });
  const append = (items) => {
    for (const it of items) {
      list.append(el("div", { class: "stat-item" },
        el("div", { class: `stat-value${current.type === "number" ? " number" : ""}`, text: String(it.value) }),
        el("div", { class: "stat-meta" }, el("span", { class: "stat-user", text: it.surveyTitle }),
          el("span", { text: formatTime(it.submittedAt) }))));
    }
  };
  const update = () => {
    const shown = list.querySelectorAll(".stat-item").length;
    more.hidden = shown >= r.itemsTotal;
    more.textContent = `加载更多（已显示 ${shown} / ${r.itemsTotal}）`;
  };
  append(r.items);
  if (!r.itemsTotal) list.append(el("div", { class: "muted", text: "还没有人作答" }));
  more.addEventListener("click", async () => {
    more.disabled = true;
    try {
      const page = await api("GET", statsPath({ offset: list.querySelectorAll(".stat-item").length, limit: ITEMS_PAGE }));
      append(page.overall.items);
    } catch (err) {
      list.append(errorNotice(err));
    } finally {
      more.disabled = false;
      update();
    }
  });
  update();
  return el("div", { class: "mt-s" }, el("div", { class: "field-label", text: "全部回答（新的在前）" }), list, more);
}

function surveyCard(s) {
  return el("div", { class: "question stat-q cross-survey" },
    el("div", { class: "q-title" },
      el("a", { href: `/surveys/${s.surveyId}/stats`, text: s.title }),
      statusBadge(s),
      versionBadge(s)),
    el("div", { class: "q-hint", text: `${POLICY_LABELS[s.submissionPolicy]} · 答卷数 ${s.answerCount} · 作答人数 ${s.respondentCount}` }),
    el("div", { class: "q-body" }, ...resultBody(s, current.type, false)));
}
