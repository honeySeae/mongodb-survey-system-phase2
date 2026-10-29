// 界面测试（第二阶段 10d 跨问卷统计页）：从题目详情进入；合并后的结果（问卷数、答卷数、跨问卷去重的作答人数、
// 选项按 id 合并、“仅出现在旧版本中”）；各问卷的结果；按问卷、按版本筛选（最新版本以参与统计的版本为准）；
// 数字题平均值与内容列表（附问卷标题、不显示填写人）；手机尺寸。
//
// 固定数据：性别 v1（男、女、保密）→ v2（女 改为 女性，删掉 保密，新增 其他）；年龄 v1
//   去年（once，用 v1）：bob 保密、20 岁；carol 男、30 岁
//   今年（all， 用 v2）：bob 女性、21 岁；carol 其他、31 岁；bob 再交一次 女性、21 岁
//   合并：男 1、女性 2、其他 1、保密 1（仅旧版本）；答卷 5、作答人数 2；年龄平均 (20+30+21+31+21)/5 = 24.6
import { scenario } from "./helpers.mjs";

await scenario("跨问卷统计页", async (t) => {
  const { browser: b, assert } = t;
  const ok = (r, status = 200) => { assert.equal(r.status, status, JSON.stringify(r.body)); return r.body; };
  const register = async (name) => {
    await t.api("POST", "/api/auth/register", { username: name, password: "uitest123" });
    return (await t.api("POST", "/api/auth/login", { username: name, password: "uitest123" })).body.accessToken;
  };
  const bob = await register("ui_cs_bob");
  const carol = await register("ui_cs_carol");
  const alice = await t.login("ui_cs_alice");

  const g1 = ok(await t.api("POST", "/api/questions", { type: "single_choice", title: "性别",
    options: [{ text: "男" }, { text: "女" }, { text: "保密" }] }, alice), 201);
  const [male, female, secret] = g1.options;
  const g2 = ok(await t.api("POST", `/api/questions/${g1.id}/versions`, { type: "single_choice", title: "性别",
    options: [male, { id: female.id, text: "女性" }, { text: "其他" }] }, alice), 201);
  const other = g2.options[2];
  const age = ok(await t.api("POST", "/api/questions", { type: "number", title: "年龄",
    validation: { min: 0, max: 150, integerOnly: true } }, alice), 201);

  const makeSurvey = async (title, policy, genderVersion) => {
    const s = ok(await t.api("POST", "/api/surveys", { title, submissionPolicy: policy }, alice), 201);
    ok(await t.api("POST", `/api/surveys/${s.id}/questions/from-library`, { questionId: genderVersion, required: true }, alice), 201);
    const full = ok(await t.api("POST", `/api/surveys/${s.id}/questions/from-library`, { questionId: age.id, required: true }, alice), 201);
    ok(await t.api("POST", `/api/surveys/${s.id}/publish`, undefined, alice));
    return { ...s, q: full.questions.map((q) => q.id) };
  };
  const submit = async (s, token, gender, years) => ok(await t.api("POST", `/api/s/${s.shortCode}/responses`,
    { answers: [{ questionId: s.q[0], value: gender }, { questionId: s.q[1], value: years }] }, token), 201);
  const lastYear = await makeSurvey("去年", "once", g1.id);
  const thisYear = await makeSurvey("今年", "all", g2.id);
  await submit(lastYear, bob, secret.id, 20);
  await submit(lastYear, carol, male.id, 30);
  await submit(thisYear, bob, female.id, 21);
  await submit(thisYear, carol, other.id, 31);
  await submit(thisYear, bob, female.id, 21);

  // ---------- 从题目详情进入 ----------
  await b.goto(`${t.base}/questions/${g2.id}`);
  await b.waitFor(`!document.getElementById("content").hidden`, "题目详情");
  await t.click("#stats-link");
  await b.waitFor(`!document.getElementById("content").hidden && document.querySelectorAll("#surveys .cross-survey").length === 2`, "跨问卷统计");
  assert.equal(await t.location(), `/questions/${g2.id}/stats`);
  assert.equal(await t.text("#title"), "「性别」跨问卷统计");
  t.step("从题目详情页点“跨问卷统计”进入");

  // ---------- 合并后的结果 ----------
  assert.deepEqual(await t.texts("#totals .stat-number"), ["2问卷数", "5答卷数", "2作答人数"]);
  assert.deepEqual(await t.texts("#overall .bar-label"), ["男", "女性", "其他", "保密仅出现在旧版本中"]);
  assert.deepEqual(await t.texts("#overall .bar-value"), ["1 人（20%）", "2 人（40%）", "1 人（20%）", "1 人（20%）"]);
  t.step("合并：2 份问卷、5 份答卷、作答人数 2（跨问卷去重）；选项按 id 合并，“女”显示为最新的“女性”；只在旧版本中的“保密”照常计数并标注");
  await t.shot("合并后的结果");

  // 各问卷的结果：用各自的选项
  const cards = await t.texts("#surveys .cross-survey .q-title");
  assert.ok(cards[0].includes("今年") && cards[0].includes("v2") && cards[1].includes("去年") && cards[1].includes("v1"), cards);
  assert.deepEqual(await t.texts("#surveys .cross-survey:nth-child(1) .bar-label"), ["男", "女性", "其他"]);
  assert.ok((await t.text("#surveys .cross-survey:nth-child(1) .q-hint")).includes("答卷数 3 · 作答人数 2"));
  assert.deepEqual(await t.texts("#surveys .cross-survey:nth-child(2) .bar-label"), ["男", "女", "保密"]);
  t.step("各问卷的结果：今年 v2（答卷 3、作答人数 2）、去年 v1，各用自己的选项文字");

  // ---------- 按问卷筛选 ----------
  const toggle = (label) => b.eval(`(() => { const box = [...document.querySelectorAll("#filters label.check")]
    .find((l) => l.textContent.trim() === ${JSON.stringify(label)}).querySelector("input"); box.click(); return true; })()`);
  await toggle("今年");
  await b.waitFor(`document.querySelectorAll("#surveys .cross-survey").length === 1`, "只剩去年");
  assert.deepEqual(await t.texts("#totals .stat-number"), ["1问卷数", "2答卷数", "2作答人数"]);
  assert.deepEqual(await t.texts("#overall .bar-label"), ["男", "女", "保密"]);   // 只有 v1 参与：不标注“仅旧版本”
  t.step("只看“去年”：合并结果只含 v1，“保密”不再标注“仅出现在旧版本中”（最新版本以参与统计的版本为准）");

  await toggle("去年");
  await b.waitFor(`document.querySelector("#message .notice.warn")`, "至少选一项的提示");
  assert.ok((await t.text("#message")).includes("至少要选择一项"));
  await toggle("去年");
  await toggle("今年");
  await b.waitFor(`document.querySelectorAll("#surveys .cross-survey").length === 2 && !document.querySelector("#message .notice")`, "恢复全部");

  // ---------- 按版本筛选 ----------
  await toggle("v1");
  await b.waitFor(`document.querySelectorAll("#surveys .cross-survey").length === 1`, "只剩 v2");
  assert.ok((await t.text("#surveys .cross-survey .q-title")).includes("今年"));
  await toggle("v1");
  await b.waitFor(`document.querySelectorAll("#surveys .cross-survey").length === 2`, "恢复全部");
  t.step("按版本筛选：只看 v2 时只剩“今年”；都没选时提示至少选择一项");

  // ---------- 数字题 ----------
  await b.goto(`${t.base}/questions/${age.id}/stats`);
  await b.waitFor(`document.querySelectorAll("#surveys .cross-survey").length === 2`, "年龄的统计");
  assert.equal(await t.text("#overall .stat-average b"), "24.60");
  assert.equal(await b.eval(`document.querySelectorAll("#overall .stat-item").length`), 5);
  assert.deepEqual(await t.texts("#overall .stat-item .stat-user"), ["今年", "今年", "今年", "去年", "去年"]);
  const pageText = await b.eval("document.body.innerText");
  assert.ok(!pageText.includes("ui_cs_bob") && !pageText.includes("ui_cs_carol"), "不显示填写人");
  t.step("数字题：平均值按全部答案 24.60；内容列表附问卷标题，不显示填写人");
  await t.shot("数字题");

  // ---------- 没有问卷使用、手机尺寸 ----------
  const unused = ok(await t.api("POST", "/api/questions", { type: "text", title: "没人用的题" }, alice), 201);
  await b.goto(`${t.base}/questions/${unused.id}/stats`);
  await b.waitFor(`document.querySelector("#overall .empty")`, "空结果");
  assert.ok((await t.text("#overall .empty")).includes("还没有你的已发布或已关闭的问卷使用这道题"));
  await b.size(390, 844);
  await b.goto(`${t.base}/questions/${g2.id}/stats`);
  await b.waitFor(`document.querySelectorAll("#surveys .cross-survey").length === 2`, "手机尺寸");
  assert.equal(await b.eval("document.documentElement.scrollWidth > window.innerWidth"), false, "手机尺寸下不应出现横向滚动");
  t.step("没有问卷使用时显示提示；手机尺寸下没有横向滚动");
  await t.shot("手机尺寸");
});
