// 题库详情：题目列表（每项是一道题的一个固定版本）；创建者可以加入 / 移除题目、换版本、修改名称说明、共享、删除。
// 创建者看到“有新版本 vN 可换”和条目不可用的原因（后端只对创建者返回这些提示）；其他人只看到可用 / 不可用。
import { api, requireLogin } from "./api.js";
import { bindOptionHighlight, el, errorNotice, formatTime, pathSegment, renderTopbar, toast } from "./layout.js";
import { diffVersions, optionSummary, parseUsernames, sharingText, versionBadge } from "./library-common.js";
import { createLibraryPicker } from "./library-picker.js";
import { TYPE_LABELS } from "./render.js";

const $ = (id) => document.getElementById(id);
const bankId = pathSegment(1);
let bank = null;
let panel = null;   // 当前展开的面板：{ key: "add" 或 "switch:<rootId>", element }

if (requireLogin()) {
  renderTopbar("banks");
  load();
}
bindOptionHighlight($("public-group"));

async function load() {
  try {
    bank = await api("GET", `/api/banks/${encodeURIComponent(bankId)}`);
  } catch (err) {
    $("title").textContent = err.status === 404 ? "题库不存在" : "加载失败";
    $("message").replaceChildren(errorNotice(err.status === 404 ? { message: "题库不存在，或没有共享给你" } : err));
    return;
  }
  render();
  $("content").hidden = false;
}

function render() {
  renderHead();
  renderItems();
  renderSharing();
  $("add-bar").hidden = !bank.isMine;
}

/** 修改题库后用返回的题库重新渲染。 */
function update(next, message) {
  bank = next;
  panel = null;
  render();
  if (message) toast(message);
}

// ---------- 抬头 ----------
function renderHead() {
  document.title = `${bank.name} · 题库`;
  $("title").textContent = bank.name;
  $("desc").textContent = bank.description;
  $("desc").hidden = !bank.description;
  const meta = [bank.isMine ? "我的题库" : `来自 ${bank.owner}`, `${bank.itemCount} 道题`, `更新于 ${formatTime(bank.updatedAt)}`];
  if (bank.isMine) meta.push(sharingText(bank.sharing));
  $("meta").textContent = meta.join(" · ");

  const actions = [];
  if (bank.isMine) {
    actions.push(el("button", { class: "btn small ghost", type: "button", text: "修改名称和说明", onclick: openEdit }));
    actions.push(el("button", { class: "btn small danger", type: "button", text: "删除题库", onclick: removeBank }));
  }
  actions.push(el("a", { class: "btn small ghost", href: "/banks", text: "返回题库列表" }));
  $("head-actions").replaceChildren(...actions);

  $("role-note").replaceChildren(bank.isMine
    ? el("div", { class: "muted", text: "删除题库或移除题目不影响已经使用这些题的问卷，也不影响题目本身。" })
    : el("div", { class: "notice info", text: `这是 ${bank.owner} 的题库：可以在问卷编辑页“从已有题目添加 → 题库”中使用这些题，` +
        "也可以打开某道题基于它创建自己的新版本；不能修改题库。" }));
}

function openEdit() {
  $("edit-name").value = bank.name;
  $("edit-description").value = bank.description;
  $("edit-form").hidden = false;
  $("edit-name").focus();
}
$("edit-cancel").addEventListener("click", () => { $("edit-form").hidden = true; $("edit-message").replaceChildren(); });
$("edit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("edit-save").disabled = true;
  try {
    const next = await api("PATCH", `/api/banks/${bank.id}`, { name: $("edit-name").value, description: $("edit-description").value });
    $("edit-form").hidden = true;
    $("edit-message").replaceChildren();
    update(next, "已保存");
  } catch (err) {
    $("edit-message").replaceChildren(errorNotice(err));
  } finally {
    $("edit-save").disabled = false;
  }
});

async function removeBank() {
  if (!confirm(`确定删除题库「${bank.name}」吗？已经使用其中题目的问卷和题目本身都不受影响。`)) return;
  try {
    await api("DELETE", `/api/banks/${bank.id}`);
    location.href = "/banks";
  } catch (err) {
    $("message").replaceChildren(errorNotice(err));
  }
}

// ---------- 题目 ----------
function renderItems() {
  const nodes = bank.items.map((item, i) => itemNode(item, i));
  if (panel && panel.key === "add") nodes.push(panel.element);
  if (!bank.items.length && !(panel && panel.key === "add")) {
    nodes.push(el("div", { class: "empty", text: bank.isMine ? "题库中还没有题目，点击下方“加入题目”" : "这个题库还没有题目" }));
  }
  $("items").replaceChildren(...nodes);
}

