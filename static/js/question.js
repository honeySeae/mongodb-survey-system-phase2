// 题目详情：预览、直接修改 / 创建新版本 / 恢复 / 删除、版本历史、被哪些问卷使用、共享设置。
import { api, requireLogin, withQuery } from "./api.js";
import { bindOptionHighlight, el, errorNotice, formatTime, linkBox, pathSegment, renderTopbar, statusBadge, toast } from "./layout.js";
import { createContentEditor } from "./library-editor.js";
import { flattenTree, parseUsernames, sharingText, versionBadge } from "./library-common.js";
import { createQuestionView, TYPE_LABELS } from "./render.js";

const $ = (id) => document.getElementById(id);
const questionId = pathSegment(1);
let question = null;
let history = null;
let usageScope = "version";

if (requireLogin()) {
  renderTopbar("questions");
  load();
}
bindOptionHighlight($("public-group"));

async function load() {
  try {
    [question, history] = await Promise.all([
      api("GET", `/api/questions/${encodeURIComponent(questionId)}`),
      api("GET", `/api/questions/${encodeURIComponent(questionId)}/history`),
    ]);
  } catch (err) {
    $("title").textContent = err.status === 404 ? "题目不存在" : "加载失败";
    $("message").replaceChildren(errorNotice(err.status === 404
      ? { message: "题目不存在，或没有共享给你" } : err));
    return;
  }
  document.title = `${question.title} · 题目库`;
  renderHead();
  renderPreview();
  renderActions();
  renderHistory();
  renderSharing();
  loadUsage();
  $("content").hidden = false;
}

// ---------- 抬头 ----------
function renderHead() {
  $("title").replaceChildren(question.title, " ", versionBadge(question));
  const meta = [TYPE_LABELS[question.type] || question.type,
                question.isMine ? "我的题目" : `来自 ${question.owner}`,
                `更新于 ${formatTime(question.updatedAt)}`];
  if (question.isMine) meta.push(sharingText(question.sharing));
  $("meta").textContent = meta.join(" · ");
}

function renderPreview() {
  let note;
  if (!question.isMine) {
    note = el("div", { class: "notice info" },
      `这是 ${question.owner} 的题目：可以用在你的问卷中，或基于它创建你自己的新版本；不能直接修改。`);
  } else if (question.locked) {
    note = el("div", { class: "notice info" },
      "这个版本已被问卷使用，不能直接修改。要修改请创建新版本——已有问卷中的题不会改变。");
  } else {
    note = el("div", { class: "notice" },
      "这个版本还没有被问卷使用，可以直接修改；也可以另存为新版本，保留现在的内容。");
  }
  const view = createQuestionView(question, 1, { disabled: true });
  $("state-note").replaceChildren(note);
  $("preview").replaceChildren(view.element,
    el("div", { class: "muted", text: "是否必答、跳转规则在问卷中设置" }));
}

// ---------- 操作 ----------
function hasLaterVersion() {
  return history.versions.some((v) => v.version > question.version);
}

function renderActions() {
  const buttons = [];
  if (question.isMine && !question.locked) {
    buttons.push(el("button", { class: "btn small", type: "button", text: "直接修改", onclick: () => openEditor("edit") }));
    buttons.push(el("button", { class: "btn small ghost", type: "button", text: "另存为新版本", onclick: () => openEditor("derive") }));
  } else {
    buttons.push(el("button", { class: "btn small", type: "button",
      text: question.isMine ? "基于此版本创建新版本" : "基于此版本创建我的新版本", onclick: () => openEditor("derive") }));
  }
  if (hasLaterVersion()) {
    buttons.push(el("button", { class: "btn small ghost", type: "button", text: "恢复此版本", onclick: restore,
      title: "把这个版本的内容复制成一个新版本，接在你最新的版本后面" }));
  }
  if (question.isMine && !question.locked) {
    buttons.push(el("button", { class: "btn small danger", type: "button", text: "删除此版本", onclick: remove }));
  }
  $("actions").replaceChildren(...buttons);
}

function openEditor(mode) {
  const editing = mode === "edit";
  const editor = createContentEditor({
    question, lockType: true,
    submitText: editing ? "保存修改" : "保存为新版本",   // 新版本号由后端分配
    onCancel: closeEditor,
    async onSubmit(body) {
      editor.setBusy(true);
      try {
        if (editing) {
          question = await api("PUT", withQuery(`/api/questions/${question.id}`, { expectedUpdatedAt: question.updatedAt }), body);
          history = await api("GET", `/api/questions/${question.id}/history`);
          closeEditor();
          renderHead();
          renderPreview();
          renderHistory();
          toast("已保存");
        } else {
          const created = await api("POST", `/api/questions/${question.id}/versions`, body);
          location.href = `/questions/${created.id}`;
        }
      } catch (err) {
        editor.showError(errorNotice(err));
        editor.setBusy(false);
      }
    },
  });
  $("editor-slot").replaceChildren(el("div", { class: "editor-head mt", text: editing ? "直接修改这个版本" : "创建新版本" }),
    editor.element);
  $("actions").hidden = true;
  const title = document.getElementById("lib-title");
  if (title) title.focus();
}

