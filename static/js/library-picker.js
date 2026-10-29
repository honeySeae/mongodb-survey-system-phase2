// 从题目库选题的面板（第二阶段）：问卷编辑页“从题目库添加”、题库页“加入题目”共用。
// 就地展开在列表中（接口：{ element, isDirty, focus }）。
// 标签：我的题目 / 共享给我的 / 公开的（按题目分组，可选版本）；问卷编辑页另有“题库”（从可访问的题库中选题）。
import { api, withQuery } from "./api.js";
import { el, errorNotice } from "./layout.js";
import { optionSummary, versionBadge } from "./library-common.js";
import { TYPE_LABELS } from "./render.js";

const PAGE_SIZE = 10;
const QUESTION_SCOPES = [["mine", "我的题目"], ["shared", "共享给我的"], ["public", "公开的"]];

/**
 * @param {object} opts
 *   title、intro      面板标题和说明
 *   usedRoots         已使用的题目（rootId 集合）：同一道题不能重复加入
 *   usedText          已使用时按钮上的文字，如“已在问卷中”
 *   usedTitle         已使用时按钮的提示
 *   addText           加入按钮的文字
 *   showRequired      是否显示“必答”勾选框（问卷编辑页显示，题库页不显示）
 *   showBanks         是否显示“题库”标签
 *   onAdd(questionId, required)  返回 Promise；出错时抛出，由面板显示
 *   onCancel()
 */
