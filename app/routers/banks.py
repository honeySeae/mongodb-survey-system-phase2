"""题库接口（第二阶段，设计文档 10.7）。均需登录。

从题库选题：取题库详情，用其中可用条目的 questionId 调用
POST /api/surveys/{id}/questions/from-library（共享的题库会让其中的版本对你可访问）。
"""
from fastapi import APIRouter, Depends, Query, Response
from pymongo.database import Database

from app.repositories import users as users_repo
from app.routers.question_library import names_for, version_out
from app.schemas.banks import (BankCreate, BankItemAdd, BankItemOut, BankItemSwitch, BankList, BankOut,
                               BankSummary, BankUpdate, NewerVersionOut)
from app.schemas.question_library import SharingOut, SharingUpdate
from app.security import get_current_user, get_database
from app.services import banks as service

router = APIRouter(prefix="/api/banks", tags=["question-banks"])

LIST_LIMIT_MAX = 100


def _summary_fields(bank: dict, user_id, usernames: dict) -> dict:
    mine = bank["ownerId"] == user_id
    shared = bank["sharing"]["userIds"]
    return dict(
        id=str(bank["_id"]), name=bank["name"], description=bank.get("description", ""),
        owner=usernames.get(bank["ownerId"], ""), is_mine=mine,
        item_count=bank["itemCount"] if "itemCount" in bank else len(bank["items"]),
        sharing=SharingOut(public=bank["sharing"]["public"], user_ids=[str(u) for u in shared],
                           usernames=[usernames.get(u, "") for u in shared]) if mine else None,
        created_at=bank["createdAt"], updated_at=bank["updatedAt"],
    )


def _bank_user_ids(bank: dict, user_id) -> list:
    """需要显示用户名的用户：创建者，以及自己题库的共享名单（共享名单只返回给创建者）。"""
    ids = [bank["ownerId"]]
    if bank["ownerId"] == user_id:
        ids.extend(bank["sharing"]["userIds"])
    return ids


def bank_out(db: Database, bank: dict, user: dict) -> BankOut:
    uid = user["_id"]
    resolved = service.resolve_items(db, bank, uid)
    docs = [r.version for r in resolved if r.version is not None]
    names = users_repo.usernames_by_ids(db, _bank_user_ids(bank, uid))
    version_names = names_for(db, docs, uid)
    items = [BankItemOut(
        question_id=str(r.item["questionId"]), root_id=str(r.item["rootId"]), added_at=r.item["addedAt"],
        available=r.version is not None,
        question=version_out(r.version, uid, version_names) if r.version is not None else None,
        newer_version=NewerVersionOut(question_id=str(r.newer["_id"]), version=r.newer["version"])
        if r.newer is not None else None,
        notice=r.notice) for r in resolved]
    return BankOut(**_summary_fields(bank, uid, names), items=items)


@router.post("", response_model=BankOut, status_code=201)
def create(body: BankCreate, user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    return bank_out(db, service.create_bank(db, user["_id"], name=body.name, description=body.description), user)


@router.get("", response_model=BankList)
def list_banks(scope: str = Query("mine", pattern="^(mine|shared|public|all)$",
                                  description="mine 我的 / shared 共享给我的 / public 公开的 / all 全部可访问的"),
               offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=LIST_LIMIT_MAX),
               user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    banks, total = service.list_banks(db, user["_id"], scope, offset, limit)
    ids = [u for b in banks for u in _bank_user_ids(b, user["_id"])]
    names = users_repo.usernames_by_ids(db, ids)
    return BankList(items=[BankSummary(**_summary_fields(b, user["_id"], names)) for b in banks],
                    total=total, offset=offset, limit=limit)


@router.get("/{bank_id}", response_model=BankOut)
def detail(bank_id: str, user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """题库详情：条目及其版本内容；不可用的条目只有 id。"""
    return bank_out(db, service.get_accessible(db, user["_id"], bank_id), user)


@router.patch("/{bank_id}", response_model=BankOut)
def update(bank_id: str, body: BankUpdate, user: dict = Depends(get_current_user),
           db: Database = Depends(get_database)):
    changes = body.model_dump(exclude_unset=True)
    return bank_out(db, service.update_bank(db, user["_id"], bank_id, changes), user)


@router.delete("/{bank_id}", status_code=204)
def delete(bank_id: str, user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """删除题库：不影响已经使用这些题的问卷，也不影响题目版本。"""
    service.delete_bank(db, user["_id"], bank_id)
    return Response(status_code=204)


@router.put("/{bank_id}/sharing", response_model=BankOut)
def set_sharing(bank_id: str, body: SharingUpdate, user: dict = Depends(get_current_user),
                db: Database = Depends(get_database)):
    """整体替换题库的共享设置（只有创建者）。"""
    bank = service.set_sharing(db, user["_id"], bank_id, public=body.public, usernames=body.usernames)
    return bank_out(db, bank, user)


@router.post("/{bank_id}/items", response_model=BankOut, status_code=201)
def add_item(bank_id: str, body: BankItemAdd, user: dict = Depends(get_current_user),
             db: Database = Depends(get_database)):
    """把一个版本加入题库（同一道题只能有一项；放进题库不锁定版本）。"""
    return bank_out(db, service.add_item(db, user["_id"], bank_id, body.question_id), user)


@router.put("/{bank_id}/items/{root_id}", response_model=BankOut)
def switch_item(bank_id: str, root_id: str, body: BankItemSwitch, user: dict = Depends(get_current_user),
                db: Database = Depends(get_database)):
    """把这道题（rootId）的一项换成另一个版本。"""
    return bank_out(db, service.switch_item(db, user["_id"], bank_id, root_id, body.question_id), user)


@router.delete("/{bank_id}/items/{root_id}", response_model=BankOut)
def remove_item(bank_id: str, root_id: str, user: dict = Depends(get_current_user),
                db: Database = Depends(get_database)):
    return bank_out(db, service.remove_item(db, user["_id"], bank_id, root_id), user)
