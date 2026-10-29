"""题目编辑接口的请求模型。

这里只约束结构和基本类型，并拒绝多余字段；题型相关的规则（validation 的字段、取值范围、
跳转规则）在 app/logic/question_rules.py 与 app/logic/survey_check.py 中检查，返回中文提示。
"""
from typing import Any

from pydantic import ConfigDict, StrictBool, StrictInt

from app.schemas.common import CamelModel


class StrictCamelModel(CamelModel):
    """不接受未定义的字段（字段名写错时直接报错，而不是被静默忽略）。"""
    model_config = ConfigDict(extra="forbid")


class OptionCreate(StrictCamelModel):
    text: str


class OptionUpdate(StrictCamelModel):
    id: str | None = None  # 保留的选项带原 id；新增选项不带 id
    text: str


class QuestionCreate(StrictCamelModel):
    type: str
    title: str
    options: list[OptionCreate] | None = None
    validation: dict[str, Any] | None = None
    position: StrictInt | None = None  # 插入到第几题（从 1 开始），不填则加在末尾
    # 添加题目时不接受跳转规则；声明该字段是为了给出明确的中文提示，而不是笼统的“不支持该字段”
    logic: Any = None


class QuestionUpdate(StrictCamelModel):
    """整体替换一道题（id 不变）。不提交 logic 或提交 null 表示没有跳转规则。"""
    type: str
    title: str
    options: list[OptionUpdate] | None = None
    validation: dict[str, Any] | None = None
    logic: dict[str, Any] | None = None


class ReorderRequest(StrictCamelModel):
    question_ids: list[str]


# ---------- 第二阶段：使用题目库中的题（设计文档 10.5） ----------
class LibraryQuestionAdd(StrictCamelModel):
    """从题目库添加：question_id 为题目版本的 id。跳转规则添加后通过修改题目设置。"""
    question_id: str
    required: StrictBool = False
    position: StrictInt | None = None


class SwitchVersionRequest(StrictCamelModel):
    """换成同一道题的另一个版本：question_id 为目标版本的 id。"""
    question_id: str
