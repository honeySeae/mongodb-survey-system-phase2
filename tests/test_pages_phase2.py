"""第二阶段第 10 步：新增页面的路由和静态资源（第一阶段 tests/test_pages.py 不改动）。

第一阶段 test_pages.py 中“不引用外部资源”“不使用 innerHTML”两条检查遍历 static/ 下所有文件，
新页面、新脚本自动包括在内。
"""
import pytest


@pytest.mark.parametrize("path, marker", [
    ("/questions", "questions.js"),
    ("/questions/abc", "question.js"),
    ("/banks", "banks.js"),
    ("/banks/abc", "bank.js"),
    ("/questions/abc/stats", "question-stats.js"),
])
def test_library_pages_served_as_html(client, path, marker):
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.headers["cache-control"] == "no-cache"
    assert marker in resp.text
    assert "/static/css/style.css" in resp.text        # 与第一阶段页面共用同一份样式


@pytest.mark.parametrize("path", ["/static/js/questions.js", "/static/js/question.js",
                                  "/static/js/library-editor.js", "/static/js/library-common.js",
                                  "/static/js/edit-library.js", "/static/js/library-picker.js",
                                  "/static/js/banks.js", "/static/js/bank.js", "/static/js/question-stats.js"])
def test_library_scripts(client, path):
    resp = client.get(path)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/javascript")


def test_library_pages_not_in_api_docs(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/questions" not in paths and "/questions/{question_id}" not in paths
    assert "/banks" not in paths and "/banks/{bank_id}" not in paths
    assert "/api/questions" in paths
