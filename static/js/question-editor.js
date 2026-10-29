// 单道题的编辑表单（就地展开在题目卡片中）：题型、题目、必答、选项、校验规则、跳转规则，下方实时预览。
// 跳转规则用下拉框设置，不需要手写 id；可选的运算符与值的格式来自 /api/meta（后端运算符表），前端不维护副本。
// 目标下拉框只列出本题之后的题和“结束问卷”，从界面上就选不到往前跳。合法性仍以后端检查为准。
// 第二阶段：来自题目库的题（有 source）内容和校验不能在问卷里改，表单中这些输入框不可编辑，只能改必答和跳转规则；
// 没有 source 的题行为不变。
import { el } from "./layout.js";
import { createQuestionView, parseNumberInput, TYPE_LABELS } from "./render.js";

const CHOICE_TYPES = new Set(["single_choice", "multiple_choice"]);

// 运算符的中文名称（显示层）；后端新增运算符而这里还没有名称时，直接显示运算符本身
const OP_LABELS = {
  single_choice: { eq: "选择了", in: "选择了其中之一" },
  multiple_choice: { contains: "选中了", containsAny: "选中其中任意一项", containsAll: "同时选中", equals: "恰好选中" },
  number: { eq: "等于", ne: "不等于", gt: "大于", gte: "大于等于", lt: "小于", lte: "小于等于", between: "介于" },
};
export function opLabel(type, op) {
  return (OP_LABELS[type] || {})[op] || op;
}

// 各题型的校验字段（与 /api/meta 的 validationFields 对应），以及在表单中的写法
const VALIDATION_INPUTS = {
  multiple_choice: [["minSelect", "至少选", "项"], ["maxSelect", "最多选", "项"]],
  text: [["minLength", "至少", "字"], ["maxLength", "最多", "字"]],
  number: [["min", "最小值", ""], ["max", "最大值", ""]],
};

const truncate = (s, n) => (s.length > n ? `${s.slice(0, n)}…` : s);

/**
 * @param {object} opts
 *   question   已有题目；新建时为 null
 *   type       新建时的题型
 *   index      题目在问卷中的位置（从 0 开始；新建为末尾）
 *   questions  问卷当前已保存的题目（用于列出跳转目标）
 *   meta       /api/meta 的结果
 *   onSave(body)  返回 Promise；onCancel()
 */
