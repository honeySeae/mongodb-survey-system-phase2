// 界面测试（第二阶段 10a 题目库页）：新建题目、列表、详情与预览、直接修改、创建新版本、
// 版本历史、被问卷使用后锁定、恢复旧版本、共享给别人、被共享的人看到的页面、删除、手机尺寸。
import { scenario } from "./helpers.mjs";

await scenario("题目库页", async (t) => {
  const { browser: b, assert } = t;
  const ok = (r, status = 200) => { assert.equal(r.status, status, JSON.stringify(r.body)); return r.body; };
  const detailLoaded = (text) => b.waitFor(`!document.getElementById("content").hidden &&
    document.getElementById("title").textContent.includes(${JSON.stringify(text)})`, `详情页显示「${text}」`);

  // 被共享的用户先注册
  await t.api("POST", "/api/auth/register", { username: "ui_lib_bob", password: "uitest123" });
  const owner = await t.login("ui_lib_alice");

  // ---------- 新建题目 ----------
  await b.goto(`${t.base}/questions`);
  await b.waitFor(`document.querySelector("#list .empty")?.textContent.includes("还没有题目")`, "空列表提示");
  assert.deepEqual(await t.texts(".topbar nav a"), ["我的问卷", "题目库", "题库"]);
  assert.equal(await t.text(".topbar nav a.active"), "题目库");
  t.step("顶部导航新增“题目库”；空列表时有提示");
  await t.shot("空的题目库");

  await t.click("#new-btn");
  await b.eval(`(() => { const s = document.querySelector("#new-slot select"); s.value = "single_choice";
    s.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
  await t.type("#lib-title", "你的性别");
  await t.type('#new-slot .editor-option:nth-child(1) input', "男");
  await t.type('#new-slot .editor-option:nth-child(2) input', "女");
  assert.deepEqual(await t.texts("#new-slot .editor-preview .option"), ["男", "女"]);
  assert.equal(await b.eval(`document.querySelectorAll("#new-slot input[type=checkbox]").length`), 0,
    "题目库中没有“必答”勾选框");
  t.step("新建题目表单：题型、题目、选项，下方实时预览；没有“必答”和跳转规则");
  await t.shot("新建题目");
  await t.click("#new-slot button[type=submit]");
  await detailLoaded("你的性别");
  const v1Id = (await t.location()).split("/")[2];
  assert.equal(await t.text("#title .badge.version"), "v1");
  assert.ok((await t.text("#state-note")).includes("还没有被问卷使用，可以直接修改"));
  assert.deepEqual(await t.texts("#actions button"), ["直接修改", "另存为新版本", "删除此版本"]);
  t.step("保存后进入详情页：v1、未使用时可以直接修改、另存为新版本、删除");

  // ---------- 直接修改 ----------
  await t.click("#actions button", "直接修改");
  assert.ok((await t.text("#editor-slot")).includes("同一道题的各个版本题型相同"));
  await t.type("#lib-title", "性别");
  await t.click("#editor-slot button", "＋ 添加选项");
  await t.type('#editor-slot .editor-option:nth-child(3) input', "不愿透露");
  await t.click("#editor-slot button[type=submit]");
  await b.waitFor(`document.querySelectorAll("#preview .option").length === 3 && !document.querySelector("#editor-slot form")`,
    "保存后在原页面更新");
  assert.equal(await b.eval(`document.getElementById("title").firstChild.textContent`), "性别");
  assert.deepEqual(await t.texts("#preview .option"), ["男", "女", "不愿透露"]);
  assert.equal(await t.text("#title .badge.version"), "v1");
  t.step("直接修改未使用的版本：题型不能改，保存后仍是 v1");

  // ---------- 创建新版本 ----------
  await t.click("#actions button", "另存为新版本");
  await t.type('#editor-slot .editor-option:nth-child(2) input', "女性");
  await t.click("#editor-slot button[type=submit]");
  await b.waitFor(`document.querySelector("#title .badge.version")?.textContent === "v2"`, "跳到 v2");
  assert.deepEqual(await t.texts("#preview .option"), ["男", "女性", "不愿透露"]);
  await b.waitFor(`document.querySelectorAll("#history .history-row").length === 2`, "历史中有 2 个版本");
  assert.deepEqual(await t.texts("#history .badge.version"), ["v1", "v2"]);
  assert.equal(await b.eval(`document.querySelector("#history .history-row.current").style.paddingLeft`), "28px");
  assert.deepEqual(await t.texts("#history .history-diff"), ["最初的版本", "与 v1 相比：选项「女」→「女性」"]);
  t.step("另存为新版本 v2；版本历史显示 v1 → v2（v2 缩进在 v1 之下），并说明每个版本改了什么");

  // ---------- 加进问卷后锁定 ----------
  const survey = ok(await t.api("POST", "/api/surveys", { title: "期中调查" }, owner), 201);
  ok(await t.api("POST", `/api/surveys/${survey.id}/questions/from-library`, { questionId: v1Id }, owner), 201);
  await b.goto(`${t.base}/questions/${v1Id}`);
  await detailLoaded("性别");
  assert.ok((await t.text("#state-note")).includes("已被问卷使用，不能直接修改"));
  assert.deepEqual(await t.texts("#actions button"), ["基于此版本创建新版本", "恢复此版本", "删除此版本"]);
  assert.equal(await b.eval(`[...document.querySelectorAll("#actions button")].find((x) => x.textContent === "删除此版本").disabled`), true);
  assert.equal(await t.text("#actions .action-note"), "不能删除：这个版本已被问卷使用，不能删除");
  await b.waitFor(`document.querySelectorAll("#usage .usage-item").length === 1`, "使用情况");
  assert.ok((await t.text("#usage .usage-item")).includes("期中调查"));
  assert.ok((await t.text("#usage")).includes("你的问卷 1 份"));
  await t.click("#usage-scope button", "整道题（所有版本）");
  await b.waitFor(`document.querySelector("#usage .muted")?.textContent.includes("共 1 份")`, "整道题的使用情况");
  t.step("v1 被问卷使用后：提示不能直接修改，只能创建新版本；删除按钮变灰并说明原因；显示被“期中调查”使用");
  await t.shot("已使用的版本");

  // ---------- 恢复旧版本 ----------
  await b.eval("window.confirm = () => true; true");
  await t.click("#actions button", "恢复此版本");
  await b.waitFor(`document.querySelector("#title .badge.version")?.textContent === "v3"`, "恢复为 v3");
  assert.deepEqual(await t.texts("#preview .option"), ["男", "女", "不愿透露"]);
  await b.waitFor(`document.querySelectorAll("#history .history-row").length === 3`, "历史中有 3 个版本");
  assert.ok((await t.text("#history .history-row.current")).includes("恢复自 v1"));
  assert.equal(await t.text("#history .history-row.current .history-diff"), "与 v2 相比：选项「女性」→「女」");
  t.step("恢复 v1：生成 v3（内容同 v1），接在 v2 后面，标注“恢复自 v1”");
  await t.shot("版本历史");

  // ---------- 共享 ----------
  await t.type("#sharing-users", "ui_lib_bob");
  await t.click("#sharing-save");
  await b.waitFor(`document.querySelector(".toast")?.textContent.includes("3 个版本")`, "共享保存提示");
  assert.ok((await t.text("#meta")).includes("已共享给 ui_lib_bob"));
  await t.type("#sharing-users", "nobody_here");
  await t.click("#sharing-save");
  await b.waitFor(`document.querySelector("#sharing-message .notice.error")`, "用户不存在的错误");
  assert.ok((await t.text("#sharing-message")).includes("用户「nobody_here」不存在"));
  t.step("共享给 ui_lib_bob：同步到这道题下的 3 个版本；用户名不存在时提示错误");

  // ---------- 被共享的人 ----------
  await t.logout();
  await t.login("ui_lib_bob");
  await b.goto(`${t.base}/questions`);
  await t.click("#tabs button", "共享给我的");
  await b.waitFor(`document.querySelectorAll("#list .lib-item").length === 1`, "共享给我的：同一道题只出现一次");
  assert.ok((await t.text("#list .lib-item .meta")).includes("来自 ui_lib_alice"));
  assert.deepEqual(await t.texts("#list .lib-item .lib-versions a"), ["v1", "v2", "v3"]);
  assert.equal(await t.text("#list .lib-item h3 .badge.version"), "v3");
  await b.goto(`${t.base}/questions/${v1Id}`);
  await detailLoaded("性别");
  assert.ok((await t.text("#state-note")).includes("这是 ui_lib_alice 的题目"));
  assert.deepEqual(await t.texts("#actions button"), ["基于此版本创建我的新版本", "恢复此版本"]);
  assert.equal(await b.eval(`document.getElementById("sharing-section").hidden`), true, "不显示共享设置");
  assert.ok(!(await t.text("#meta")).includes("ui_lib_bob"), "不显示共享名单");
  await b.waitFor(`document.querySelector("#usage .muted")?.textContent.includes("别人的问卷 1 份")`, "别人的问卷只显示数量");
  assert.ok(!(await t.text("#usage")).includes("期中调查"));
  t.step("被共享的人：“共享给我的”中这道题只出现一次（列出 v1、v2、v3）；只能基于它创建自己的新版本；看不到共享名单和别人问卷的标题");
  await t.shot("被共享的人看到的详情");

  // ---------- 焦点框 ----------
  // 无界面 Chrome 中鼠标点击本来就不显示焦点框，无法复现；这里检查样式表中确有两条规则：
  // 非键盘操作时不显示焦点框；键盘操作时为靛蓝色细框（不是浏览器默认的黑色 / 系统色）
  const rules = await b.eval(`[...document.styleSheets].flatMap((sh) => [...sh.cssRules])
    .filter((r) => r.selectorText && r.selectorText.includes("focus")).map((r) => r.cssText)`);
  assert.ok(rules.some((r) => r.startsWith(":focus:not(:focus-visible)") && r.includes("outline: none")), rules.join(" | "));
  assert.ok(rules.some((r) => r.includes("button:focus-visible") && r.includes("var(--primary-line)")), rules.join(" | "));
  t.step("样式表规定：鼠标点击不显示焦点框，键盘操作时为靛蓝色细框");

  // ---------- 删除 ----------
  await t.logout();
  await t.login("ui_lib_alice");
  const temp = ok(await t.api("POST", "/api/questions", { type: "text", title: "临时题" }, owner), 201);
  await b.goto(`${t.base}/questions/${temp.id}`);
  await detailLoaded("临时题");
  await b.eval("window.confirm = () => true; true");   // 换了页面，需要重新替换确认框
  await t.click("#actions button", "删除此版本");
  await b.waitFor(`location.pathname === "/questions"`, "删除后回到列表");
  await b.waitFor(`document.querySelectorAll("#list .lib-item").length === 1`, "列表剩 1 道题");
  assert.ok(!(await t.texts("#list .lib-item h3 a")).includes("临时题"));
  t.step("删除未使用的版本后回到题目库列表");

  // ---------- 不存在的题目、手机尺寸 ----------
  await b.goto(`${t.base}/questions/000000000000000000000000`);
  await b.waitFor(`document.getElementById("title").textContent === "题目不存在"`, "不存在的题目");
  await b.size(390, 844);
  await b.goto(`${t.base}/questions/${v1Id}`);
  await detailLoaded("性别");
  const overflow = await b.eval("document.documentElement.scrollWidth > window.innerWidth");
  assert.equal(overflow, false, "手机尺寸下不应出现横向滚动");
  t.step("不存在的题目提示“题目不存在”；手机尺寸下没有横向滚动");
  await t.shot("手机尺寸");
});
