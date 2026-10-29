"""题库接口的请求/响应模型（设计文档 10.7）。"""
from datetime import datetime

from app.schemas.common import CamelModel
from app.schemas.question_library import QuestionVersionOut, SharingOut
from app.schemas.questions import StrictCamelModel


class BankCreate(StrictCamelModel):
    name: str
    description: str | None = None


class BankUpdate(StrictCamelModel):
    """只提交要修改的字段。"""
    name: str | None = None
    description: str | None = None


class BankItemAdd(StrictCamelModel):
    question_id: str  # 题目版本 id


class BankItemSwitch(StrictCamelModel):
    question_id: str  # 换成的版本 id（必须是同一道题）


class BankSummary(CamelModel):
    id: str
    name: str
    description: str
    owner: str            # 创建者用户名
    is_mine: bool
    item_count: int
    sharing: SharingOut | None = None  # 只对创建者返回
    created_at: datetime
    updated_at: datetime


class BankItemOut(CamelModel):
    """题库中的一项。available=false 表示不可用（题库创建者已不能访问该版本，如原作者取消了共享），
    此时不返回题目内容。"""
    question_id: str
    root_id: str
    added_at: datetime
    available: bool
    question: QuestionVersionOut | None = None


class BankOut(BankSummary):
    items: list[BankItemOut]


class BankList(CamelModel):
    items: list[BankSummary]
    total: int
    offset: int
    limit: int
