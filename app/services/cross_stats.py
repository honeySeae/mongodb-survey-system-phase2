"""单题跨问卷统计（设计文档 10.8，需求八）。

- 只统计**自己的**问卷中使用这道题的题目；只算已发布、已关闭的问卷（草稿没有答卷）
- 默认合并同一道题（同一 rootId）的所有版本；可以按版本筛选（问卷题目的 source.questionId）
- 每份问卷按它自己的提交策略选答卷（复用第一阶段 scope_filter，与单份问卷统计口径一致）
- 不显示填写人（无论问卷是否匿名）
- 结果：合并后的总体数据 + 每份问卷各自的数据
  - 单选 / 多选：按选项 id 合并（各版本沿用选项 id）；选项文字取参与统计的版本中版本号最大的
  - 答卷数各问卷相加；作答人数跨问卷去重
  - 数字：总体平均值按全部答案计算（不是各问卷平均值的平均）
  - 文本 / 数字内容：合并后按提交时间倒序分页，每条附问卷标题
"""
from bson import ObjectId
from pymongo.database import Database

from app.db import RESPONSES
from app.errors import ValidationFailed
from app.logic import survey_state as state
from app.repositories import questions as questions_repo
from app.repositories import surveys as surveys_repo
from app.repositories.responses import scope_filter
from app.services import question_library as library
from app.stats.cross_pipelines import Target, cross_question_pipeline
from app.utils import parse_object_id

INCLUDED_STATUSES = [state.PUBLISHED, state.CLOSED]
CHOICE_TYPES = ("single_choice", "multiple_choice")


def _version_filter(db: Database, root_id: ObjectId, version_ids: list[str] | None) -> set[ObjectId] | None:
    if not version_ids:
        return None
    errors, ids = [], []
    for i, raw in enumerate(version_ids):
        oid = parse_object_id(raw)
        if oid is None:
            errors.append({"field": f"versionId[{i}]", "message": f"版本 id {raw} 格式不正确"})
        else:
            ids.append(oid)
    found = {d["_id"]: d for d in questions_repo.find_many(db, ids)}
    for oid in ids:
        if oid not in found or found[oid]["rootId"] != root_id:
            errors.append({"field": "versionId", "message": f"{oid} 不是这道题的版本"})
    if errors:
        raise ValidationFailed(errors, "筛选条件不合法")
    return set(ids)


def _entries(db: Database, user_id: ObjectId, root_id: ObjectId, versions: set[ObjectId] | None) -> list[dict]:
    """参与统计的问卷：[{survey, question（问卷中的这道题）}]，新建的问卷在前。"""
    entries = []
    for survey in surveys_repo.find_for_cross_stats(db, user_id, root_id, INCLUDED_STATUSES):
        q = next(q for q in survey["questions"] if (q.get("source") or {}).get("rootId") == root_id)
        if versions is None or q["source"]["questionId"] in versions:
            entries.append({"survey": survey, "question": q})
    return entries


def _merged_options(entries: list[dict]) -> list[dict]:
    """各版本选项的并集：按版本号从大到小取，选项文字以版本号最大的为准，顺序也以它为准。"""
    merged: dict[str, str] = {}
    for e in sorted(entries, key=lambda e: e["question"]["source"]["version"], reverse=True):
        for o in e["question"].get("options") or []:
            merged.setdefault(o["id"], o["text"])
    return [{"id": oid, "text": text} for oid, text in merged.items()]


def cross_stats(db: Database, user_id: ObjectId, question_id: str, *, version_ids: list[str] | None,
                offset: int, limit: int) -> dict:
    doc = library.get_accessible(db, user_id, question_id)
    root_id, qtype = doc["rootId"], doc["type"]
    versions = _version_filter(db, root_id, version_ids)
    entries = _entries(db, user_id, root_id, versions)

    facet: dict = {}
    if entries:
        targets = [Target(e["survey"]["_id"], e["question"]["id"],
                          scope_filter(e["survey"]["settings"]["submissionPolicy"])) for e in entries]
        rows = list(db[RESPONSES].aggregate(cross_question_pipeline(targets, qtype, offset, limit)))
        facet = rows[0] if rows else {}

    per_survey = {row["_id"]: row for row in facet.get("perSurvey", [])}
    overall_totals = (facet.get("overall") or [{}])[0]
    titles = {e["survey"]["_id"]: e["survey"]["title"] for e in entries}

    surveys = []
    for e in entries:
        s, q = e["survey"], e["question"]
        totals = per_survey.get(s["_id"], {})
        surveys.append({
            "survey": s, "survey_question_id": q["id"], "source": q["source"],
            "answer_count": totals.get("answerCount", 0), "respondent_count": totals.get("respondentCount", 0),
        })
    overall = {
        "survey_count": len(entries),
        "answer_count": overall_totals.get("answerCount", 0),
        "respondent_count": overall_totals.get("respondentCount", 0),
    }

    if qtype in CHOICE_TYPES:
        counts: dict[tuple, int] = {(r["_id"]["s"], r["_id"]["o"]): r["count"] for r in facet.get("byOption", [])}
        for item, e in zip(surveys, entries):
            sid = e["survey"]["_id"]
            item["options"] = [{"id": o["id"], "text": o["text"], "count": counts.get((sid, o["id"]), 0)}
                               for o in e["question"]["options"]]
        overall["options"] = [{**o, "count": sum(c for (_, oid), c in counts.items() if oid == o["id"])}
                              for o in _merged_options(entries)]
    else:
        overall["items"] = [{"survey_id": r["surveyId"], "survey_title": titles.get(r["surveyId"], ""),
                             "value": r["value"], "submitted_at": r["submittedAt"]}
                            for r in facet.get("items", [])]
        overall["items_total"] = overall["answer_count"]
    if qtype == "number":
        averages = {r["_id"]: r["value"] for r in facet.get("average", [])}
        for item, e in zip(surveys, entries):
            item["average"] = averages.get(e["survey"]["_id"])
        overall["average"] = (facet.get("overallAverage") or [{}])[0].get("value")

    newest = max(entries, key=lambda e: e["question"]["source"]["version"], default=None)
    return {
        "question": doc, "type": qtype,
        "title": newest["question"]["title"] if newest else doc["title"],
        "version_filter": sorted(str(v) for v in versions) if versions else None,
        "overall": overall, "surveys": surveys,
    }
