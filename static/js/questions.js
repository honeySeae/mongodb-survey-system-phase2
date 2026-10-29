// 题目库：我的题目 / 共享给我的 / 公开的（每个版本一项，最近修改的在前），新建题目。
import { api, requireLogin, withQuery } from "./api.js";
import { el, errorNotice, formatTime, renderTopbar } from "./layout.js";
import { createContentEditor } from "./library-editor.js";
import { optionSummary, sharingText, versionBadge } from "./library-common.js";
import { TYPE_LABELS } from "./render.js";

const $ = (id) => document.getElementById(id);
const PAGE_SIZE = 20;
const EMPTY_TEXT = {
  mine: "还没有题目，点击上方“新建题目”，或在问卷编辑页把问卷中的题“存入题目库”",
  shared: "还没有人把题目共享给你",
  public: "还没有别人公开的题目",
};
const SCOPE_NOTE = {
  mine: "你创建的所有版本。被问卷使用过的版本不能直接修改，只能基于它创建新版本。",
  shared: "别人共享给你的题目：可以查看、用在自己的问卷中、基于它创建自己的新版本，不能直接修改。",
  public: "别人设为公开的题目：可以查看、用在自己的问卷中、基于它创建自己的新版本，不能直接修改。",
};

let scope = "mine";
let loaded = [];
let total = 0;

if (requireLogin()) {
  renderTopbar("questions");
  load(true);
}

// ---------- 标签页 ----------
$("tabs").addEventListener("click", (event) => {
  const btn = event.target.closest("button[data-scope]");
  if (!btn || btn.dataset.scope === scope) return;
  scope = btn.dataset.scope;
  $("tabs").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
  load(true);
});
$("more-btn").addEventListener("click", () => load(false));

// ---------- 新建 ----------
$("new-btn").addEventListener("click", () => {
  const editor = createContentEditor({
    question: null, submitText: "保存到题目库",
    onCancel: closeNew,
    async onSubmit(body) {
      editor.setBusy(true);
      try {
        const q = await api("POST", "/api/questions", body);
        location.href = `/questions/${q.id}`;
      } catch (err) {
        editor.showError(errorNotice(err));
        editor.setBusy(false);
      }
    },
  });
  $("new-slot").replaceChildren(editor.element);
  $("new-section").hidden = false;
  $("new-btn").hidden = true;
  const title = document.getElementById("lib-title");
  if (title) title.focus();
});

function closeNew() {
  $("new-section").hidden = true;
  $("new-btn").hidden = false;
  $("new-slot").replaceChildren();
}

// ---------- 列表 ----------
async function load(reset) {
  if (reset) {
    loaded = [];
    $("list").replaceChildren(el("div", { class: "empty", text: "加载中…" }));
  }
  $("more-btn").disabled = true;
  try {
    const page = await api("GET", withQuery("/api/questions", { scope, offset: loaded.length, limit: PAGE_SIZE }));
    loaded = loaded.concat(page.items);
    total = page.total;
    $("summary").textContent = `${SCOPE_NOTE[scope]}共 ${total} 个版本。`;
    $("list").replaceChildren(...(loaded.length ? loaded.map(questionItem)
      : [el("div", { class: "empty", text: EMPTY_TEXT[scope] })]));
    $("more-btn").hidden = loaded.length >= total;
  } catch (err) {
    $("list").replaceChildren(el("div", { class: "paper-body" }, errorNotice(err)));
  } finally {
    $("more-btn").disabled = false;
  }
}

function questionItem(q) {
  const meta = [TYPE_LABELS[q.type] || q.type, `更新于 ${formatTime(q.updatedAt)}`];
  if (!q.isMine) meta.unshift(`来自 ${q.owner}`);
  if (q.isMine) meta.push(sharingText(q.sharing));
  const summary = optionSummary(q);
  return el("div", { class: "survey-item lib-item" },
    el("h3", {},
      el("a", { href: `/questions/${q.id}`, text: q.title }),
      versionBadge(q),
      q.locked ? el("span", { class: "badge closed", title: "已被问卷使用，只能基于它创建新版本", text: "已使用" }) : null),
    el("div", { class: "meta", text: meta.join(" · ") }),
    summary ? el("div", { class: "lib-options", text: summary }) : null,
    el("div", { class: "actions mt-s" },
      el("a", { class: "btn small ghost", href: `/questions/${q.id}`, text: "查看 / 版本历史" })),
  );
}
