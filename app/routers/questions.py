"""题目编辑接口（创建者视角，仅草稿可修改）。

所有接口返回修改后的完整问卷（含系统生成的 id 和当前的 warnings）。
可选查询参数 expectedUpdatedAt：客户端读取问卷时看到的 updatedAt，带了则检查期间问卷是否被修改。
"""
from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime
from pymongo.database import Database

from app.routers.question_library import version_detail
from app.routers.surveys import survey_out
from app.schemas.question_library import SaveToLibraryResult
from app.schemas.questions import (LibraryQuestionAdd, QuestionCreate, QuestionUpdate, ReorderRequest,
                                   SwitchVersionRequest)
from app.schemas.surveys import SurveyOut
from app.security import get_current_user, get_database
from app.services import questions as question_service

router = APIRouter(prefix="/api/surveys/{survey_id}/questions", tags=["questions"])

ExpectedUpdatedAt = Query(None, alias="expectedUpdatedAt",
                          description="读取问卷时的 updatedAt；带了就检查期间是否被修改，不带则不检查")


@router.post("", response_model=SurveyOut, status_code=201)
def add(survey_id: str, body: QuestionCreate,
        expected_updated_at: AwareDatetime | None = ExpectedUpdatedAt,
        user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """添加题目（不接受跳转规则，添加后通过修改题目设置）。"""
    doc = question_service.add_question(
        db, user["_id"], survey_id, qtype=body.type, title=body.title,
        options=[o.model_dump() for o in body.options] if body.options is not None else None,
        validation=body.validation, position=body.position,
        logic_given="logic" in body.model_fields_set, expected_updated_at=expected_updated_at)
    return survey_out(doc)


@router.post("/from-library", response_model=SurveyOut, status_code=201)
def add_from_library(survey_id: str, body: LibraryQuestionAdd,
                     expected_updated_at: AwareDatetime | None = ExpectedUpdatedAt,
                     user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """第二阶段：把题目库中的一个版本复制进问卷（记录 source，版本加锁）；同一道题只能出现一次。"""
    return survey_out(question_service.add_from_library(
        db, user["_id"], survey_id, question_id=body.question_id, required=body.required,
        position=body.position, expected_updated_at=expected_updated_at))


# 注意：/order 必须在 /{question_id} 之前声明，否则 "order" 会被当成题目 id
@router.put("/order", response_model=SurveyOut)
def reorder(survey_id: str, body: ReorderRequest,
            expected_updated_at: AwareDatetime | None = ExpectedUpdatedAt,
            user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """调整题目顺序，questionIds 必须恰好包含全部题目。"""
    return survey_out(question_service.reorder_questions(
        db, user["_id"], survey_id, body.question_ids, expected_updated_at))


@router.put("/{question_id}", response_model=SurveyOut)
def update(survey_id: str, question_id: str, body: QuestionUpdate,
           expected_updated_at: AwareDatetime | None = ExpectedUpdatedAt,
           user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """整体替换一道题（含跳转规则）。保留的选项带原 id，新增选项不带 id，未提交的选项视为删除。"""
    doc = question_service.update_question(
        db, user["_id"], survey_id, question_id, qtype=body.type, title=body.title,
        options=[o.model_dump() for o in body.options] if body.options is not None else None,
        validation=body.validation, logic=body.logic, expected_updated_at=expected_updated_at)
    return survey_out(doc)


@router.put("/{question_id}/version", response_model=SurveyOut)
def switch_version(survey_id: str, question_id: str, body: SwitchVersionRequest,
                   expected_updated_at: AwareDatetime | None = ExpectedUpdatedAt,
                   user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """第二阶段：来自题目库的题换成同一道题的另一个版本（保留题目 id、是否必答、跳转规则）。"""
    return survey_out(question_service.switch_version(
        db, user["_id"], survey_id, question_id, version_id=body.question_id,
        expected_updated_at=expected_updated_at))


@router.post("/{question_id}/save-to-library", response_model=SaveToLibraryResult, status_code=201)
def save_to_library(survey_id: str, question_id: str,
                    user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """第二阶段：把问卷中直接建的题存进题目库，生成新题 v1（选项 id 沿用），并给原题补上 source。
    不改题目内容，已发布、已关闭的问卷也可以。"""
    survey, version = question_service.save_to_library(db, user["_id"], survey_id, question_id)
    return SaveToLibraryResult(survey=survey_out(survey), question=version_detail(db, version, user))


@router.delete("/{question_id}", response_model=SurveyOut)
def delete(survey_id: str, question_id: str,
           expected_updated_at: AwareDatetime | None = ExpectedUpdatedAt,
           user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """删除题目；有其他题的跳转规则指向它时拒绝。"""
    return survey_out(question_service.delete_question(
        db, user["_id"], survey_id, question_id, expected_updated_at))
