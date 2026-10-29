// 题库列表：我的题库 / 共享给我的 / 公开的，新建题库。
import { api, requireLogin, withQuery } from "./api.js";
import { el, errorNotice, formatTime, renderTopbar } from "./layout.js";
import { sharingText } from "./library-common.js";

const $ = (id) => document.getElementById(id);
const PAGE_SIZE = 20;
const EMPTY_TEXT = {
  mine: "还没有题库，点击上方“新建题库”开始整理常用题目",
  shared: "还没有人把题库共享给你",
  public: "还没有别人公开的题库",
};
const SCOPE_NOTE = {
  mine: "你创建的题库：只有你能修改。",
  shared: "别人共享给你的题库：可以使用其中的题，不能修改题库。",
  public: "别人公开的题库：可以使用其中的题，不能修改题库。",
};

let scope = "mine";
let loaded = [];
let requestNo = 0;   // 切换标签时，只采用最后一次请求的结果（较早的请求可能更晚返回）

if (requireLogin()) {
  renderTopbar("banks");
  load(true);
}

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
  $("new-form").hidden = false;
  $("new-btn").hidden = true;
  $("name").focus();
});
$("cancel-btn").addEventListener("click", () => {
  $("new-form").hidden = true;
  $("new-btn").hidden = false;
  $("new-message").replaceChildren();
});
$("new-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("new-message").replaceChildren();
  $("create-btn").disabled = true;
  try {
    const bank = await api("POST", "/api/banks", { name: $("name").value, description: $("description").value });
    location.href = `/banks/${bank.id}`;
  } catch (err) {
    $("new-message").replaceChildren(errorNotice(err));
    $("create-btn").disabled = false;
  }
});

// ---------- 列表 ----------
async function load(reset) {
  if (reset) {
    loaded = [];
    $("list").replaceChildren(el("div", { class: "empty", text: "加载中…" }));
  }
  $("more-btn").disabled = true;
  const no = ++requestNo;
  try {
    const page = await api("GET", withQuery("/api/banks", { scope, offset: loaded.length, limit: PAGE_SIZE }));
    if (no !== requestNo) return;
    loaded = loaded.concat(page.items);
    $("summary").textContent = `${SCOPE_NOTE[scope]}共 ${page.total} 个题库。`;
    $("list").replaceChildren(...(loaded.length ? loaded.map(bankItem)
      : [el("div", { class: "empty", text: EMPTY_TEXT[scope] })]));
    $("more-btn").hidden = loaded.length >= page.total;
  } catch (err) {
    if (no === requestNo) $("list").replaceChildren(el("div", { class: "paper-body" }, errorNotice(err)));
  } finally {
    $("more-btn").disabled = false;
  }
}

function bankItem(b) {
  const meta = [`${b.itemCount} 道题`, `更新于 ${formatTime(b.updatedAt)}`];
  if (!b.isMine) meta.unshift(`来自 ${b.owner}`);
  if (b.isMine) meta.push(sharingText(b.sharing));
  return el("div", { class: "survey-item lib-item" },
    el("h3", {}, el("a", { href: `/banks/${b.id}`, text: b.name })),
    el("div", { class: "meta", text: meta.join(" · ") }),
    b.description ? el("div", { class: "lib-options", text: b.description }) : null,
    el("div", { class: "actions mt-s" },
      el("a", { class: "btn small ghost", href: `/banks/${b.id}`, text: b.isMine ? "管理题库" : "查看题目" })));
}
