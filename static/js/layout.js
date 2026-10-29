// 公共界面工具：创建元素、顶部导航、提示、时间格式、状态标签、复制链接。
// 安全：用户提供的内容一律通过 textContent 显示，从不拼接进 innerHTML，防止 XSS。

import { clearAuth, getUser } from "./api.js";

/**
 * 创建元素。attrs 中：class、text（纯文本内容）、on<事件>（事件处理）、dataset、
 * 其他键作为属性；值为 false/null/undefined 的属性不设置。children 中的字符串作为文本节点。
 */
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value === null || value === undefined) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "value") node.value = value;
    else if (key === "checked" || key === "disabled" || key === "selected") node[key] = Boolean(value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** 顶部导航：品牌、我的问卷、题目库（第二阶段）、当前用户和退出。 */
export function renderTopbar(active = "") {
  const user = getUser();
  const bar = el("header", { class: "topbar" },
    el("a", { class: "brand", href: "/surveys", text: "问卷" }),
    el("nav", {},
      el("a", { href: "/surveys", class: active === "surveys" ? "active" : null, text: "我的问卷" }),
      el("a", { href: "/questions", class: active === "questions" ? "active" : null, text: "题目库" }),
    ),
    user
      ? el("div", { class: "user" },
          el("span", { text: user.username }),
          el("button", { class: "btn link", type: "button", text: "退出", onclick: logout }))
      : el("div", { class: "user" }, el("a", { href: "/login", text: "登录" })),
  );
  document.body.prepend(bar);
}

export function logout() {
  clearAuth();
  location.href = "/login";
}

let toastTimer = null;
/** 底部短暂提示。 */
export function toast(message, kind = "info") {
  document.querySelectorAll(".toast").forEach((t) => t.remove());
  const node = el("div", { class: `toast ${kind === "error" ? "error" : ""}`, role: "status", text: message });
  document.body.append(node);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.remove(), 3000);
}

/** 错误提示块：主信息 + 字段错误列表。 */
export function errorNotice(err) {
  const box = el("div", { class: "notice error", role: "alert" }, el("div", { text: err.message || "操作失败" }));
  const items = (err.errors || []).filter((e) => e.message && e.message !== err.message);
  if (items.length) box.append(el("ul", {}, items.map((e) => el("li", { text: e.message }))));
  return box;
}

/** ISO 时间 -> 本地时间文字（如 2026/11/30 23:59）。 */
export function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit",
                                     hour: "2-digit", minute: "2-digit", hour12: false });
}

export const POLICY_LABELS = {
  once: "每人只能填一次",
  latest: "可以重填，以最后一次为准",
  all: "可多次填写，每次都算",
};

/** 状态标签：草稿 / 收集中 / 已截止 / 已关闭。 */
export function statusBadge(survey) {
  if (survey.status === "draft") return el("span", { class: "badge draft", text: "草稿" });
  if (survey.status === "closed") return el("span", { class: "badge closed", text: "已关闭" });
  if (survey.isExpired) return el("span", { class: "badge expired", text: "已截止" });
  return el("span", { class: "badge published", text: "收集中" });
}

/** 复制文字；非安全上下文（如部署后用 http + IP 访问）没有剪贴板接口时退回旧方法。 */
export async function copyText(text, inputForFallback) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* 改用下面的方法 */ }
  if (inputForFallback) {
    inputForFallback.select();
    try { return document.execCommand("copy"); } catch { return false; }
  }
  return false;
}

/** 链接框：只读输入框 + 复制按钮。 */
export function linkBox(url) {
  const input = el("input", { value: url, readonly: true, "aria-label": "问卷链接", onclick: (e) => e.target.select() });
  const btn = el("button", {
    class: "btn small ghost", type: "button", text: "复制",
    onclick: async () => toast((await copyText(url, input)) ? "链接已复制" : "请手动复制链接"),
  });
  return el("div", { class: "link-box" }, input, btn);
}

/**
 * 让容器内的 .option（整行可点的单选/多选行）在选中时高亮：根据其中 input 的选中状态切换 is-checked。
 * 填写页、编辑页的题目选项也使用同一机制。
 */
export function bindOptionHighlight(container) {
  const sync = () => {
    container.querySelectorAll(".option").forEach((row) => {
      const input = row.querySelector("input");
      row.classList.toggle("is-checked", Boolean(input && input.checked));
    });
  };
  container.addEventListener("change", sync);
  sync();
  return sync;
}

/** 读取当前地址中的查询参数。 */
export function queryParam(name) {
  return new URLSearchParams(location.search).get(name);
}

/** 当前路径的第 n 段（从 0 开始），如 /surveys/<id>/edit 的第 1 段是 id。 */
export function pathSegment(n) {
  return decodeURIComponent(location.pathname.split("/").filter(Boolean)[n] || "");
}
