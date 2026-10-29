// 问卷编辑页的第二阶段功能：换版本、题目来源标签（“从题目库添加”的面板见 library-picker.js）。
// 面板像题目编辑器一样就地展开在题目列表中（接口：{ element, isDirty, focus }），由 edit.js 管理。
import { api } from "./api.js";
import { el, errorNotice } from "./layout.js";
import { diffVersions, versionBadge } from "./library-common.js";

/** 题目来源标签：“题目库 v2”，点击在新标签页打开该版本。 */
export function sourceBadge(q) {
  return el("a", { class: "badge version source", href: `/questions/${q.source.questionId}`, target: "_blank",
                   title: "这道题来自题目库，点击查看该版本", text: `题目库 v${q.source.version}` });
}

/** 问卷中一道来自题目库的题当前的内容（不含是否必答），用于和其他版本比较。 */
function contentOf(q) {
  const validation = { ...(q.validation || {}) };
  delete validation.required;
  return { title: q.title, options: q.options, validation };
}

/**
 * 换版本的面板：列出同一道题自己能访问的其他版本，并说明与当前内容相比改了什么。
 * @param {object} opts  question（问卷中的题）、number（题号）；onSwitch(versionId) 返回 Promise；onCancel()
 */
export function createSwitchPanel(opts) {
  const q = opts.question;
  const message = el("div");
  const list = el("div", { class: "pick-list" }, el("div", { class: "muted", text: "加载中…" }));
  const element = el("div", { class: "question editing library-picker" },
    el("div", { class: "editor-head", text: `第 ${opts.number} 题换版本（当前 v${q.source.version}）` }),
    el("div", { class: "muted", text: "换版本后保留题目在问卷中的位置、是否必答和跳转规则；跳转规则用到的选项在新版本中不存在时不能换。" }),
    message, list,
    el("div", { class: "actions mt" },
      el("button", { class: "btn link muted", type: "button", text: "取消", onclick: () => opts.onCancel() })));

  (async () => {
    let history;
    try {
      history = await api("GET", `/api/questions/${q.source.questionId}/history`);
    } catch (err) {
      list.replaceChildren(errorNotice(err.status === 404
        ? { message: "这道题的来源版本已不再共享给你，无法换版本" } : err));
      return;
    }
    const current = contentOf(q);
    const others = history.versions.filter((v) => v.accessible && v.id !== q.source.questionId)
      .sort((a, b) => b.version - a.version);
    if (!others.length) {
      list.replaceChildren(el("div", { class: "muted" }, "这道题没有其他可用的版本。可以到",
        el("a", { href: `/questions/${q.source.questionId}`, target: "_blank", text: "题目库" }), "创建新版本。"));
      return;
    }
    list.replaceChildren(...others.map((v) => {
      const changes = diffVersions(current, v.detail);
      const btn = el("button", { class: "btn small", type: "button", text: "换成这个版本", onclick: async () => {
        btn.disabled = true;
        try {
          await opts.onSwitch(v.id);
        } catch (err) {
          message.replaceChildren(errorNotice(err));
          btn.disabled = false;
        }
      } });
      return el("div", { class: "pick-row" },
        el("div", { class: "pick-main" },
          el("div", { class: "pick-title" }, el("span", { text: v.detail.title }), versionBadge(v),
            v.version > q.source.version ? el("span", { class: "muted", text: "较新" }) : el("span", { class: "muted", text: "较旧" }),
            el("a", { href: `/questions/${v.id}`, target: "_blank", class: "muted", text: "查看" })),
          el("div", { class: "muted", text: `${v.detail.isMine ? "我的" : v.detail.owner} · ` +
            (changes.length ? `与当前相比：${changes.join("；")}` : "与当前内容相同") })),
        el("div", { class: "pick-controls" }, btn));
    }));
  })();

  return { element, isDirty: () => false, focus: () => {} };
}
