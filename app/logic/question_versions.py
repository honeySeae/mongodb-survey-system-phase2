"""题目版本的内容规则（纯函数，不访问数据库）。对应设计文档 10.2、10.4。

- 题目内容 = type、title、options、validation；validation 不含 required（是否必答由问卷决定）
- 内容本身的检查复用第一阶段 app/logic/question_rules.py
- 同一道题（同一 rootId）的所有版本题型相同：派生新版本、直接修改都不能改题型
- 选项 id：保留的选项带原 id（必须是被修改的那个版本的选项），新增选项不带 id，
  由系统生成，且在这道题的所有版本中都不重复（删掉的选项 id 不会再表示别的选项）
"""
import secrets
import string

from app.logic.question_rules import check_question_settings

ID_ALPHABET = string.ascii_lowercase + string.digits
ID_LENGTH = 6


def new_option_id(used: set[str]) -> str:
    """生成不在 used 中的选项 id（格式同第一阶段 o_ + 6 位），并加入 used。"""
    while True:
        candidate = "o_" + "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))
        if candidate not in used:
            used.add(candidate)
            return candidate


def build_content(*, qtype: str, title: str, options: list[dict] | None, validation: dict | None,
                  base: dict | None = None, used_option_ids: set[str] | None = None
                  ) -> tuple[dict, list[dict]]:
    """根据请求构造一个版本的题目内容，返回 (内容, 问题列表)。问题列表非空时内容不可用。

    base：被修改 / 派生的版本；为 None 表示新建题目（v1）。
    used_option_ids：这道题所有版本中已经用过的选项 id（新建题目时为空），新生成的 id 会加入其中。
    """
    problems: list[dict] = []
    used = used_option_ids if used_option_ids is not None else set()

    if base is not None and qtype != base["type"]:
        return {}, [{"field": "type",
                     "message": "同一道题的各个版本题型必须相同；要换题型请新建一道题"}]

    v = dict(validation or {})
    if "required" in v:
        problems.append({"field": "validation.required",
                         "message": "题目中不设置是否必答，加入问卷后在问卷中设置"})
        v.pop("required")

    content = {"type": qtype, "title": title.strip() if isinstance(title, str) else title}
    if options is not None:
        base_ids = {o["id"] for o in (base or {}).get("options") or []}
        built, kept = [], set()
        for k, o in enumerate(options):
            oid = o.get("id")
            if oid is None:
                oid = new_option_id(used)
            elif oid not in base_ids or oid in kept:
                problems.append({"field": f"options[{k}].id",
                                 "message": f"第 {k + 1} 个选项的 id {oid} 不是原版本已有的选项（新增选项不要带 id）"})
                continue
            kept.add(oid)
            text = o.get("text")
            built.append({"id": oid, "text": text.strip() if isinstance(text, str) else text})
        if problems:
            # 与第一阶段修改题目一致：选项 id 有误时只报这些错误（跳过的选项会引出无关的“选项不足”等提示）
            return {}, problems
        content["options"] = built
    content["validation"] = v

    # 内容检查复用第一阶段的规则；required 已在上面单独处理
    problems.extend(check_question_settings(content))
    return content, problems


def option_ids(doc: dict) -> set[str]:
    return {o["id"] for o in doc.get("options") or []}
