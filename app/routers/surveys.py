"""问卷管理接口（创建者视角，均需登录，只能操作自己的问卷）。"""
from fastapi import APIRouter, Depends, Response
from pymongo.database import Database

from app.config import get_settings
from app.logic import survey_state as state
from app.logic.survey_check import check_survey
from app.schemas.surveys import SettingsOut, SurveyCreate, SurveyOut, SurveySummary, SurveyUpdate
from app.security import get_current_user, get_database
from app.services import surveys as survey_service
from app.utils import now_utc

router = APIRouter(prefix="/api/surveys", tags=["surveys"])


def survey_url(short_code: str) -> str:
    """问卷访问链接；前缀来自配置，不存入数据库，更换部署地址无需修改数据。"""
    return f"{get_settings().public_base_url}/survey/{short_code}"


def _common_fields(doc: dict) -> dict:
    s = doc["settings"]
    return dict(
        id=str(doc["_id"]),
        short_code=doc["shortCode"],
        url=survey_url(doc["shortCode"]),
        title=doc["title"],
        status=doc["status"],
        is_expired=state.is_expired(s.get("deadline"), now_utc()),
        settings=SettingsOut(allow_anonymous=s["allowAnonymous"],
                             submission_policy=s["submissionPolicy"],
                             deadline=s.get("deadline")),
        created_at=doc["createdAt"],
        updated_at=doc["updatedAt"],
        published_at=doc.get("publishedAt"),
        closed_at=doc.get("closedAt"),
    )


def question_out(q: dict) -> dict:
    """创建者看到的题目。第二阶段：source 中的 ObjectId 转为字符串；没有 source 的题原样返回（与第一阶段相同）。"""
    if "source" not in q:
        return q
    s = q["source"]
    return {**q, "source": {"questionId": str(s["questionId"]), "rootId": str(s["rootId"]),
                            "version": s["version"]}}


def survey_out(doc: dict) -> SurveyOut:
    return SurveyOut(**_common_fields(doc), description=doc.get("description", ""),
                     version=doc["version"], questions=[question_out(q) for q in doc["questions"]],
                     warnings=check_survey(doc["questions"]).warnings)


def survey_summary(doc: dict) -> SurveySummary:
    return SurveySummary(**_common_fields(doc), question_count=doc["questionCount"],
                         response_count=doc["responseCount"])


@router.post("", response_model=SurveyOut, status_code=201)
def create(body: SurveyCreate, user: dict = Depends(get_current_user),
           db: Database = Depends(get_database)):
    """创建问卷（草稿状态），系统生成 shortCode 和访问链接。"""
    doc = survey_service.create_survey(
        db, user["_id"], title=body.title, description=body.description,
        allow_anonymous=body.allow_anonymous, submission_policy=body.submission_policy,
        deadline=body.deadline)
    return survey_out(doc)


@router.get("", response_model=list[SurveySummary])
def list_mine(user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """我的问卷列表（新的在前），含题目数和答卷数。"""
    return [survey_summary(d) for d in survey_service.list_surveys(db, user["_id"])]


@router.get("/{survey_id}", response_model=SurveyOut)
def detail(survey_id: str, user: dict = Depends(get_current_user),
           db: Database = Depends(get_database)):
    return survey_out(survey_service.get_owned(db, user["_id"], survey_id))


@router.patch("/{survey_id}", response_model=SurveyOut)
def update(survey_id: str, body: SurveyUpdate, user: dict = Depends(get_current_user),
           db: Database = Depends(get_database)):
    """修改基本信息和设置，只提交要改的字段；能改哪些字段取决于问卷状态。"""
    changes = body.model_dump(by_alias=True, exclude_unset=True)
    return survey_out(survey_service.update_survey(db, user["_id"], survey_id, changes))


@router.delete("/{survey_id}", status_code=204)
def delete(survey_id: str, user: dict = Depends(get_current_user),
           db: Database = Depends(get_database)):
    """删除问卷（仅限草稿）。"""
    survey_service.delete_survey(db, user["_id"], survey_id)
    return Response(status_code=204)


@router.post("/{survey_id}/publish", response_model=SurveyOut)
def publish(survey_id: str, user: dict = Depends(get_current_user),
            db: Database = Depends(get_database)):
    return survey_out(survey_service.publish_survey(db, user["_id"], survey_id))


@router.post("/{survey_id}/close", response_model=SurveyOut)
def close(survey_id: str, user: dict = Depends(get_current_user),
          db: Database = Depends(get_database)):
    return survey_out(survey_service.close_survey(db, user["_id"], survey_id))
