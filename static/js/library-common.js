// 题目库各页面共用的显示工具（第二阶段）。
import { el } from "./layout.js";

/** 版本号标签，如 v3。 */
export function versionBadge(q) {
  return el("span", { class: "badge version", title: "版本号", text: `v${q.version}` });
}

/** 选项摘要：如“男 / 女 / 其他”（太长时截断）。 */
export function optionSummary(q) {
  if (!q.options) return "";
  const text = q.options.map((o) => o.text).join(" / ");
  return text.length > 60 ? `${text.slice(0, 60)}…` : text;
}

/** 共享状态的文字说明（只有所有者能看到共享设置）。 */
export function sharingText(sharing) {
  if (!sharing) return "";
  const parts = [];
  if (sharing.public) parts.push("已公开");
  if (sharing.usernames.length) parts.push(`已共享给 ${sharing.usernames.join("、")}`);
  return parts.length ? parts.join("，") : "未共享";
}

/** 把版本按 parentId 排成树，返回 [{node, depth}]（深度优先，同层按版本号）。 */
export function flattenTree(versions) {
  const byId = new Map(versions.map((v) => [v.id, v]));
  const children = new Map();
  const roots = [];
  for (const v of versions) {
    if (v.parentId && byId.has(v.parentId)) {
      if (!children.has(v.parentId)) children.set(v.parentId, []);
      children.get(v.parentId).push(v);
    } else {
      roots.push(v);
    }
  }
  const out = [];
  const walk = (v, depth) => {
    out.push({ node: v, depth });
    (children.get(v.id) || []).sort((a, b) => a.version - b.version).forEach((c) => walk(c, depth + 1));
  };
  roots.sort((a, b) => a.version - b.version).forEach((r) => walk(r, 0));
  return out;
}

/** “a, b\nc” -> ["a", "b", "c"]（去掉空项）。 */
export function parseUsernames(text) {
  return text.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
}
