"""题目与版本接口的请求/响应模型（设计文档 10.2）。

只约束结构和基本类型，并拒绝多余字段；内容规则在 app/logic/question_versions.py 中检查。
"""
from datetime import datetime
from typing import Any

from app.schemas.common import CamelModel
from app.schemas.questions import OptionCreate, OptionUpdate, StrictCamelModel


class QuestionVersionCreate(StrictCamelModel):
    """新建一道题（生成 v1）。validation 不含 required。"""
    type: str
    title: str
    options: list[OptionCreate] | None = None
    validation: dict[str, Any] | None = None


class QuestionVersionEdit(StrictCamelModel):
    """直接修改 / 派生新版本：整体提交内容。保留的选项带原 id，新增选项不带 id，未提交的选项视为删除。
    type 必须与原版本相同。"""
    type: str
    title: str
    options: list[OptionUpdate] | None = None
    validation: dict[str, Any] | None = None


class RestoreRequest(StrictCamelModel):
    parent_id: str | None = None  # 接在哪个版本后面；不填按默认规则


class SharingOut(CamelModel):
    public: bool
    user_ids: list[str]


class QuestionVersionOut(CamelModel):
    id: str
    root_id: str
    parent_id: str | None
    restored_from: str | None
    version: int
    owner: str            # 所有者用户名（不返回用户 id）
    is_mine: bool
    locked: bool          # 已被问卷使用，只能派生新版本
    type: str
    title: str
    options: list[dict] | None = None
    validation: dict[str, Any]
    sharing: SharingOut | None = None  # 只对所有者返回
    created_at: datetime
    updated_at: datetime


class QuestionVersionList(CamelModel):
    items: list[QuestionVersionOut]
    total: int
    offset: int
    limit: int


class HistoryNode(CamelModel):
    """历史中的一个版本。没有权限查看的版本只有版本号和父子关系（accessible=false，detail 为空）。"""
    id: str
    version: int
    parent_id: str | None
    restored_from: str | None
    accessible: bool
    detail: QuestionVersionOut | None = None


class QuestionHistory(CamelModel):
    root_id: str
    versions: list[HistoryNode]
