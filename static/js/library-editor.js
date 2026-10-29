// 题目库中一道题的内容编辑表单：题型、题目、选项、校验规则（不含是否必答、不含跳转规则），下方实时预览。
// 新建题目、直接修改、基于某个版本创建新版本共用。
// 规则（与后端一致，以后端检查为准）：同一道题的各个版本题型相同；保留的选项带原 id，新增选项不带 id。
import { el } from "./layout.js";
import { createQuestionView, TYPE_LABELS } from "./render.js";

const CHOICE_TYPES = new Set(["single_choice", "multiple_choice"]);

// 各题型的校验字段及在表单中的写法（与问卷编辑页相同；题目库中没有“必答”）
const VALIDATION_INPUTS = {
  multiple_choice: [["minSelect", "至少选", "项"], ["maxSelect", "最多选", "项"]],
  text: [["minLength", "至少", "字"], ["maxLength", "最多", "字"]],
  number: [["min", "最小值", ""], ["max", "最大值", ""]],
};

/** 输入框文字 -> 校验值：空为不设置；合法数字转为数字；否则原样交给后端报错。 */
export function toValidationValue(raw) {
  const s = String(raw).trim();
  if (s === "") return undefined;
  const n = Number(s);
  return Number.isFinite(n) ? n : s;
}

/** 由编辑状态生成请求体 {type, title, options?, validation}。 */
export function buildBody(state) {
  const validation = {};
  for (const [key] of VALIDATION_INPUTS[state.type] || []) {
    const value = toValidationValue(state.validation[key] ?? "");
    if (value !== undefined) validation[key] = value;
  }
  if (state.type === "number" && state.integerOnly) validation.integerOnly = true;
  const body = { type: state.type, title: state.title, validation };
  if (CHOICE_TYPES.has(state.type)) {
    body.options = state.options.map((o) => (o.id ? { id: o.id, text: o.text } : { text: o.text }));
  }
  return body;
}

/**
 * @param {object} opts
 *   question  已有版本（修改 / 派生时）；新建为 null
 *   lockType  为 true 时不能改题型（修改、派生）
 *   submitText 保存按钮文字
 *   onSubmit(body) 返回 Promise；onCancel()
 * @returns {{ element, setBusy(bool), showError(node) }}
 */
export function createContentEditor(opts) {
  const q = opts.question;
  const v0 = (q && q.validation) || {};
  const state = {
    type: q ? q.type : "single_choice",
    title: q ? q.title : "",
    options: q && q.options ? q.options.map((o) => ({ id: o.id, text: o.text })) : [{ text: "" }, { text: "" }],
    validation: Object.fromEntries(Object.entries(v0).filter(([k]) => k !== "integerOnly")
      .map(([k, val]) => [k, String(val)])),
    integerOnly: Boolean(v0.integerOnly),
  };

  const message = el("div", { class: "msg-slot" });
  const typeRow = el("div", { class: "editor-row" });
  const titleRow = el("div", { class: "editor-row" });
  const optionsRow = el("div", { class: "editor-row top" });
  const validationRow = el("div", { class: "editor-row" });
  const preview = el("div", { class: "editor-preview" });
  const submitBtn = el("button", { class: "btn", type: "submit", text: opts.submitText || "保存" });

  const form = el("form", { class: "library-editor", novalidate: true },
    message, typeRow, titleRow, optionsRow, validationRow,
    el("div", { class: "actions" }, submitBtn,
      el("button", { class: "btn link muted", type: "button", text: "取消", onclick: () => opts.onCancel && opts.onCancel() })),
    preview);

  // ---------- 题型 ----------
  function renderType() {
    if (opts.lockType) {
      typeRow.replaceChildren(el("span", { class: "editor-label", text: "题型" }),
        el("span", {}, TYPE_LABELS[state.type], el("span", { class: "muted", text: "  同一道题的各个版本题型相同；要换题型请新建一道题" })));
      return;
    }
    const select = el("select", { "aria-label": "题型", onchange: (e) => { state.type = e.target.value; renderAll(); } },
      Object.entries(TYPE_LABELS).map(([value, label]) => el("option", { value, text: label, selected: value === state.type })));
    typeRow.replaceChildren(el("label", { class: "editor-label", text: "题型" }), select);
  }

  // ---------- 题目 ----------
  function renderTitle() {
    const input = el("input", { class: "input", id: "lib-title", maxlength: 200, value: state.title,
      placeholder: "如：你的年龄", oninput: (e) => { state.title = e.target.value; renderPreview(); } });
    titleRow.replaceChildren(el("label", { class: "editor-label", for: "lib-title", text: "题目" }), input);
  }

  // ---------- 选项 ----------
  function renderOptions() {
    if (!CHOICE_TYPES.has(state.type)) { optionsRow.hidden = true; return; }
    optionsRow.hidden = false;
    const markClass = state.type === "single_choice" ? "radio" : "checkbox";
    const list = el("div", {}, state.options.map((o, i) => el("div", { class: "editor-option" },
      el("span", { class: `mark-static ${markClass}` }),
      el("input", { class: "input", value: o.text, maxlength: 100, placeholder: `选项 ${i + 1}`, "aria-label": `选项 ${i + 1}`,
        oninput: (e) => { o.text = e.target.value; renderPreview(); } }),
      el("button", { class: "btn link muted", type: "button", text: "删除", title: "删除这个选项",
        disabled: state.options.length <= 1,
        onclick: () => { state.options.splice(i, 1); renderOptions(); renderPreview(); } }))));
    const add = el("button", { class: "btn small ghost", type: "button", text: "＋ 添加选项",
      onclick: () => { state.options.push({ text: "" }); renderOptions(); renderPreview(); } });
    optionsRow.replaceChildren(el("span", { class: "editor-label", text: "选项" }), el("div", {}, list, add,
      q && q.options ? el("div", { class: "help", text: "只改文字的选项仍是同一个选项，统计时会与旧版本合并" }) : null));
  }

  // ---------- 校验规则 ----------
  function renderValidation() {
    const fields = VALIDATION_INPUTS[state.type] || [];
    const parts = fields.map(([key, label, unit]) => el("span", { class: "inline" },
      el("span", { text: label }),
      el("input", { class: "input short", value: state.validation[key] || "", "aria-label": label,
        inputmode: "decimal", oninput: (e) => { state.validation[key] = e.target.value; renderPreview(); } }),
      unit ? el("span", { text: unit }) : null));
    if (state.type === "number") {
      parts.push(el("label", { class: "check" },
        el("input", { type: "checkbox", checked: state.integerOnly,
          onchange: (e) => { state.integerOnly = e.target.checked; renderPreview(); } }), "只允许整数"));
    }
    validationRow.hidden = parts.length === 0;
    validationRow.replaceChildren(el("span", { class: "editor-label", text: "校验" }),
      el("div", { class: "editor-checks" }, parts));
  }

  function renderPreview() {
    const body = buildBody(state);
    const view = createQuestionView({ id: "preview", ...body, options: (body.options || []).map((o, i) => ({ id: o.id || `new-${i}`, text: o.text })) },
      1, { disabled: true });
    preview.replaceChildren(el("div", { class: "muted", text: "预览（是否必答、跳转规则在问卷中设置）" }), view.element);
  }

  function renderAll() {
    renderType(); renderTitle(); renderOptions(); renderValidation(); renderPreview();
  }
  renderAll();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    message.replaceChildren();
    await opts.onSubmit(buildBody(state));
  });

  return {
    element: form,
    setBusy(busy) { submitBtn.disabled = busy; },
    showError(node) { message.replaceChildren(node); },
  };
}
