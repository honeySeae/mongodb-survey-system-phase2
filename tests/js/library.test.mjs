// 第二阶段题目库页面的纯函数测试（不需要浏览器）。由 tests/test_frontend_js.py 调用。
import assert from "node:assert/strict";
import { changeSummary, diffVersions, filterParam, flattenTree, formatNumber, optionSummary, parseUsernames, percent,
         sharingText } from "../../static/js/library-common.js";
import { buildBody, toValidationValue } from "../../static/js/library-editor.js";

// 版本树：按 parentId 缩进；同层按版本号；父版本不可见时作为根
const v = (id, version, parentId = null) => ({ id, version, parentId });
const tree = flattenTree([v("a", 1), v("b", 2, "a"), v("c", 3, "a"), v("d", 4, "b"), v("e", 5, "zz")]);
assert.deepEqual(tree.map((t) => [t.node.id, t.depth]), [["a", 0], ["b", 1], ["d", 2], ["c", 1], ["e", 0]]);
assert.deepEqual(flattenTree([]), []);

// 用户名：逗号（中英文）、空格、换行都可以分隔
assert.deepEqual(parseUsernames("bob, carol，dave\n  eve  "), ["bob", "carol", "dave", "eve"]);
assert.deepEqual(parseUsernames("  "), []);

// 共享状态说明
assert.equal(sharingText({ public: false, userIds: [], usernames: [] }), "未共享");
assert.equal(sharingText({ public: true, userIds: ["1"], usernames: ["bob"] }), "已公开，已共享给 bob");
assert.equal(sharingText(null), "");

// 选项摘要
assert.equal(optionSummary({ options: [{ text: "男" }, { text: "女" }] }), "男 / 女");
assert.equal(optionSummary({ type: "text" }), "");
assert.ok(optionSummary({ options: Array.from({ length: 30 }, (_, i) => ({ text: `选项${i}` })) }).endsWith("…"));

// 校验值：空为不设置；数字转为数字；非法内容原样交给后端报错
assert.equal(toValidationValue(""), undefined);
assert.equal(toValidationValue(" 3 "), 3);
assert.equal(toValidationValue("1.5"), 1.5);
assert.equal(toValidationValue("abc"), "abc");

// 请求体：不含 required；选择题保留已有选项 id、新增选项不带 id；数字题“只允许整数”
assert.deepEqual(buildBody({ type: "single_choice", title: "性别", validation: {}, integerOnly: false,
                             options: [{ id: "o_1", text: "男" }, { text: "女" }] }),
                 { type: "single_choice", title: "性别", validation: {}, options: [{ id: "o_1", text: "男" }, { text: "女" }] });
assert.deepEqual(buildBody({ type: "number", title: "年龄", validation: { min: "0", max: "" }, integerOnly: true, options: [] }),
                 { type: "number", title: "年龄", validation: { min: 0, integerOnly: true } });
assert.deepEqual(buildBody({ type: "text", title: "建议", validation: { maxLength: "100", min: "5" }, integerOnly: true, options: [{ text: "x" }] }),
                 { type: "text", title: "建议", validation: { maxLength: 100 } });   // 不属于该题型的字段和选项不提交

// 版本比较：题目、选项（按 id：改文字、新增、删除、调整顺序）、校验规则
const base = { title: "你的性别", options: [{ id: "a", text: "男" }, { id: "b", text: "女" }, { id: "c", text: "保密" }],
               validation: { min: 0, max: 150, integerOnly: true } };
assert.deepEqual(diffVersions(base, base), []);
assert.deepEqual(diffVersions(base, {
  title: "性别", options: [{ id: "b", text: "女性" }, { id: "a", text: "男" }, { id: "d", text: "其他" }],
  validation: { min: 0, max: 120 } }), [
  "题目：「你的性别」→「性别」",
  "选项「女」→「女性」",
  "新增选项「其他」",
  "删除选项「保密」",
  "调整了选项顺序",
  "最大值：150 → 120",
  "只允许整数：是 → 否",
]);
assert.deepEqual(diffVersions({ title: "建议", validation: {} }, { title: "建议", validation: { maxLength: 100 } }),
                 ["最多字数：不限 → 100"]);

// 历史中的改动说明：与上一版本比较；最初版本、上一版本无权查看、内容相同
const node = (id, version, parentId, detail, accessible = true) => ({ id, version, parentId, detail, accessible });
const n1 = node("1", 1, null, base);
const n2 = node("2", 2, "1", { ...base, title: "性别" });
const n3 = node("3", 3, "2", { ...base, title: "性别" });
const hidden = node("4", 4, "1", null, false);
const n5 = node("5", 5, "4", base);
const byId = new Map([n1, n2, n3, hidden, n5].map((n) => [n.id, n]));
assert.equal(changeSummary(n1, byId), "最初的版本");
assert.equal(changeSummary(n2, byId), "与 v1 相比：题目：「你的性别」→「性别」");
assert.equal(changeSummary(n3, byId), "与 v2 内容相同");
assert.equal(changeSummary(n5, byId), "上一版本无权查看，无法比较");
assert.equal(changeSummary(hidden, byId), "");

// 跨问卷统计：百分比、数字显示、筛选条件（全部选中或都没选时不筛选）
assert.equal(percent(1, 3), 33.3);
assert.equal(percent(0, 0), 0);
assert.equal(formatNumber(30), "30");
assert.equal(formatNumber(3.3333), "3.33");
assert.equal(formatNumber(null), "—");
assert.equal(filterParam(["a", "b"], ["a", "b"]), null);
assert.equal(filterParam([], ["a", "b"]), null);
assert.deepEqual(filterParam(["a"], ["a", "b"]), ["a"]);

console.log("ok");
