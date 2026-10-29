"""查看题目被哪些问卷使用（设计文档 10.8，需求六）。

- 能访问这个版本的人都可以查（所有者、被共享的人、通过题库访问的人）
- 自己的问卷：显示标题、状态、链接；别人的问卷：只显示数量
- 两种范围：version 只看这个版本；question 看整道题（同一 rootId 的所有版本）
- 只依据 surveys.questions.source：没有 source 的题（第一阶段的题、问卷中直接建的题）不算使用
- 包括草稿：加进草稿就算用过（版本已锁定）；题目从问卷中删除后不再计入（但版本不解锁）
"""
from bson import ObjectId
from pymongo.database import Database

from app.repositories import surveys as surveys_repo
from app.services import question_library as library


def usage(db: Database, user_id: ObjectId, question_id: str, scope: str) -> dict:
    doc = library.get_accessible(db, user_id, question_id)
    key, value = ("questionId", doc["_id"]) if scope == "version" else ("rootId", doc["rootId"])
    source_filter = {f"questions.source.{key}": value}

    mine = []
    for survey in surveys_repo.find_using(db, source_filter, user_id):
        # 同一道题在一份问卷中只出现一次：取出是问卷中的哪道题、用的哪个版本
        q = next(q for q in survey["questions"] if (q.get("source") or {}).get(key) == value)
        mine.append({"survey": survey, "survey_question_id": q["id"], "source": q["source"]})
    return {"version": doc, "mine": mine,
            "others_count": surveys_repo.count_using_by_others(db, source_filter, user_id)}