function closeEditor() {
  $("editor-slot").replaceChildren();
  $("actions").hidden = false;
}

async function restore() {
  if (!confirm(`把 v${question.version} 的内容复制成一个新版本？原有的版本都不会改变。`)) return;
  try {
    const created = await api("POST", `/api/questions/${question.id}/restore`);
    location.href = `/questions/${created.id}`;
  } catch (err) {
    $("message").replaceChildren(errorNotice(err));
  }
}

async function remove() {
  if (!confirm(`确定删除「${question.title}」的 v${question.version} 吗？删除后无法恢复。`)) return;
  try {
    await api("DELETE", `/api/questions/${question.id}`);
    location.href = "/questions";
  } catch (err) {
    $("message").replaceChildren(errorNotice(err));
  }
}

// ---------- 版本历史 ----------
function renderHistory() {
  const versionOf = new Map(history.versions.map((v) => [v.id, v.version]));
  const rows = flattenTree(history.versions).map(({ node, depth }) => {
    const current = node.id === question.id;
    const extra = [];
    if (node.restoredFrom) extra.push(`恢复自 v${versionOf.get(node.restoredFrom) ?? "?"}`);
    let body;
    if (node.accessible) {
      const d = node.detail;
      extra.unshift(d.isMine ? "我的" : d.owner);
      if (d.locked) extra.push("已使用");
      body = [current ? el("b", { text: d.title }) : el("a", { href: `/questions/${node.id}`, text: d.title })];
    } else {
      body = [el("span", { class: "muted", text: "他人的版本（无权查看）" })];
    }
    return el("div", { class: `history-row${current ? " current" : ""}`, style: `padding-left: ${depth * 22 + 6}px` },
      depth ? el("span", { class: "history-branch", text: "└" }) : null,
      el("span", { class: "badge version", text: `v${node.version}` }),
      ...body,
      extra.length ? el("span", { class: "muted", text: extra.join(" · ") }) : null,
      current ? el("span", { class: "muted", text: "（当前查看）" }) : null);
  });
  $("history").replaceChildren(...rows);
}

// ---------- 被哪些问卷使用 ----------
$("usage-scope").addEventListener("click", (event) => {
  const btn = event.target.closest("button[data-scope]");
  if (!btn || btn.dataset.scope === usageScope) return;
  usageScope = btn.dataset.scope;
  $("usage-scope").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
  loadUsage();
});

async function loadUsage() {
  $("usage").replaceChildren(el("div", { class: "muted", text: "加载中…" }));
  try {
    const u = await api("GET", withQuery(`/api/questions/${question.id}/usage`, { scope: usageScope }));
    const items = u.mine.map((m) => el("div", { class: "usage-item" },
      el("div", { class: "usage-title" },
        el("a", { href: `/surveys/${m.id}/edit`, text: m.title }),
        statusBadge(m),
        el("span", { class: "badge version", title: "这份问卷使用的版本", text: `v${m.version}` })),
      m.status !== "draft" ? linkBox(m.url) : null));
    const summary = u.totalCount === 0
      ? (usageScope === "version" ? "还没有问卷使用这个版本" : "还没有问卷使用这道题")
      : `共 ${u.totalCount} 份问卷在使用：你的问卷 ${u.mineCount} 份` +
        (u.othersCount ? `，别人的问卷 ${u.othersCount} 份（不显示详情）` : "");
    $("usage").replaceChildren(el("div", { class: "muted mt-s", text: summary }), ...items);
  } catch (err) {
    $("usage").replaceChildren(errorNotice(err));
  }
}

// ---------- 共享设置（只有所有者） ----------
function renderSharing() {
  if (!question.isMine) return;
  $("sharing-section").hidden = false;
  $("sharing-public").checked = question.sharing.public;
  $("sharing-public").dispatchEvent(new Event("change", { bubbles: true }));
  $("sharing-users").value = question.sharing.usernames.join(", ");
}

$("sharing-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("sharing-message").replaceChildren();
  $("sharing-save").disabled = true;
  try {
    const r = await api("PUT", `/api/questions/${question.id}/sharing`, {
      public: $("sharing-public").checked, usernames: parseUsernames($("sharing-users").value),
    });
    question = { ...question, sharing: r.question.sharing };
    renderHead();
    renderSharing();
    toast(`已保存，同步到你在这道题下的 ${r.updatedVersions} 个版本`);
  } catch (err) {
    $("sharing-message").replaceChildren(errorNotice(err));
  } finally {
    $("sharing-save").disabled = false;
  }
});
