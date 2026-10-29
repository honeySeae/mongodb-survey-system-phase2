"""题目与版本接口的请求/响应模型（设计文档 10.2）。

只约束结构和基本类型，并拒绝多余字段；内容规则在 app/logic/question_versions.py 中检查。
"""
from datetime import datetime
from typing import Any

from pydantic import StrictBool

from app.schemas.common import CamelModel
from app.schemas.questions import OptionCreate, OptionUpdate, StrictCamelModel
from app.schemas.surveys import SurveyOut


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


class SharingUpdate(StrictCamelModel):
    """整体替换共享设置：usernames 为共享给哪些用户（空数组 = 不共享给任何人），public 是否公开。"""
    public: StrictBool
    usernames: list[str]


class SharingOut(CamelModel):
    public: bool
    user_ids: list[str]
    usernames: list[str]


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


class SharingResult(CamelModel):
    question: QuestionVersionOut
    updated_versions: int  # 自己在这道题下被一起更新的版本数


class SaveToLibraryResult(CamelModel):
    """存入题目库的结果：补上 source 的问卷和新生成的 v1。"""
    survey: SurveyOut
    question: QuestionVersionOut


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


class UsageSurvey(CamelModel):
    """使用这道题的一份自己的问卷。"""
    id: str
    title: str
    status: str
    is_expired: bool
    short_code: str
    url: str
    survey_question_id: str   # 问卷中这道题的 id
    question_id: str          # 问卷使用的版本 id
    version: int              # 问卷使用的版本号


class QuestionUsage(CamelModel):
    """被哪些问卷使用（10.8）：自己的问卷列出详情，别人的问卷只给数量。"""
    scope: str                # version 只看这个版本 / question 整道题的所有版本
    question_id: str
    root_id: str
    mine: list[UsageSurvey]
    mine_count: int
    others_count: int
    total_count: int
