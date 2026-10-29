// 界面测试（第二阶段 10b 问卷编辑页 × 我的题目）：从我的题目添加（选版本、必答）、同一道题不能重复添加、
// 来自已保存题目的题只能改必答和跳转、换版本（显示与当前相比改了什么）、存入我的题目（草稿和已发布问卷）、
// 被共享的人从“共享给我的”中添加、手机尺寸。
import { scenario } from "./helpers.mjs";

await scenario("问卷编辑页 × 我的题目", async (t) => {
  const { browser: b, assert } = t;
  const ok = (r, status = 200) => { assert.equal(r.status, status, JSON.stringify(r.body)); return r.body; };
  const questionCount = (n) => b.waitFor(`document.querySelectorAll("#questions > .question:not(.editing)").length === ${n}`,
    `显示 ${n} 道题`);

  await t.api("POST", "/api/auth/register", { username: "ui_el_bob", password: "uitest123" });
  const alice = await t.login("ui_el_alice");
  // 我的题目：v1（男、女）→ v2（女 改为 女性，新增 其他）
  const v1 = ok(await t.api("POST", "/api/questions", { type: "single_choice", title: "性别",
    options: [{ text: "男" }, { text: "女" }] }, alice), 201);
  const v2 = ok(await t.api("POST", `/api/questions/${v1.id}/versions`, { type: "single_choice", title: "性别",
    options: [v1.options[0], { id: v1.options[1].id, text: "女性" }, { text: "其他" }] }, alice), 201);
  const survey = ok(await t.api("POST", "/api/surveys", { title: "年度调查" }, alice), 201);
  await b.goto(`${t.base}/surveys/${survey.id}/edit`);
  await b.waitFor(`document.querySelector("#questions .empty")`, "空问卷");

  // ---------- 从我的题目添加 ----------
  assert.ok((await t.texts("#add-bar button")).includes("从已有题目添加"));
  await t.click("#add-bar button", "从已有题目添加");
  await b.waitFor(`document.querySelectorAll(".library-picker .pick-row").length === 1`, "我的题目中的题");
  assert.deepEqual(await b.eval(`[...document.querySelectorAll(".library-picker select option")].map((o) => o.textContent)`),
    ["v2（最新）", "v1"]);
  t.step("“从我的题目添加”：按题目列出（同一道题一项），可以选择版本，默认最新");
  await t.shot("从已有题目添加");
  await b.eval(`(() => { const s = document.querySelector(".library-picker select"); s.value = ${JSON.stringify(v1.id)}; return true; })()`);
  await t.click(".library-picker .pick-row button", "添加");
  await questionCount(1);
  assert.equal(await t.text("#questions .question .badge.source"), "来源 v1");
  assert.deepEqual(await t.texts("#questions .question .option"), ["男", "女"]);
  assert.equal(await b.eval(`Boolean(document.querySelector("#questions .question .q-required"))`), true);
  t.step("选择 v1 添加：题目显示“来源 v1”标签，默认必答");

  await t.click("#add-bar button", "从已有题目添加");
  await b.waitFor(`document.querySelector(".library-picker .pick-row button")?.textContent === "已在问卷中"`, "已在问卷中");
  assert.equal(await b.eval(`document.querySelector(".library-picker .pick-row button").disabled`), true);
  await t.click(".library-picker button", "关闭");
  t.step("同一道题再次添加时按钮显示“已在问卷中”并不可点");

  // ---------- 编辑：只能改必答和跳转 ----------
  await t.click(".q-tools button", "编辑");
  await b.waitFor(`document.querySelector(".question.editing [data-field=title]")`, "编辑器");
  assert.equal(await b.eval(`document.querySelector(".question.editing [data-field=title]").disabled`), true);
  assert.equal(await b.eval(`document.querySelector(".question.editing [data-field='options[0].text']").disabled`), true);
  assert.equal(await b.eval(`document.querySelector(".question.editing [data-field=type]").disabled`), true);
  assert.ok((await t.text(".question.editing .notice.info")).includes("来自已保存的题目（v1）"));
  assert.ok(!(await t.texts(".question.editing button")).includes("＋ 添加选项"));
  await b.eval(`(() => { const c = [...document.querySelectorAll(".question.editing .option.checkbox input")][0];
    c.click(); return true; })()`);   // 取消“必答”
  await t.click(".question.editing button", "保存");
  await b.waitFor(`!document.querySelector(".question.editing")`, "保存完成");
  assert.equal(await b.eval(`Boolean(document.querySelector("#questions .question .q-required"))`), false);
  assert.equal(await t.text("#questions .question .badge.source"), "来源 v1");
  t.step("编辑来自已保存题目的题：题型、题目、选项不可编辑并有说明；可以改是否必答");
  await t.shot("来自已保存题目的题的编辑器");

  // ---------- 换版本 ----------
  await t.click(".q-tools button", "换版本");
  await b.waitFor(`document.querySelectorAll(".library-picker .pick-row").length === 1`, "可换的版本");
  const diff = await t.text(".library-picker .pick-row .pick-main > .muted");
  assert.ok(diff.includes("选项「女」→「女性」") && diff.includes("新增选项「其他」"), diff);
  t.step("换版本：列出 v2（较新），说明与当前相比改了什么");
  await t.shot("换版本");
  await t.click(".library-picker .pick-row button", "换成这个版本");
  await b.waitFor(`document.querySelector("#questions .question .badge.source")?.textContent === "来源 v2"`, "换成 v2");
  assert.deepEqual(await t.texts("#questions .question .option"), ["男", "女性", "其他"]);
  assert.equal(await b.eval(`Boolean(document.querySelector("#questions .question .q-required"))`), false, "保留是否必答");
  t.step("换成 v2：内容更新，保留“非必答”设置");

  // ---------- 存入我的题目（草稿） ----------
  ok(await t.api("POST", `/api/surveys/${survey.id}/questions`, { type: "number", title: "你的年龄",
    validation: { required: true, min: 0, max: 150, integerOnly: true } }, alice), 201);
  ok(await t.api("POST", `/api/surveys/${survey.id}/questions`, { type: "text", title: "备注" }, alice), 201);
  await b.goto(`${t.base}/surveys/${survey.id}/edit`);
  await questionCount(3);
  await b.eval("window.confirm = () => true; true");
  await b.eval(`document.querySelectorAll(".q-tools")[1].querySelector("button:last-child").click(); true`);
  await b.waitFor(`document.querySelectorAll("#questions .badge.source").length === 2`, "第 2 题存入我的题目");
  assert.equal(await b.eval(`document.querySelectorAll(".question")[1].querySelector(".badge.source").textContent`), "来源 v1");
  assert.equal(await b.eval(`document.querySelectorAll(".q-tools")[1].querySelector("button:last-child").textContent`), "换版本");
  t.step("草稿中把直接建的题“存入我的题目”：出现“来源 v1”标签，之后可以换版本");

  // ---------- 发布后：题目不能改，但直接建的题仍可存入我的题目 ----------
  ok(await t.api("POST", `/api/surveys/${survey.id}/publish`, undefined, alice));
  await b.goto(`${t.base}/surveys/${survey.id}/edit`);
  await questionCount(3);
  assert.equal(await b.eval(`document.querySelectorAll(".q-tools").length`), 0);
  assert.deepEqual(await t.texts(".q-lib-tools button"), ["存入我的题目"]);   // 只有“备注”没有来源
  await b.eval("window.confirm = () => true; true");
  await t.click(".q-lib-tools button", "存入我的题目");
  await b.waitFor(`document.querySelectorAll("#questions .badge.source").length === 3`, "已发布问卷存入我的题目");
  assert.equal(await b.eval(`document.querySelectorAll(".q-lib-tools").length`), 0);
  t.step("已发布问卷：没有编辑工具；直接建的题仍可存入我的题目（只补来源，不改内容）");
  await t.shot("已发布问卷");

  await b.goto(`${t.base}/questions`);
  await b.waitFor(`document.querySelectorAll("#list .lib-item").length === 3`, "我的题目中 3 道题");
  t.step("我的题目中出现存入的“你的年龄”“备注”和原有的“性别”");

  // ---------- 被共享的人从“共享给我的”中添加 ----------
  ok(await t.api("PUT", `/api/questions/${v1.id}/sharing`, { public: false, usernames: ["ui_el_bob"] }, alice));
  await t.logout();
  const bob = await t.login("ui_el_bob");
  const bobSurvey = ok(await t.api("POST", "/api/surveys", { title: "bob 的问卷" }, bob), 201);
  await b.goto(`${t.base}/surveys/${bobSurvey.id}/edit`);
  await b.waitFor(`document.querySelector("#questions .empty")`, "空问卷");
  await t.click("#add-bar button", "从已有题目添加");
  await b.waitFor(`document.querySelector(".library-picker .muted")`, "面板");
  await t.click(".library-picker .seg button", "共享给我的");
  await b.waitFor(`document.querySelectorAll(".library-picker .pick-row").length === 1`, "共享给我的题");
  assert.ok((await t.text(".library-picker .pick-row")).includes("来自 ui_el_alice"));
  await t.click(".library-picker .pick-row button", "添加");
  await questionCount(1);
  assert.equal(await t.text("#questions .question .badge.source"), "来源 v2");
  t.step("被共享的人在“共享给我的”中选题加入自己的问卷");

  await b.size(390, 844);
  await t.click("#add-bar button", "从已有题目添加");
  await t.click(".library-picker .seg button", "共享给我的");
  await b.waitFor(`document.querySelector(".library-picker .pick-row")`, "手机尺寸的面板");
  assert.equal(await b.eval("document.documentElement.scrollWidth > window.innerWidth"), false, "手机尺寸下不应出现横向滚动");
  t.step("手机尺寸下“从我的题目添加”面板没有横向滚动");
  await t.shot("手机尺寸");
});
