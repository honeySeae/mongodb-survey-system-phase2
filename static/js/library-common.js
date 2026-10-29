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

// 校验字段的中文名（版本比较时显示）
const VALIDATION_LABELS = {
  minSelect: "至少选", maxSelect: "最多选", minLength: "最少字数", maxLength: "最多字数",
  min: "最小值", max: "最大值", integerOnly: "只允许整数",
};
const showValue = (key, value) => {
  if (value === undefined || value === null) return "不限";
  if (key === "integerOnly") return value ? "是" : "否";
  return String(value);
};

/**
 * 比较一个版本和它的上一版本（parentId），返回改动说明列表，如
 * ["题目：「你的性别」→「性别」", "选项「女」→「女性」", "新增选项「其他」", "最大值：150 → 120"]。
 * 选项按 id 比较：id 相同、文字不同是“改了文字”（统计时仍合并为同一个选项）。
 */
export function diffVersions(prev, cur) {
  const changes = [];
  if (prev.title !== cur.title) changes.push(`题目：「${prev.title}」→「${cur.title}」`);

  const before = prev.options || [];
  const after = cur.options || [];
  const beforeById = new Map(before.map((o) => [o.id, o]));
  const afterIds = new Set(after.map((o) => o.id));
  for (const o of after) {
    const old = beforeById.get(o.id);
    if (!old) changes.push(`新增选项「${o.text}」`);
    else if (old.text !== o.text) changes.push(`选项「${old.text}」→「${o.text}」`);
  }
  for (const o of before) if (!afterIds.has(o.id)) changes.push(`删除选项「${o.text}」`);
  const kept = after.filter((o) => beforeById.has(o.id)).map((o) => o.id);
  const keptBefore = before.filter((o) => afterIds.has(o.id)).map((o) => o.id);
  if (kept.join() !== keptBefore.join()) changes.push("调整了选项顺序");

  const pv = prev.validation || {};
  const cv = cur.validation || {};
  for (const key of Object.keys(VALIDATION_LABELS)) {
    const a = key === "integerOnly" ? Boolean(pv[key]) : pv[key];
    const b = key === "integerOnly" ? Boolean(cv[key]) : cv[key];
    if (a !== b) changes.push(`${VALIDATION_LABELS[key]}：${showValue(key, a)} → ${showValue(key, b)}`);
  }
  return changes;
}

/** 历史中一个版本的改动说明（一行文字）：与它的上一版本（parentId）比较。 */
export function changeSummary(node, byId) {
  if (!node.accessible) return "";
  if (!node.parentId) return "最初的版本";
  const parent = byId.get(node.parentId);
  if (!parent || !parent.accessible) return "上一版本无权查看，无法比较";
  const changes = diffVersions(parent.detail, node.detail);
  return changes.length ? `与 v${parent.version} 相比：${changes.join("；")}` : `与 v${parent.version} 内容相同`;
}

// ---------- 跨问卷统计（第二阶段） ----------
/** 百分比，保留一位小数（与第一阶段统计页相同：选项次数 ÷ 答卷数）。 */
export function percent(count, total) {
  return total ? Math.round((count / total) * 1000) / 10 : 0;
}

/** 平均值等数字的显示：整数原样，小数保留两位；没有值时为“—”。 */
export function formatNumber(x) {
  if (x === null || x === undefined) return "—";
  return Number.isInteger(x) ? String(x) : x.toFixed(2);
}

/**
 * 筛选条件：全部选中（或一个都没选）时不筛选，返回 null；否则返回选中的 id 列表。
 * 一个都没选时由页面提示“至少选择一项”，不发请求。
 */
export function filterParam(selected, all) {
  if (!selected.length || selected.length === all.length) return null;
  return selected;
}
