"""单题跨问卷统计（设计文档 10.8，需求八）。

- 只统计**自己的**问卷中使用这道题的题目；只算已发布、已关闭的问卷（草稿没有答卷）
- 默认合并同一道题（同一 rootId）的所有版本、所有问卷；可以按版本筛选（问卷题目的 source.questionId），
  也可以按问卷筛选（如比较“去年的问卷”和“今年的问卷”），两者同时给出时取交集
- 每份问卷按它自己的提交策略选答卷（复用第一阶段 scope_filter，与单份问卷统计口径一致）
- 不显示填写人（无论问卷是否匿名）
- 结果：合并后的总体数据 + 每份问卷各自的数据
  - 单选 / 多选：按选项 id 合并（各版本沿用选项 id）；选项文字取参与统计的版本中含有该选项的、版本号最大的版本；
    在参与统计的最新版本中已被删除的选项（只在旧版本中出现）照常计数，并标注 only_in_old_versions
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


def _candidates(db: Database, user_id: ObjectId, root_id: ObjectId) -> list[dict]:
    """可以参与统计的问卷：[{survey, question（问卷中的这道题）}]，新建的问卷在前。"""
    entries = []
    for survey in surveys_repo.find_for_cross_stats(db, user_id, root_id, INCLUDED_STATUSES):
        q = next(q for q in survey["questions"] if (q.get("source") or {}).get("rootId") == root_id)
        entries.append({"survey": survey, "question": q})
    return entries


def _survey_filter(candidates: list[dict], survey_ids: list[str] | None) -> set[ObjectId] | None:
    """按问卷筛选：必须是自己的、使用这道题的、已发布或已关闭的问卷。"""
    if not survey_ids:
        return None
    allowed = {e["survey"]["_id"] for e in candidates}
    errors, ids = [], set()
    for i, raw in enumerate(survey_ids):
        oid = parse_object_id(raw)
        if oid is None or oid not in allowed:
            errors.append({"field": f"surveyId[{i}]",
                           "message": f"{raw} 不是使用这道题的、已发布或已关闭的你的问卷"})
        else:
            ids.add(oid)
    if errors:
        raise ValidationFailed(errors, "筛选条件不合法")
    return ids


def _merged_options(entries: list[dict]) -> list[dict]:
    """参与统计的各版本选项的并集。

    按版本号从大到小取：先是最新版本的选项（顺序同最新版本），之后是只在旧版本中出现的选项；
    每个选项的文字取含有它的、版本号最大的版本。只在旧版本中出现的选项标注 only_in_old_versions。
    """
    ordered = sorted(entries, key=lambda e: e["question"]["source"]["version"], reverse=True)
    if not ordered:
        return []
    newest_ids = {o["id"] for o in ordered[0]["question"].get("options") or []}
    merged: dict[str, str] = {}
    for e in ordered:
        for o in e["question"].get("options") or []:
            merged.setdefault(o["id"], o["text"])
    return [{"id": oid, "text": text, "only_in_old_versions": oid not in newest_ids}
            for oid, text in merged.items()]


def cross_stats(db: Database, user_id: ObjectId, question_id: str, *, version_ids: list[str] | None,
                survey_ids: list[str] | None = None, offset: int = 0, limit: int = 20) -> dict:
    doc = library.get_accessible(db, user_id, question_id)
    root_id, qtype = doc["rootId"], doc["type"]
    versions = _version_filter(db, root_id, version_ids)
    candidates = _candidates(db, user_id, root_id)
    surveys_wanted = _survey_filter(candidates, survey_ids)
    entries = [e for e in candidates
               if (versions is None or e["question"]["source"]["questionId"] in versions)
               and (surveys_wanted is None or e["survey"]["_id"] in surveys_wanted)]

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
        "survey_filter": sorted(str(v) for v in surveys_wanted) if surveys_wanted else None,
        "overall": overall, "surveys": surveys,
    }