export function createQuestionEditor(opts) {
  const { question, index, questions, meta } = opts;
  const isNew = !question;
  const contentLocked = Boolean(question && question.source);   // 第二阶段：来自题目库的题
  const number = index + 1;

  // ---------- 编辑中的状态 ----------
  const v0 = (question && question.validation) || {};
  const state = {
    type: question ? question.type : opts.type,
    title: question ? question.title : "",
    required: question ? Boolean(v0.required) : true,   // 新题默认必答
    options: question && question.options
      ? question.options.map((o) => ({ id: o.id, text: o.text }))
      : (CHOICE_TYPES.has(opts.type) ? [{ text: "" }, { text: "" }] : []),
    validation: Object.fromEntries(Object.entries(v0)
      .filter(([k]) => k !== "required" && k !== "integerOnly").map(([k, val]) => [k, String(val)])),
    integerOnly: Boolean(v0.integerOnly),
    rules: ((question && question.logic && question.logic.rules) || []).map((r) => ({
      op: r.when.op, value: r.when.value, goto: r.goto })),
    defaultNext: (question && question.logic && question.logic.defaultNext) ?? null,
  };
  let dirty = false;
  let typeNote = "";

  const element = el("div", { class: "question editing", dataset: { questionId: question ? question.id : "new" } });
  const errorBox = el("div");
  const preview = el("div", { class: "editor-preview" });

  function touch() { dirty = true; renderPreview(); }

  // ---------- 小部件 ----------
  function field(label, control, extraClass = "") {
    return el("div", { class: `editor-row ${extraClass}` }, el("span", { class: "editor-label", text: label }), control);
  }

  function lockable(input) {
    input.disabled = contentLocked;
    return input;
  }

  function numberBox(value, dataField, onInput) {
    return el("input", { class: "input short", type: "text", inputmode: "decimal", value: value ?? "",
                         dataset: { field: dataField }, oninput: (e) => onInput(e.target.value) });
  }

  function select(items, value, dataField, onChange) {
    const s = el("select", { dataset: { field: dataField }, onchange: (e) => onChange(e.target.value) },
      ...items.map(([val, label]) => el("option", { value: val, text: label, selected: val === value })));
    return s;
  }

  // 跳转目标：本题之后的题 + 结束问卷
  function targets() {
    const later = questions.slice(index + 1).map((q, k) =>
      [q.id, `第 ${index + 2 + k} 题：${truncate(q.title, 18)}`]);
    return [...later, [meta.end, "结束问卷"]];
  }

  // 本题已保存、仍保留的选项（新增的选项保存后才有 id，才能用于跳转规则）
  function savedOptions() {
    return state.options.filter((o) => o.id);
  }

  function defaultValue(format) {
    const first = savedOptions()[0];
    return { option: first ? first.id : null, option_list: [], number: null, number_range: [null, null] }[format] ?? null;
  }

  // ---------- 各区块 ----------
  function typeAndRequired() {
    const typeSelect = select(meta.questionTypes.map((t) => [t, TYPE_LABELS[t] || t]), state.type, "type", (t) => {
      changeType(t);
    });
    typeSelect.disabled = contentLocked;
    const req = el("label", { class: `option checkbox${state.required ? " is-checked" : ""}` },
      el("input", { type: "checkbox", checked: state.required, onchange: (e) => {
        state.required = e.target.checked;
        e.target.closest(".option").classList.toggle("is-checked", state.required);
        touch();
      } }),
      el("span", { class: "mark" }), el("span", { text: "必答" }));
    return el("div", { class: "editor-row inline" }, el("span", { class: "editor-label", text: "题型" }), typeSelect, req);
  }

  function titleRow() {
    return field("题目", el("input", { class: "input", value: state.title, maxlength: meta.limits.questionTitleMax,
      placeholder: "请输入题目", dataset: { field: "title" }, disabled: contentLocked,
      oninput: (e) => { state.title = e.target.value; touch(); } }));
  }

  function optionsBlock() {
    if (!CHOICE_TYPES.has(state.type)) return null;
    const list = el("div", { class: "editor-options" });
    state.options.forEach((o, i) => {
      list.append(el("div", { class: "editor-option" },
        el("span", { class: `mark-static ${state.type === "single_choice" ? "radio" : "checkbox"}` }),
        el("input", { class: "input", value: o.text, placeholder: `选项 ${i + 1}`, maxlength: meta.limits.optionTextMax,
                      dataset: { field: `options[${i}].text` }, disabled: contentLocked,
                      oninput: (e) => { o.text = e.target.value; touch(); } }),
        contentLocked ? null : el("button", { class: "btn link muted", type: "button", title: "删除选项", text: "删除",
                       disabled: state.options.length <= 1,
                       onclick: () => { state.options.splice(i, 1); dirty = true; render(); } })));
    });
    const add = el("button", { class: "btn link", type: "button", text: "＋ 添加选项",
      disabled: state.options.length >= meta.limits.optionsMax,
      onclick: () => { state.options.push({ text: "" }); dirty = true; render();
                       element.querySelector(`[data-field="options[${state.options.length - 1}].text"]`)?.focus(); } });
    return field("选项", el("div", {}, list, contentLocked ? null : add), "top");
  }

  function validationBlock() {
    const inputs = VALIDATION_INPUTS[state.type];
    if (!inputs) return null;
    const row = el("div", { class: "inline" });
    for (const [key, before, after] of inputs) {
      // 注意：原生 append/replaceChildren 会把 null 显示成文字 "null"，可能为空的部分要先过滤
      row.append(...[el("span", { class: "muted", text: before }),
        lockable(numberBox(state.validation[key], `validation.${key}`, (val) => { state.validation[key] = val; touch(); })),
        after ? el("span", { class: "muted", text: after }) : null].filter(Boolean));
    }
    if (state.type === "number") {
      row.append(el("label", { class: `option checkbox${state.integerOnly ? " is-checked" : ""}${contentLocked ? " disabled" : ""}` },
        el("input", { type: "checkbox", checked: state.integerOnly, dataset: { field: "validation.integerOnly" },
          disabled: contentLocked,
          onchange: (e) => { state.integerOnly = e.target.checked;
                             e.target.closest(".option").classList.toggle("is-checked", state.integerOnly); touch(); } }),
        el("span", { class: "mark" }), el("span", { text: "必须为整数" })));
    }
    const help = { multiple_choice: "两项填同一个数表示“必须选 N 项”；留空表示不限",
                   text: "留空表示不限", number: "留空表示不限" }[state.type];
    return field("要求", el("div", {}, row, el("div", { class: "help", text: help })));
  }

  function valueControl(rule, k, format) {
    const df = `logic.rules[${k}].when.value`;
    if (format === "option") {
      const opts = savedOptions();
      return select(opts.map((o) => [o.id, truncate(o.text || "（空）", 16)]), rule.value, df, (val) => { rule.value = val; touch(); });
    }
    if (format === "option_list") {
      const chosen = new Set(Array.isArray(rule.value) ? rule.value : []);
      return el("div", { class: "editor-checks", dataset: { field: df } },
        ...savedOptions().map((o) => el("label", { class: "check" },
          el("input", { type: "checkbox", checked: chosen.has(o.id), onchange: (e) => {
            if (e.target.checked) chosen.add(o.id); else chosen.delete(o.id);
            // 按选项顺序保存
            rule.value = savedOptions().map((x) => x.id).filter((id) => chosen.has(id));
            touch();
          } }), truncate(o.text || "（空）", 12))));
    }
    if (format === "number") {
      return numberBox(rule.value, df, (val) => { rule.value = parseNumberInput(val); touch(); });
    }
    if (format === "number_range") {
      const pair = Array.isArray(rule.value) ? [...rule.value] : [null, null];
      rule.value = pair;
      return el("span", { class: "inline" },
        numberBox(pair[0], df, (val) => { pair[0] = parseNumberInput(val); touch(); }),
        el("span", { class: "muted", text: "到" }),
        numberBox(pair[1], df, (val) => { pair[1] = parseNumberInput(val); touch(); }));
    }
    return el("span", { class: "muted", text: format });
  }

  function logicBlock() {
    const ops = meta.operators[state.type];
    if (!ops) return null;   // 文本题不支持跳转
    if (isNew) {
      return field("跳转", el("div", { class: "muted", text: "保存题目后可设置跳转规则" }));
    }
    const rows = el("div", { class: "editor-rules" });
    state.rules.forEach((rule, k) => {
      const format = ops[rule.op];
      rows.append(el("div", { class: "editor-rule", dataset: { field: `logic.rules[${k}]` } },
        el("span", { class: "muted", text: `${k + 1}. 如果答案` }),
        select(Object.keys(ops).map((op) => [op, opLabel(state.type, op)]), rule.op, `logic.rules[${k}].when.op`, (op) => {
          if (ops[op] !== ops[rule.op]) rule.value = defaultValue(ops[op]);
          rule.op = op; dirty = true; render();
        }),
        valueControl(rule, k, format),
        el("span", { class: "muted", text: "就跳到" }),
        select(targets(), rule.goto, `logic.rules[${k}].goto`, (g) => { rule.goto = g; touch(); }),
        el("span", { class: "rule-tools" },
          el("button", { class: "btn link muted", type: "button", text: "↑", title: "上移（规则按顺序检查，先命中的生效）",
                         disabled: k === 0, onclick: () => { moveRule(k, -1); } }),
          el("button", { class: "btn link muted", type: "button", text: "↓", title: "下移",
                         disabled: k === state.rules.length - 1, onclick: () => { moveRule(k, 1); } }),
          el("button", { class: "btn link muted", type: "button", text: "删除",
                         onclick: () => { state.rules.splice(k, 1); dirty = true; render(); } }))));
    });
    const canAdd = state.rules.length < meta.limits.rulesMax;
    const add = el("button", { class: "btn link", type: "button", text: "＋ 添加跳转规则", disabled: !canAdd,
      onclick: () => {
        const op = Object.keys(ops)[0];
        const later = targets();
        state.rules.push({ op, value: defaultValue(ops[op]), goto: later[0][0] });
        dirty = true; render();
      } });
    const defaultRow = el("div", { class: "inline" },
      el("span", { class: "muted", text: "其他情况（没有命中任何规则、或选填未作答）：" }),
      select([["", "顺序进入下一题"], ...targets()], state.defaultNext ?? "", "logic.defaultNext",
        (val) => { state.defaultNext = val === "" ? null : val; touch(); }));
    const unsavedOptions = CHOICE_TYPES.has(state.type) && state.options.some((o) => !o.id);
    return field("跳转", el("div", {},
      rows, add,
      unsavedOptions ? el("div", { class: "help", text: "新增的选项保存后才能用于跳转规则" }) : null,
      state.rules.length > 1 ? el("div", { class: "help", text: "规则按从上到下的顺序检查，第一条成立的生效" }) : null,
      defaultRow), "top");
  }

  function moveRule(k, delta) {
    const [r] = state.rules.splice(k, 1);
    state.rules.splice(k + delta, 0, r);
    dirty = true; render();
  }

  function changeType(t) {
    const wasChoice = CHOICE_TYPES.has(state.type);
    state.type = t;
    if (!CHOICE_TYPES.has(t)) state.options = [];
    else if (!wasChoice) state.options = [{ text: "" }, { text: "" }];
    state.validation = {};
    state.integerOnly = false;
    const hadLogic = state.rules.length > 0;
    state.rules = [];
    if (!meta.operators[t]) state.defaultNext = null;
    typeNote = hadLogic ? "更换题型后，原来的跳转规则已清空" : "";
    dirty = true;
    render();
  }

  // ---------- 预览与提交内容 ----------
  function buildValidation() {
    const out = { required: state.required };
    for (const [key] of VALIDATION_INPUTS[state.type] || []) {
      const raw = (state.validation[key] ?? "").trim();
      if (raw === "") continue;
      const n = Number(raw);
      out[key] = Number.isFinite(n) ? n : raw;   // 不是数字时原样提交，由后端给出提示
    }
    if (state.type === "number" && state.integerOnly) out.integerOnly = true;
    return out;
  }

  function buildBody() {
    const body = { type: state.type, title: state.title, validation: buildValidation() };
    if (CHOICE_TYPES.has(state.type)) {
      body.options = state.options.map((o) => (o.id && !isNew ? { id: o.id, text: o.text } : { text: o.text }));
    }
    if (!isNew && meta.operators[state.type] && (state.rules.length || state.defaultNext !== null)) {
      body.logic = {
        rules: state.rules.map((r) => ({ when: { op: r.op, value: r.value }, goto: r.goto })),
        defaultNext: state.defaultNext,
      };
    }
    return body;
  }

  function renderPreview() {
    const q = {
      id: question ? question.id : "preview",
      type: state.type,
      title: state.title || "（题目）",
      options: state.options.map((o, i) => ({ id: o.id || `new-${i}`, text: o.text || `选项 ${i + 1}` })),
      validation: buildValidation(),
    };
    preview.replaceChildren(el("div", { class: "editor-label", text: "预览（填写者看到的样子）" }),
      createQuestionView(q, number, { disabled: true }).element);
  }

  // ---------- 整体 ----------
  const saveBtn = el("button", { class: "btn", type: "button", text: isNew ? "添加" : "保存" });
  const cancelBtn = el("button", { class: "btn link muted", type: "button", text: "取消" });

  function render() {
    element.replaceChildren(...[
      el("div", { class: "editor-head", text: isNew ? `新建第 ${number} 题` : `编辑第 ${number} 题` }),
      errorBox,
      typeNote ? el("div", { class: "notice warn", text: typeNote }) : null,
      contentLocked ? el("div", { class: "notice info", text: `这道题来自已保存的题目（v${question.source.version}）：` +
        "题目、选项和校验不能在问卷里修改，只能改是否必答和跳转规则。要修改内容，请在“我的题目”中创建新版本，再在这里“换版本”。" }) : null,
      typeAndRequired(), titleRow(), optionsBlock(), validationBlock(), logicBlock(),
      preview,
      el("div", { class: "actions mt" }, saveBtn, cancelBtn)].filter(Boolean));
    renderPreview();
  }

  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    try { await opts.onSave(buildBody()); } finally { saveBtn.disabled = false; }
  });
  cancelBtn.addEventListener("click", () => opts.onCancel());

  render();

  return {
    element,
    isDirty: () => dirty,
    focus: () => element.querySelector('[data-field="title"]')?.focus(),
    /** 显示后端返回的错误：列在表单上方，并把对应输入框标红。 */
    setErrors(err) {
      element.querySelectorAll(".invalid").forEach((n) => n.classList.remove("invalid"));
      if (!err) { errorBox.replaceChildren(); return; }
      const items = err.errors && err.errors.length ? err.errors : [{ message: err.message }];
      errorBox.replaceChildren(el("div", { class: "notice error", role: "alert" },
        el("div", { text: err.message }),
        el("ul", {}, items.filter((e) => e.message !== err.message).map((e) => el("li", { text: e.message })))));
      for (const e of items) {
        if (!e.field) continue;
        // 字段路径与后端一致，如 options[1].text、validation.minSelect、logic.rules[0].goto
        let target = element.querySelector(`[data-field="${CSS.escape(e.field)}"]`);
        if (!target && e.field.startsWith("logic.rules[")) {
          target = element.querySelector(`[data-field="${CSS.escape(e.field.replace(/\.when\..*$|\.goto$/, ""))}"]`);
        }
        if (target) target.classList.add("invalid");
      }
      element.scrollIntoView({ behavior: "smooth", block: "start" });
    },
  };
}
