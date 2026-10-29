// 界面测试（第二阶段 10c 题库页）：新建题库、加入题目（我的 / 共享给我的）、同一道题只能加入一次、
// “有新版本 vN 可换”与换版本、换其他版本（说明改了什么）、共享题库、原作者取消共享后的不可用提示
// （只对创建者说明原因）、被共享的人只读查看并在问卷编辑页“从题目库添加 → 题库”中选题、
// 修改名称、移除、删除题库、手机尺寸。
import { scenario } from "./helpers.mjs";

await scenario("题库页", async (t) => {
  const { browser: b, assert } = t;
  const ok = (r, status = 200) => { assert.equal(r.status, status, JSON.stringify(r.body)); return r.body; };
  const register = async (name) => {
    await t.api("POST", "/api/auth/register", { username: name, password: "uitest123" });
    return (await t.api("POST", "/api/auth/login", { username: name, password: "uitest123" })).body.accessToken;
  };
  const itemCount = (n) => b.waitFor(`document.querySelectorAll("#items .bank-item").length === ${n}`, `题库中 ${n} 项`);
  const itemText = (i) => t.text(`#items .bank-item:nth-child(${i})`);

  const carol = await register("ui_bk_carol");
  await register("ui_bk_bob");
  const alice = await t.login("ui_bk_alice");
  const gender = ok(await t.api("POST", "/api/questions", { type: "single_choice", title: "性别",
    options: [{ text: "男" }, { text: "女" }] }, alice), 201);
  ok(await t.api("POST", "/api/questions", { type: "number", title: "年龄", validation: { min: 0, max: 150 } }, alice), 201);
  const hobby = ok(await t.api("POST", "/api/questions", { type: "text", title: "爱好" }, carol), 201);
  ok(await t.api("PUT", `/api/questions/${hobby.id}/sharing`, { public: false, usernames: ["ui_bk_alice"] }, carol));

  // ---------- 新建题库 ----------
  await b.goto(`${t.base}/banks`);
  await b.waitFor(`document.querySelector("#list .empty")?.textContent.includes("还没有题库")`, "空列表");
  assert.deepEqual(await t.texts(".topbar nav a"), ["我的问卷", "题目库", "题库"]);
  await t.click("#new-btn");
  await t.type("#name", "学生基本信息");
  await t.type("#description", "每学期都用");
  await t.click("#create-btn");
  await b.waitFor(`!document.getElementById("content").hidden && document.getElementById("title").textContent === "学生基本信息"`, "题库详情");
  const bankId = (await t.location()).split("/")[2];
  assert.ok((await t.text("#items .empty")).includes("还没有题目"));
  t.step("新建题库后进入题库详情，提示加入题目");

  // ---------- 加入题目 ----------
  await t.click("#add-btn");
  await b.waitFor(`document.querySelectorAll(".library-picker .pick-row").length === 2`, "我的题目");
  assert.equal(await b.eval(`document.querySelectorAll(".library-picker input[type=checkbox]").length`), 0, "题库中不设必答");
  await b.eval(`[...document.querySelectorAll(".library-picker .pick-row")].find((r) => r.textContent.includes("性别"))
    .querySelector("button").click(); true`);
  await itemCount(1);
  await t.click("#add-btn");
  await b.waitFor(`[...document.querySelectorAll(".library-picker .pick-row button")].some((x) => x.textContent === "已在题库中")`, "已在题库中");
  await b.eval(`[...document.querySelectorAll(".library-picker .pick-row")].find((r) => r.textContent.includes("年龄"))
    .querySelector("button").click(); true`);
  await itemCount(2);
  await t.click("#add-btn");
  await t.click(".library-picker .seg button", "共享给我的");
  await b.waitFor(`document.querySelector(".library-picker .pick-row")?.textContent.includes("爱好")`, "共享给我的题");
  await t.click(".library-picker .pick-row button", "加入");
  await itemCount(3);
  assert.ok((await itemText(3)).includes("来自 ui_bk_carol"));
  t.step("加入题目：我的题目、共享给我的；已加入的显示“已在题库中”；题库中不设必答");
  await t.shot("题库详情");

  // ---------- 有新版本可换 ----------
  const g2 = ok(await t.api("POST", `/api/questions/${gender.id}/versions`, { type: "single_choice", title: "性别",
    options: [gender.options[0], { id: gender.options[1].id, text: "女性" }] }, alice), 201);
  await b.goto(`${t.base}/banks/${bankId}`);
  await itemCount(3);
  assert.ok((await itemText(1)).includes("有新版本 v2 可换"));
  await t.click("#items .bank-item:nth-child(1) button", "换成 v2");
  await b.waitFor(`document.querySelector("#items .bank-item:nth-child(1) .badge.version")?.textContent === "v2"`, "换成 v2");
  assert.ok(!(await itemText(1)).includes("有新版本"));
  t.step("有新版本时提示“有新版本 v2 可换”，一键更换后提示消失");

  await t.click("#items .bank-item:nth-child(1) button", "换其他版本");
  await b.waitFor(`document.querySelector(".library-picker .pick-row")`, "其他版本");
  assert.ok((await t.text(".library-picker .pick-row")).includes("与当前相比：选项「女性」→「女」"));
  t.step("换其他版本：列出 v1（较旧），说明与当前相比改了什么");
  await t.click(".library-picker button", "取消");

  // ---------- 共享、修改名称 ----------
  await t.type("#sharing-users", "ui_bk_bob");
  await t.click("#sharing-save");
  await b.waitFor(`document.getElementById("meta").textContent.includes("已共享给 ui_bk_bob")`, "共享成功");
  await t.click("#head-actions button", "修改名称和说明");
  await t.type("#edit-name", "学生信息");
  await t.click("#edit-save");
  await b.waitFor(`document.getElementById("title").textContent === "学生信息"`, "名称已修改");
  t.step("共享给 ui_bk_bob；修改题库名称");

  // ---------- 原作者取消共享：只对创建者说明原因 ----------
  ok(await t.api("PUT", `/api/questions/${hobby.id}/sharing`, { public: false, usernames: [] }, carol));
  await b.goto(`${t.base}/banks/${bankId}`);
  await itemCount(3);
  assert.ok((await itemText(3)).includes("原作者 ui_bk_carol 已取消共享"));
  assert.ok((await itemText(3)).includes("请移除这一项"));
  t.step("原作者取消共享后：创建者看到“不可用”和原因、处理办法");
  await t.shot("不可用的条目");

  // ---------- 被共享的人 ----------
  await t.logout();
  const bob = await t.login("ui_bk_bob");
  await b.goto(`${t.base}/banks`);
  await t.click("#tabs button", "共享给我的");
  await b.waitFor(`document.querySelectorAll("#list .lib-item").length === 1`, "共享给我的题库");
  await b.goto(`${t.base}/banks/${bankId}`);
  await itemCount(3);
  assert.ok((await t.text("#role-note")).includes("这是 ui_bk_alice 的题库"));
  assert.equal(await b.eval(`document.getElementById("add-bar").hidden`), true);
  assert.equal(await b.eval(`document.querySelectorAll("#items button").length`), 0, "没有修改按钮");
  assert.equal(await b.eval(`document.getElementById("sharing-section").hidden`), true);
  assert.ok((await itemText(3)).includes("这一项目前不可用"));
  assert.ok(!(await itemText(3)).includes("取消共享"), "原因只对创建者显示");
  t.step("被共享的人：只读查看，没有修改按钮和共享设置；不可用的项只显示“不可用”，不显示原因");

  const survey = ok(await t.api("POST", "/api/surveys", { title: "bob 的问卷" }, bob), 201);
  await b.goto(`${t.base}/surveys/${survey.id}/edit`);
  await b.waitFor(`document.querySelector("#questions .empty")`, "空问卷");
  await t.click("#add-bar button", "从题目库添加");
  await b.waitFor(`document.querySelector(".library-picker .seg")`, "面板");
  await t.click(".library-picker .seg button", "题库");
  await b.waitFor(`document.querySelector(".library-picker .pick-bank")?.textContent.includes("学生信息")`, "题库列表");
  await t.click(".library-picker .pick-bank button", "展开");
  await b.waitFor(`document.querySelectorAll(".library-picker .pick-bank-items .pick-row").length === 3`, "题库中的题");
  assert.ok((await t.text(".library-picker .pick-bank-items")).includes("这一项不可用"));
  await t.click(".library-picker .pick-bank-items .pick-row button", "添加");
  await b.waitFor(`document.querySelector("#questions .badge.source")?.textContent === "题目库 v2"`, "从题库添加");
  t.step("被共享的人在问卷编辑页“从题目库添加 → 题库”中展开题库并添加（未单独共享给他的题也能用）");
  await t.shot("从题库选题");

  // ---------- 移除、删除 ----------
  await t.logout();
  await t.login("ui_bk_alice");
  await b.goto(`${t.base}/banks/${bankId}`);
  await itemCount(3);
  await b.eval("window.confirm = () => true; true");
  await t.click("#items .bank-item:nth-child(3) button", "移除");
  await itemCount(2);
  t.step("移除不可用的项");

  await b.size(390, 844);
  await b.goto(`${t.base}/banks/${bankId}`);
  await itemCount(2);
  assert.equal(await b.eval("document.documentElement.scrollWidth > window.innerWidth"), false, "手机尺寸下不应出现横向滚动");
  await t.shot("手机尺寸");
  await b.size(1100, 900);

  await b.eval("window.confirm = () => true; true");
  await t.click("#head-actions button", "删除题库");
  await b.waitFor(`location.pathname === "/banks"`, "删除后回到列表");
  await b.waitFor(`document.querySelector("#list .empty")`, "题库列表为空");
  assert.equal((await t.api("GET", `/api/questions/${g2.id}`, undefined, alice)).status, 200, "删除题库不影响题目");
  t.step("手机尺寸下没有横向滚动；删除题库后回到列表，题目库中的题不受影响");
});
