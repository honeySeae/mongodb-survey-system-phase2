// 第二阶段题目库页面的纯函数测试（不需要浏览器）。由 tests/test_frontend_js.py 调用。
import assert from "node:assert/strict";
import { flattenTree, optionSummary, parseUsernames, sharingText } from "../../static/js/library-common.js";
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

console.log("ok");