function itemNode(item, i) {
  if (panel && panel.key === `switch:${item.rootId}`) return panel.element;
  const q = item.question;
  const tools = bank.isMine ? el("div", { class: "actions mt-s" },
    item.newerVersion ? el("button", { class: "btn small", type: "button", text: `换成 v${item.newerVersion.version}`,
      onclick: () => switchItem(item, item.newerVersion.questionId) }) : null,
    item.available ? el("button", { class: "btn small ghost", type: "button", text: "换其他版本", onclick: () => openSwitch(item) }) : null,
    el("button", { class: "btn small danger", type: "button", text: "移除", onclick: () => removeItem(item) })) : null;

  if (!item.available) {
    return el("div", { class: "survey-item lib-item bank-item unavailable" },
      el("h3", {}, el("span", { class: "q-number", text: `${i + 1}.` }), el("span", { class: "muted", text: "不可用的题" }),
        el("span", { class: "badge closed", text: "不可用" })),
      // 原因只对题库创建者给出；其他人只知道不可用
      el("div", { class: bank.isMine ? "notice warn" : "muted", text: bank.isMine && item.notice ? item.notice : "这一项目前不可用" }),
      tools);
  }
  const meta = [TYPE_LABELS[q.type] || q.type, q.isMine ? "我的题目" : `来自 ${q.owner}`];
  const summary = optionSummary(q);
  return el("div", { class: "survey-item lib-item bank-item" },
    el("h3", {}, el("span", { class: "q-number", text: `${i + 1}.` }),
      el("a", { href: `/questions/${q.id}`, text: q.title }), versionBadge(q)),
    el("div", { class: "meta", text: meta.join(" · ") }),
    summary ? el("div", { class: "lib-options", text: summary }) : null,
    bank.isMine && item.notice ? el("div", { class: "notice info bank-notice", text: item.notice }) : null,
    tools);
}

async function switchItem(item, questionId) {
  try {
    update(await api("PUT", `/api/banks/${bank.id}/items/${item.rootId}`, { questionId }), "已换版本");
  } catch (err) {
    $("message").replaceChildren(errorNotice(err));
    $("message").scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

async function removeItem(item) {
  const title = item.question ? `「${item.question.title}」` : "这一项";
  if (!confirm(`从题库中移除${title}？题目本身和已经使用它的问卷都不受影响。`)) return;
  try {
    update(await api("DELETE", `/api/banks/${bank.id}/items/${item.rootId}`), "已移除");
  } catch (err) {
    $("message").replaceChildren(errorNotice(err));
  }
}

/** 换其他版本：列出这道题中自己能用的其他版本，并说明与当前版本相比改了什么。 */
async function openSwitch(item) {
  const list = el("div", { class: "pick-list" }, el("div", { class: "muted", text: "加载中…" }));
  const element = el("div", { class: "question editing library-picker" },
    el("div", { class: "editor-head", text: `「${item.question.title}」换版本（当前 v${item.question.version}）` }),
    el("div", { class: "muted", text: "只能换成同一道题中你自己的、共享给你的或公开的版本。" }),
    list,
    el("div", { class: "actions mt" }, el("button", { class: "btn link muted", type: "button", text: "取消",
      onclick: () => { panel = null; renderItems(); } })));
  panel = { key: `switch:${item.rootId}`, element };
  renderItems();
  try {
    const history = await api("GET", `/api/questions/${item.questionId}/history`);
    const others = history.versions.filter((v) => v.accessible && v.id !== item.questionId)
      .sort((a, b) => b.version - a.version);
    list.replaceChildren(...(others.length ? others.map((v) => {
      const changes = diffVersions(item.question, v.detail);
      return el("div", { class: "pick-row" },
        el("div", { class: "pick-main" },
          el("div", { class: "pick-title" }, el("span", { text: v.detail.title }), versionBadge(v),
            el("span", { class: "muted", text: v.version > item.question.version ? "较新" : "较旧" }),
            el("a", { href: `/questions/${v.id}`, target: "_blank", class: "muted", text: "查看" })),
          el("div", { class: "muted", text: `${v.detail.isMine ? "我的" : v.detail.owner} · ` +
            (changes.length ? `与当前相比：${changes.join("；")}` : "与当前内容相同") })),
        el("div", { class: "pick-controls" },
          el("button", { class: "btn small", type: "button", text: "换成这个版本", onclick: () => switchItem(item, v.id) })));
    }) : [el("div", { class: "muted", text: "这道题没有其他可用的版本" })]));
  } catch (err) {
    list.replaceChildren(errorNotice(err));
  }
}

$("add-btn").addEventListener("click", () => {
  const picker = createLibraryPicker({
    title: "加入题目",
    intro: "题库中的每一项是一道题的一个固定版本；同一道题只能加入一次，要用其他版本请对这一项“换版本”。",
    usedRoots: new Set(bank.items.map((i) => i.rootId)),
    usedText: "已在题库中",
    usedTitle: "同一道题在一个题库中只能有一项",
    addText: "加入",
    showRequired: false,
    showBanks: false,
    async onAdd(questionId) {
      update(await api("POST", `/api/banks/${bank.id}/items`, { questionId }), "已加入题库");
    },
    onCancel: () => { panel = null; renderItems(); },
  });
  panel = { key: "add", element: picker.element };
  renderItems();
  picker.element.scrollIntoView({ behavior: "smooth", block: "start" });
});

// ---------- 共享设置（只有创建者） ----------
function renderSharing() {
  $("sharing-section").hidden = !bank.isMine;
  if (!bank.isMine) return;
  $("sharing-public").checked = bank.sharing.public;
  $("sharing-public").dispatchEvent(new Event("change", { bubbles: true }));
  $("sharing-users").value = bank.sharing.usernames.join(", ");
}

$("sharing-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("sharing-message").replaceChildren();
  $("sharing-save").disabled = true;
  try {
    const next = await api("PUT", `/api/banks/${bank.id}/sharing`, {
      public: $("sharing-public").checked, usernames: parseUsernames($("sharing-users").value),
    });
    update(next, "共享设置已保存");
  } catch (err) {
    $("sharing-message").replaceChildren(errorNotice(err));
  } finally {
    $("sharing-save").disabled = false;
  }
});
