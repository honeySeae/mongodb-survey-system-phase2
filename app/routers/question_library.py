"""题目与版本接口（第二阶段，设计文档第十节）。均需登录。

- 题目独立于问卷保存，每个版本一条记录；问卷中的题目接口仍是 /api/surveys/{id}/questions
- 看不到的版本与不存在一样返回 404；看得到但不是自己的，修改、删除返回 403
"""
from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime
from pymongo.database import Database

from app.logic import question_access as access
from app.repositories import users as users_repo
from app.schemas.question_library import (HistoryNode, QuestionHistory, QuestionVersionCreate,
                                          QuestionVersionEdit, QuestionVersionList, QuestionVersionOut,
                                          RestoreRequest, SharingOut, SharingResult, SharingUpdate)
from app.security import get_current_user, get_database
from app.services import question_library as service

router = APIRouter(prefix="/api/questions", tags=["question-library"])

LIST_LIMIT_MAX = 100


def _str(oid) -> str | None:
    return str(oid) if oid is not None else None


def _user_ids_to_name(docs: list[dict], user_id) -> list:
    """需要显示用户名的用户：所有者，以及自己版本的共享名单（共享名单只返回给所有者）。"""
    ids = [d["ownerId"] for d in docs]
    for d in docs:
        if access.is_owner(d, user_id):
            ids.extend(d["sharing"]["userIds"])
    return ids


def _names(db: Database, docs: list[dict], user_id) -> dict:
    return users_repo.usernames_by_ids(db, _user_ids_to_name(docs, user_id))


def version_out(doc: dict, user_id, usernames: dict) -> QuestionVersionOut:
    mine = access.is_owner(doc, user_id)
    shared_ids = doc["sharing"]["userIds"]
    return QuestionVersionOut(
        id=str(doc["_id"]), root_id=str(doc["rootId"]), parent_id=_str(doc.get("parentId")),
        restored_from=_str(doc.get("restoredFrom")), version=doc["version"],
        owner=usernames.get(doc["ownerId"], ""), is_mine=mine, locked=access.is_locked(doc),
        type=doc["type"], title=doc["title"], options=doc.get("options"), validation=doc["validation"],
        sharing=SharingOut(public=doc["sharing"]["public"], user_ids=[str(u) for u in shared_ids],
                           usernames=[usernames.get(u, "") for u in shared_ids]) if mine else None,
        created_at=doc["createdAt"], updated_at=doc["updatedAt"],
    )


def version_detail(db: Database, doc: dict, user: dict) -> QuestionVersionOut:
    return version_out(doc, user["_id"], _names(db, [doc], user["_id"]))


def _options(body) -> list[dict] | None:
    return [o.model_dump() for o in body.options] if body.options is not None else None


@router.post("", response_model=QuestionVersionOut, status_code=201)
def create(body: QuestionVersionCreate, user: dict = Depends(get_current_user),
           db: Database = Depends(get_database)):
    """新建一道题，生成 v1（默认不共享）。"""
    doc = service.create_question(db, user["_id"], qtype=body.type, title=body.title,
                                  options=_options(body), validation=body.validation)
    return version_detail(db, doc, user)


@router.get("", response_model=QuestionVersionList)
def list_versions(scope: str = Query("mine", pattern="^(mine|shared|public|all)$",
                                     description="mine 我的 / shared 共享给我的 / public 公开的 / all 全部可访问的"),
                  root_id: str | None = Query(None, alias="rootId", description="只看某道题的版本"),
                  offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=LIST_LIMIT_MAX),
                  user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """题目版本列表（最近修改的在前）。"""
    docs, total = service.list_questions(db, user["_id"], scope, root_id, offset, limit)
    names = _names(db, docs, user["_id"])
    return QuestionVersionList(items=[version_out(d, user["_id"], names) for d in docs],
                               total=total, offset=offset, limit=limit)


@router.get("/{question_id}", response_model=QuestionVersionOut)
def detail(question_id: str, user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    return version_detail(db, service.get_accessible(db, user["_id"], question_id), user)


@router.put("/{question_id}", response_model=QuestionVersionOut)
def update(question_id: str, body: QuestionVersionEdit,
           expected_updated_at: AwareDatetime | None = Query(None, alias="expectedUpdatedAt"),
           user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """直接修改自己的、未被问卷使用的版本（题型不能改）。"""
    doc = service.update_version(db, user["_id"], question_id, qtype=body.type, title=body.title,
                                 options=_options(body), validation=body.validation,
                                 expected_updated_at=expected_updated_at)
    return version_detail(db, doc, user)


@router.delete("/{question_id}", status_code=204)
def delete(question_id: str, user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """删除自己的版本：被问卷用过、有子版本、在题库中的不能删。"""
    service.delete_version(db, user["_id"], question_id)
    return Response(status_code=204)


@router.post("/{question_id}/versions", response_model=QuestionVersionOut, status_code=201)
def derive(question_id: str, body: QuestionVersionEdit, user: dict = Depends(get_current_user),
           db: Database = Depends(get_database)):
    """基于一个可访问的版本创建自己的新版本（parentId = 该版本）。"""
    doc = service.derive_version(db, user["_id"], question_id, qtype=body.type, title=body.title,
                                 options=_options(body), validation=body.validation)
    return version_detail(db, doc, user)


@router.post("/{question_id}/restore", response_model=QuestionVersionOut, status_code=201)
def restore(question_id: str, body: RestoreRequest | None = None, user: dict = Depends(get_current_user),
            db: Database = Depends(get_database)):
    """把这个版本的内容复制成一个新版本（restoredFrom = 该版本），接在 parentId 后面。"""
    doc = service.restore_version(db, user["_id"], question_id, body.parent_id if body else None)
    return version_detail(db, doc, user)


@router.put("/{question_id}/sharing", response_model=SharingResult)
def set_sharing(question_id: str, body: SharingUpdate, user: dict = Depends(get_current_user),
                db: Database = Depends(get_database)):
    """设置共享（只有所有者）：以整道题为单位，同时作用于自己在这道题下的所有版本；整体替换原设置。"""
    doc, count = service.set_sharing(db, user["_id"], question_id,
                                     public=body.public, usernames=body.usernames)
    return SharingResult(question=version_detail(db, doc, user), updated_versions=count)


@router.get("/{question_id}/history", response_model=QuestionHistory)
def get_history(question_id: str, user: dict = Depends(get_current_user),
                db: Database = Depends(get_database)):
    """这道题的全部版本（按版本号排序）；无权查看的版本只显示版本号和父子关系。"""
    doc, versions = service.history(db, user["_id"], question_id)
    names = _names(db, [v for v, ok in versions if ok], user["_id"])
    nodes = [HistoryNode(id=str(v["_id"]), version=v["version"], parent_id=_str(v.get("parentId")),
                         restored_from=_str(v.get("restoredFrom")), accessible=ok,
                         detail=version_out(v, user["_id"], names) if ok else None)
             for v, ok in versions]
    return QuestionHistory(root_id=str(doc["rootId"]), versions=nodes)
