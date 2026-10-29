// 编辑问卷页：问卷设置、发布/关闭/删除、题目（所见即所得）的添加、修改、删除、调整顺序与跳转规则。
// 所有修改题目的请求都带 expectedUpdatedAt；保存后以后端返回的整份问卷为准重新渲染。
// 第二阶段：从题目库添加、换版本、存入题目库（面板见 edit-library.js）；来自题目库的题显示来源标签。
import { api, requireLogin, withQuery } from "./api.js";
import { createDeadlinePicker } from "./deadline.js";
import { bindOptionHighlight, el, errorNotice, linkBox, pathSegment, POLICY_LABELS, renderTopbar, statusBadge, toast } from "./layout.js";
import { createQuestionEditor } from "./question-editor.js";
import { createQuestionView, TYPE_LABELS } from "./render.js";
import { createSwitchPanel, sourceBadge } from "./edit-library.js";
import { createLibraryPicker } from "./library-picker.js";

const $ = (id) => document.getElementById(id);
const surveyId = pathSegment(1);

let survey = null;
let meta = null;
let editor = null;          // 当前打开的编辑器：{ key: 题目 id、"new"、"library"（从题目库添加）或 "switch:<题目 id>", instance }
let deadlinePicker = null;

if (requireLogin()) {
  renderTopbar("surveys");
  init();
}

async function init() {
  try {
    [meta, survey] = await Promise.all([api("GET", "/api/meta"), api("GET", `/api/surveys/${encodeURIComponent(surveyId)}`)]);
  } catch (err) {
    $("survey-title").textContent = err.status === 404 ? "问卷不存在" : "加载失败";
    $("status-message").replaceChildren(errorNotice(err));
    $("settings-form").hidden = true;
    $("questions-paper").hidden = true;
    return;
  }
  deadlinePicker = createDeadlinePicker({ value: survey.settings.deadline });
  $("s-deadline-slot").append(deadlinePicker.element);
  bindOptionHighlight($("s-policy-group"));
  bindOptionHighlight($("s-anonymous-group"));
  renderAddBar();
  renderAll();
}

// 离开页面时提醒未保存的题目修改
window.addEventListener("beforeunload", (e) => {
  if (editor && editor.instance.isDirty()) { e.preventDefault(); e.returnValue = ""; }
});

const editable = () => survey.status === "draft";

function renderAll() {
  renderHeader();
  renderSettings();
  renderQuestions();
}

// ---------- 抬头、状态与操作 ----------
function renderHeader() {
  document.title = `${survey.title} · 编辑问卷`;
  $("survey-title").replaceChildren(survey.title, " ", statusBadge(survey));
  const parts = [`${survey.questions.length} 道题`, POLICY_LABELS[survey.settings.submissionPolicy]];
  if (survey.settings.allowAnonymous) parts.push("匿名");
  $("survey-meta").textContent = parts.join(" · ");

  const actions = [];
  actions.push(el("a", { class: "btn small ghost", href: `/survey/${survey.shortCode}`, target: "_blank",
                         text: survey.status === "draft" ? "预览" : "打开填写页" }));
  actions.push(el("a", { class: "btn small ghost", href: `/surveys/${survey.id}/stats`, text: "统计" }));
  if (survey.status === "draft") {
    actions.push(el("button", { class: "btn small", type: "button", text: "发布", onclick: publish }));
    actions.push(el("button", { class: "btn small danger", type: "button", text: "删除", onclick: removeSurvey }));
  } else if (survey.status === "published") {
    actions.push(el("button", { class: "btn small danger", type: "button", text: "关闭问卷", onclick: closeSurvey }));
  }
  $("status-actions").replaceChildren(...actions);

  $("link-slot").replaceChildren(...(survey.status === "draft" ? [] : [
    el("div", { class: "field-label", text: "问卷链接（发给填写者）" }), linkBox(survey.url)]));

  const lock = {
    draft: null,
    published: survey.isExpired
      ? "问卷已截止：延长截止时间后恢复收集。题目、提交策略和匿名设置不能修改。"
      : "问卷已发布：题目、提交策略和匿名设置不能修改，可以修改标题、说明和截止时间。",
    closed: "问卷已关闭，不能再修改。",
  }[survey.status];
  $("status-message").replaceChildren(...(lock ? [el("div", { class: `notice ${survey.status === "closed" ? "" : "info"}`, text: lock })] : []));
}

