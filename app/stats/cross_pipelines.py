"""单题跨问卷统计的聚合管道（只构造管道，不执行）。对应设计文档 10.8，需求八。

一道题（同一 rootId）在多份问卷中各有一个题目 id；每份问卷按自己的提交策略选答卷。
每个统计目标是 (问卷 _id, 问卷中这道题的 id, 该问卷的统计口径 scope)：

    $match  任一目标：问卷 + 口径 + 答了这道题   （每个分支可用 surveyId / answers.questionId 索引）
    $unwind answers
    $match  任一目标：问卷 + 这道题的答案         （只保留各问卷中这道题的答案）
    $facet  每份问卷的计数、总体计数（作答人数跨问卷去重）、按题型的分组、内容列表

与第一阶段单份问卷的管道（app/stats/pipelines.py）结构相同，只是把“一份问卷 + 一道题”换成多个目标。
**不显示填写人**：管道中没有 $lookup，任何阶段都不输出 respondentId（无论问卷是否匿名）。
"""
from dataclasses import dataclass

from bson import ObjectId


@dataclass(frozen=True)
class Target:
    survey_id: ObjectId
    question_id: str   # 问卷中这道题的 id
    scope: dict        # repositories.responses.scope_filter(问卷的提交策略)


def answers_stages(targets: list[Target]) -> list[dict]:
    """公共前三步：每条输出是“某份目标问卷的一份答卷中这道题的答案”。"""
    first = [{"surveyId": t.survey_id, **t.scope, "answers.questionId": t.question_id} for t in targets]
    third = [{"surveyId": t.survey_id, "answers.questionId": t.question_id} for t in targets]
    return [
        {"$match": {"$or": first}},
        {"$unwind": "$answers"},
        {"$match": {"$or": third}},
    ]


def per_survey_totals_stages() -> list[dict]:
    """每份问卷的答卷数和作答人数（先按 问卷 + 填写人 分组，与第一阶段 totals_stages 的做法相同）。"""
    return [
        {"$group": {"_id": {"s": "$surveyId", "r": "$respondentId"}, "n": {"$sum": 1}}},
        {"$group": {"_id": "$_id.s", "respondentCount": {"$sum": 1}, "answerCount": {"$sum": "$n"}}},
    ]


def overall_totals_stages() -> list[dict]:
    """合并后的答卷数和作答人数：作答人数跨问卷去重（同一个人填了两份问卷算 1 人）。"""
    return [
        {"$group": {"_id": "$respondentId", "n": {"$sum": 1}}},
        {"$group": {"_id": None, "respondentCount": {"$sum": 1}, "answerCount": {"$sum": "$n"}}},
        {"$project": {"_id": 0, "respondentCount": 1, "answerCount": 1}},
    ]


def items_stages(skip: int, limit: int) -> list[dict]:
    """合并后的内容列表（新的在前、分页），附问卷 id 以便显示问卷标题；不取、不输出填写人。"""
    return [
        {"$sort": {"submittedAt": -1, "_id": -1}},
        {"$skip": skip},
        {"$limit": limit},
        {"$project": {"_id": 0, "surveyId": 1, "value": "$answers.value", "submittedAt": 1}},
    ]


def cross_question_pipeline(targets: list[Target], qtype: str, skip: int = 0, limit: int = 20) -> list[dict]:
    """按题型构造完整管道。选项的合并（总体各选项次数）由各问卷的分组结果相加得到。"""
    facet = {"perSurvey": per_survey_totals_stages(), "overall": overall_totals_stages()}
    if qtype in ("single_choice", "multiple_choice"):
        by_option = [{"$unwind": "$answers.value"}] if qtype == "multiple_choice" else []
        by_option.append({"$group": {"_id": {"s": "$surveyId", "o": "$answers.value"}, "count": {"$sum": 1}}})
        facet["byOption"] = by_option
    else:
        facet["items"] = items_stages(skip, limit)
    if qtype == "number":
        facet["average"] = [{"$group": {"_id": "$surveyId", "value": {"$avg": "$answers.value"}}}]
        facet["overallAverage"] = [{"$group": {"_id": None, "value": {"$avg": "$answers.value"}}}]
    return answers_stages(targets) + [{"$facet": facet}]