export function createLibraryPicker(opts) {
  const usedRoots = opts.usedRoots;
  const scopes = opts.showBanks ? [...QUESTION_SCOPES, ["banks", "题库"]] : QUESTION_SCOPES;
  let scope = "mine";
  let loaded = [];
  let total = 0;
  let requestNo = 0;   // 切换标签时，只采用最后一次请求的结果（较早的请求可能更晚返回）

  const message = el("div");
  const list = el("div", { class: "pick-list" });
  const more = el("button", { class: "btn small ghost", type: "button", text: "加载更多", hidden: true,
                              onclick: () => load(false) });
  const tabs = el("div", { class: "seg", role: "tablist" }, scopes.map(([value, label]) =>
    el("button", { type: "button", class: value === scope ? "active" : null, dataset: { scope: value }, text: label,
                   onclick: (e) => {
                     if (scope === value) return;
                     scope = value;
                     tabs.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === e.target));
                     load(true);
                   } })));
  const element = el("div", { class: "question editing library-picker" },
    el("div", { class: "editor-head", text: opts.title }),
    el("div", { class: "muted", text: opts.intro }),
    tabs, message, list,
    el("div", { class: "actions mt" }, more,
      el("button", { class: "btn link muted", type: "button", text: "关闭", onclick: () => opts.onCancel() })));

  async function load(reset) {
    if (reset) { loaded = []; list.replaceChildren(el("div", { class: "muted", text: "加载中…" })); }
    message.replaceChildren();
    const no = ++requestNo;
    try {
      const page = scope === "banks"
        ? await api("GET", withQuery("/api/banks", { scope: "all", offset: loaded.length, limit: PAGE_SIZE }))
        : await api("GET", withQuery("/api/questions/groups", { scope, offset: loaded.length, limit: PAGE_SIZE }));
      if (no !== requestNo) return;
      loaded = loaded.concat(page.items);
      total = page.total;
      const rows = scope === "banks" ? loaded.map(bankRow) : loaded.map(groupRow);
      list.replaceChildren(...(rows.length ? rows : [el("div", { class: "muted", text: emptyText() })]));
      more.hidden = loaded.length >= total;
    } catch (err) {
      if (no === requestNo) list.replaceChildren(errorNotice(err));
    }
  }

  function emptyText() {
    return { mine: "题目库中还没有你的题目", shared: "还没有人把题目共享给你", public: "还没有别人公开的题目",
             banks: "还没有可用的题库" }[scope];
  }

  /** 加入按钮 + 必答勾选框；used 时不可点。 */
  function controls(rootId, getQuestionId, extra = null) {
    const used = usedRoots.has(rootId);
    const required = el("input", { type: "checkbox", checked: true, disabled: used });
    const addBtn = el("button", { class: "btn small", type: "button", text: used ? opts.usedText : opts.addText,
      disabled: used, title: used ? opts.usedTitle : null,
      onclick: async () => {
        addBtn.disabled = true;
        try {
          await opts.onAdd(getQuestionId(), required.checked);
        } catch (err) {
          message.replaceChildren(errorNotice(err));
          addBtn.disabled = false;
        }
      } });
    return { used, node: el("div", { class: "pick-controls" }, extra,
      opts.showRequired ? el("label", { class: "check" }, required, "必答") : null, addBtn) };
  }

  function questionInfo(q, ownerText) {
    const meta = [TYPE_LABELS[q.type] || q.type];
    if (ownerText) meta.push(ownerText);
    const summary = optionSummary(q);
    return el("div", { class: "pick-main" },
      el("div", { class: "pick-title" }, el("span", { text: q.title }), versionBadge(q),
        el("a", { href: `/questions/${q.id}`, target: "_blank", class: "muted", text: "查看" })),
      el("div", { class: "muted", text: [meta.join(" · "), summary].filter(Boolean).join(" · ") }));
  }

  // 题目：一道题一行，可选版本（默认版本号最大的）
  function groupRow(group) {
    const q = group.latest;
    const used = usedRoots.has(group.rootId);
    const versionSelect = el("select", { "aria-label": "选择版本", disabled: used },
      [...group.versions].reverse().map((v) => el("option", { value: v.id, selected: v.id === q.id,
        text: `v${v.version}${v.id === q.id ? "（最新）" : ""}${q.isMine ? "" : ` · ${v.owner}`}` })));
    const c = controls(group.rootId, () => versionSelect.value, group.versions.length > 1 ? versionSelect : null);
    return el("div", { class: `pick-row${c.used ? " used" : ""}` },
      questionInfo(q, q.isMine ? "" : `来自 ${q.owner}`), c.node);
  }

  // 题库：一个题库一行，点开后列出其中可用的题（题库中的每一项是固定的版本）
  function bankRow(bank) {
    const items = el("div", { class: "pick-bank-items", hidden: true });
    const toggle = el("button", { class: "btn small ghost", type: "button", text: "展开", onclick: async () => {
      if (!items.hidden) { items.hidden = true; toggle.textContent = "展开"; return; }
      items.hidden = false;
      toggle.textContent = "收起";
      items.replaceChildren(el("div", { class: "muted", text: "加载中…" }));
      try {
        const detail = await api("GET", `/api/banks/${bank.id}`);
        const rows = detail.items.map((item) => {
          if (!item.available) {
            return el("div", { class: "pick-row used" },
              el("div", { class: "pick-main muted", text: "这一项不可用（原作者已取消共享）" }));
          }
          const c = controls(item.rootId, () => item.questionId);
          return el("div", { class: `pick-row${c.used ? " used" : ""}` },
            questionInfo(item.question, item.question.isMine ? "" : `来自 ${item.question.owner}`), c.node);
        });
        items.replaceChildren(...(rows.length ? rows : [el("div", { class: "muted", text: "这个题库还没有题目" })]));
      } catch (err) {
        items.replaceChildren(errorNotice(err));
      }
    } });
    return el("div", { class: "pick-bank" },
      el("div", { class: "pick-row" },
        el("div", { class: "pick-main" },
          el("div", { class: "pick-title" }, el("span", { text: bank.name }),
            el("span", { class: "muted", text: `${bank.itemCount} 道题${bank.isMine ? "" : ` · 来自 ${bank.owner}`}` })),
          bank.description ? el("div", { class: "muted", text: bank.description }) : null),
        el("div", { class: "pick-controls" }, toggle)),
      items);
  }

  load(true);
  return { element, isDirty: () => false, focus: () => tabs.querySelector("button")?.focus() };
}