async function publish() {
  if (editor && editor.instance.isDirty() && !confirm("有未保存的题目修改，发布前请先保存或取消。仍要继续发布吗？")) return;
  if (!confirm("发布后不能再修改题目、提交策略和匿名设置。确定发布吗？")) return;
  await statusAction("POST", `/api/surveys/${survey.id}/publish`, "问卷已发布");
}

async function closeSurvey() {
  if (!confirm("关闭后不能重新打开，填写者将无法再提交。确定关闭吗？")) return;
  await statusAction("POST", `/api/surveys/${survey.id}/close`, "问卷已关闭");
}

async function removeSurvey() {
  if (!confirm(`确定删除草稿《${survey.title}》吗？删除后无法恢复。`)) return;
  try {
    await api("DELETE", `/api/surveys/${survey.id}`);
    location.href = "/surveys";
  } catch (err) {
    $("status-message").replaceChildren(errorNotice(err));
  }
}

async function statusAction(method, path, doneMessage) {
  try {
    survey = await api(method, path);
    closeEditor();
    renderAll();
    toast(doneMessage);
  } catch (err) {
    $("status-message").replaceChildren(errorNotice(err));
    $("status-message").scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

// ---------- 问卷设置 ----------
function renderSettings() {
  const s = survey.settings;
  $("s-title").value = survey.title;
  $("s-description").value = survey.description;
  document.querySelectorAll('input[name="s-policy"]').forEach((i) => { i.checked = i.value === s.submissionPolicy; });
  $("s-anonymous").checked = s.allowAnonymous;
  deadlinePicker.setValue(s.deadline);

  const closed = survey.status === "closed";
  const locked = survey.status !== "draft";   // 已发布、已关闭：匿名和提交策略锁定
  $("s-title").disabled = closed;
  $("s-description").disabled = closed;
  document.querySelectorAll('input[name="s-policy"]').forEach((i) => { i.disabled = locked; i.closest(".option").classList.toggle("disabled", locked); });
  $("s-anonymous").disabled = locked;
  $("s-anonymous").closest(".option").classList.toggle("disabled", locked);
  deadlinePicker.setDisabled(closed);
  $("settings-save").hidden = closed;
  $("settings-lock-hint").hidden = !locked || closed;
  $("settings-lock-hint").textContent = "已发布：提交策略和匿名设置不能修改（会影响已收集答卷的统计口径和对填写者的隐私承诺）";
  $("s-policy-group").dispatchEvent(new Event("change"));
  $("s-anonymous-group").dispatchEvent(new Event("change"));
}

$("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("settings-message").replaceChildren();
  document.querySelectorAll("#settings-form .invalid").forEach((n) => n.classList.remove("invalid"));
  const body = {
    title: $("s-title").value,
    description: $("s-description").value,
    deadline: deadlinePicker.getValue(),
  };
  if (survey.status === "draft") {
    body.submissionPolicy = document.querySelector('input[name="s-policy"]:checked').value;
    body.allowAnonymous = $("s-anonymous").checked;
  }
  $("settings-save").disabled = true;
  try {
    survey = await api("PATCH", `/api/surveys/${survey.id}`, body);
    renderHeader();
    renderSettings();
    renderQuestionsHead();
    toast("设置已保存");
  } catch (err) {
    $("settings-message").replaceChildren(errorNotice(err));
    for (const item of err.errors || []) {
      const target = document.querySelector(`#settings-form [data-field="${CSS.escape(item.field || "")}"]`);
      if (target) target.classList.add("invalid");
    }
  } finally {
    $("settings-save").disabled = false;
  }
});

// ---------- 题目 ----------
function renderQuestionsHead() {
  $("q-paper-title").textContent = survey.title;
  $("q-paper-desc").textContent = survey.description;
  $("q-paper-desc").hidden = !survey.description;
}

function warningsOf(qid) {
  return (survey.warnings || []).filter((w) => w.questionId === qid).map((w) => w.message);
}

function renderQuestions(errorsByQuestion = {}) {
  renderQuestionsHead();
  const list = $("questions");
  list.replaceChildren();
  survey.questions.forEach((q, i) => {
    if (editor && (editor.key === q.id || editor.key === `switch:${q.id}`)) {
      list.append(editor.instance.element);
      return;
    }
    const view = createQuestionView(q, i + 1, { disabled: true });
    view.setWarnings(warningsOf(q.id));
    if (errorsByQuestion[q.id]) view.setError(errorsByQuestion[q.id]);
    if (q.source) view.element.querySelector(".q-title").append(sourceBadge(q));
    if (editable()) view.element.prepend(questionTools(q, i));
    else if (!q.source) view.element.prepend(libraryTools(q));
    list.append(view.element);
  });
  if (editor && (editor.key === "new" || editor.key === "library")) list.append(editor.instance.element);
  if (!survey.questions.length && !(editor && editor.key === "new")) {
    list.append(el("div", { class: "empty", text: editable() ? "还没有题目，在下方选择题型添加第一道题" : "这份问卷没有题目" }));
  }
  $("add-bar").hidden = !editable();
}

function questionTools(q, i) {
  const n = survey.questions.length;
  return el("div", { class: "q-tools" },
    el("button", { class: "btn small link", type: "button", text: "编辑", onclick: () => openEditor(q.id) }),
    el("button", { class: "btn small link muted", type: "button", text: "上移", disabled: i === 0, onclick: () => move(i, -1) }),
    el("button", { class: "btn small link muted", type: "button", text: "下移", disabled: i === n - 1, onclick: () => move(i, 1) }),
    el("button", { class: "btn small link muted", type: "button", text: "删除", onclick: () => removeQuestion(q, i) }),
    q.source
      ? el("button", { class: "btn small link muted", type: "button", text: "换版本", onclick: () => openSwitch(q, i) })
      : el("button", { class: "btn small link muted", type: "button", text: "存入题目库", onclick: () => saveToLibrary(q) }));
}

/** 已发布、已关闭的问卷：问卷中直接建的题仍可以存入题目库（只补来源信息，不改题目内容）。 */
function libraryTools(q) {
  return el("div", { class: "q-lib-tools" },
    el("button", { class: "btn small link muted", type: "button", text: "存入题目库", onclick: () => saveToLibrary(q) }));
}

function renderAddBar() {
  const bar = $("add-bar");
  for (const type of meta.questionTypes) {
    bar.append(el("button", { class: "btn small ghost", type: "button", text: `＋ ${TYPE_LABELS[type] || type}`,
                              onclick: () => openEditor("new", type) }));
  }
  bar.append(el("button", { class: "btn small ghost", type: "button", text: "从题目库添加", onclick: openLibraryPicker }));
}

// ---------- 第二阶段：题目库 ----------
function openPanel(key, instance) {
  if (!confirmDiscard()) return;
  editor = { key, instance };
  $("questions-message").replaceChildren();
  renderQuestions();
  instance.element.scrollIntoView({ behavior: "smooth", block: "start" });
  instance.focus();
}

function openLibraryPicker() {
  openPanel("library", createLibraryPicker({
    title: "从题目库添加",
    intro: "添加的是题目的副本：题目库中的题以后修改（生成新版本）不会影响这份问卷。是否必答、跳转规则在问卷中设置。",
    usedRoots: new Set(survey.questions.filter((q) => q.source).map((q) => q.source.rootId)),
    usedText: "已在问卷中",
    usedTitle: "同一道题在一份问卷中只能出现一次；要用其他版本请对问卷中的这道题“换版本”",
    addText: "添加",
    showRequired: true,
    showBanks: true,
    async onAdd(questionId, required) {
      try {
        survey = await api("POST", questionsPath("/from-library"), { questionId, required });
      } catch (err) {
        if (err.code === "EDIT_CONFLICT") return showConflict(err);
        throw err;   // 由面板显示
      }
      closeEditor();
      renderAll();
      toast("已添加；可以“编辑”这道题设置是否必答和跳转规则");
    },
    onCancel: () => { closeEditor(); renderQuestions(); },
  }));
}

function openSwitch(q, i) {
  openPanel(`switch:${q.id}`, createSwitchPanel({
    question: q, number: i + 1,
    async onSwitch(versionId) {
      try {
        survey = await api("PUT", questionsPath(`/${encodeURIComponent(q.id)}/version`), { questionId: versionId });
      } catch (err) {
        if (err.code === "EDIT_CONFLICT") return showConflict(err);
        throw err;
      }
      closeEditor();
      renderAll();
      const qNow = survey.questions.find((x) => x.id === q.id);
      toast(`已换成 v${qNow.source.version}`);
    },
    onCancel: () => { closeEditor(); renderQuestions(); },
  }));
}

async function saveToLibrary(q) {
  if (!confirmDiscard()) return;
  const lockNote = editable() ? "存入后，这道题在问卷中只能修改是否必答和跳转规则。" : "题目内容和已收集的答卷都不会改变。";
  if (!confirm(`把「${q.title}」存入题目库？会生成一道新题 v1，之后可以在其他问卷中使用。${lockNote}`)) return;
  try {
    const r = await api("POST", `/api/surveys/${survey.id}/questions/${encodeURIComponent(q.id)}/save-to-library`);
    survey = r.survey;
    closeEditor();
    renderAll();
    toast("已存入题目库（v1）");
  } catch (err) {
    showQuestionsError(err, q.id);
  }
}

function confirmDiscard() {
  return !editor || !editor.instance.isDirty() || confirm("当前题目有未保存的修改，确定放弃吗？");
}

function openEditor(key, type) {
  if (!confirmDiscard()) return;
  const index = key === "new" ? survey.questions.length : survey.questions.findIndex((q) => q.id === key);
  const question = key === "new" ? null : survey.questions[index];
  const instance = createQuestionEditor({
    question, type, index, questions: survey.questions, meta,
    onSave: (body) => saveQuestion(key, body),
    onCancel: () => { if (confirmDiscard()) { closeEditor(); renderQuestions(); } },
  });
  editor = { key, instance };
  $("questions-message").replaceChildren();
  renderQuestions();
  instance.element.scrollIntoView({ behavior: "smooth", block: "start" });
  instance.focus();
}

function closeEditor() {
  editor = null;
}

/** 修改题目的请求都带 expectedUpdatedAt：期间问卷被修改过（例如另一个标签页）时后端返回 409。 */
function questionsPath(suffix = "") {
  return withQuery(`/api/surveys/${survey.id}/questions${suffix}`, { expectedUpdatedAt: survey.updatedAt });
}

async function saveQuestion(key, body) {
  try {
    if (key === "new") {
      survey = await api("POST", questionsPath(), body);
      // 新题保存后自动打开它的编辑器，方便继续设置跳转规则
      const created = survey.questions[survey.questions.length - 1];
      closeEditor();
      const hasLogic = Boolean(meta.operators[created.type]);
      if (hasLogic) {
        openEditor(created.id);
        toast("已添加，可以继续设置跳转规则");
      } else {
        renderAll();
        toast("已添加");
      }
    } else {
      survey = await api("PUT", questionsPath(`/${encodeURIComponent(key)}`), body);
      closeEditor();
      renderAll();
      const warnings = warningsOf(key);
      toast(warnings.length ? `已保存，有 ${warnings.length} 条提醒（见题目下方）` : "已保存");
    }
  } catch (err) {
    if (err.code === "EDIT_CONFLICT") return showConflict(err);
    editor.instance.setErrors(err);
  }
}

async function move(i, delta) {
  if (!confirmDiscard()) return;
  const ids = survey.questions.map((q) => q.id);
  [ids[i], ids[i + delta]] = [ids[i + delta], ids[i]];
  try {
    survey = await api("PUT", questionsPath("/order"), { questionIds: ids });
    closeEditor();
    $("questions-message").replaceChildren();
    renderAll();
  } catch (err) {
    if (err.code === "EDIT_CONFLICT") return showConflict(err);
    // 例如调整后出现往前跳：错误提示在顶部，并标在对应题目上
    showQuestionsError(err);
  }
}

async function removeQuestion(q, i) {
  if (!confirmDiscard()) return;
  if (!confirm(`确定删除第 ${i + 1} 题「${q.title}」吗？`)) return;
  try {
    survey = await api("DELETE", questionsPath(`/${encodeURIComponent(q.id)}`));
    closeEditor();
    $("questions-message").replaceChildren();
    renderAll();
    toast("已删除");
  } catch (err) {
    if (err.code === "EDIT_CONFLICT") return showConflict(err);
    // 被跳转规则引用时：提示是哪条规则
    showQuestionsError(err, q.id);
  }
}

function showQuestionsError(err, fallbackQuestionId) {
  $("questions-message").replaceChildren(errorNotice(err));
  const byQuestion = {};
  for (const e of err.errors || []) {
    const qid = e.questionId || fallbackQuestionId;
    if (qid && !byQuestion[qid]) byQuestion[qid] = e.message;
  }
  if (!Object.keys(byQuestion).length && fallbackQuestionId) byQuestion[fallbackQuestionId] = err.message;
  renderQuestions(byQuestion);
  $("questions-message").scrollIntoView({ behavior: "smooth", block: "center" });
}

function showConflict(err) {
  const box = el("div", { class: "notice warn", role: "alert" },
    `${err.message}。`,
    el("button", { class: "btn small ghost", type: "button", text: "刷新页面", onclick: () => location.reload() }));
  $("questions-message").replaceChildren(box);
  box.scrollIntoView({ behavior: "smooth", block: "center" });
}
