# API 说明

> 本文件是 [README](../README.md#七api-说明) 中“API 说明”的完整版：每个接口的参数、返回示例和错误码。
> 第 1–6 节为第一阶段的接口（第二阶段没有改变它们的参数和返回格式）；**第 7–10 节为第二阶段新增的接口**。
> 运行服务后，http://127.0.0.1:8000/docs 提供可交互的接口文档（点 Authorize 填入令牌即可调试）。

## 通用约定

- **认证**：除注册、登录、`/api/meta`、`/api/health` 外，所有接口都需要请求头 `Authorization: Bearer <accessToken>`（登录接口返回）。
- **请求与响应**均为 JSON，字段名使用驼峰命名；时间为带时区的 ISO 8601（返回统一为 UTC，以 `Z` 结尾；提交时必须带时区）。
- **只能操作自己的问卷**：访问别人的问卷与访问不存在的问卷一样返回 404。
- **统一错误格式**：

```json
{ "code": "VALIDATION_ERROR", "message": "提交内容不合法",
  "errors": [ { "field": "username", "message": "用户名只能包含字母、数字和下划线" } ] }
```

`errors` 只在有字段级错误时出现；与题目相关的错误还带 `questionId`。

| 状态码 | 错误码 | 含义 |
|---|---|---|
| 400 | `BAD_REQUEST` | 请求体无法解析（如不是 UTF-8 编码） |
| 401 | `NOT_AUTHENTICATED` / `INVALID_TOKEN` / `TOKEN_EXPIRED` / `INVALID_CREDENTIALS` | 未登录 / 令牌无效 / 已过期 / 用户名或密码错误 |
| 404 | `SURVEY_NOT_FOUND` / `QUESTION_NOT_FOUND` / `SURVEY_NOT_PUBLISHED` / `NOT_FOUND` | 资源不存在（含别人的问卷）/ 问卷尚未发布 |
| 409 | `USERNAME_TAKEN` | 用户名已被注册 |
| 409 | `INVALID_STATUS` / `FIELD_LOCKED` | 当前状态不允许该操作 / 字段已锁定 |
| 409 | `EDIT_CONFLICT` / `QUESTION_REFERENCED` | 问卷已被修改 / 题目被跳转规则引用 |
| 409 | `SURVEY_CLOSED` / `SURVEY_EXPIRED` / `ALREADY_SUBMITTED` / `SUBMIT_CONFLICT` | 问卷已关闭 / 已截止 / 已填写过（once）/ 同时提交冲突 |
| 422 | `VALIDATION_ERROR` / `NO_QUESTIONS` | 输入不合法 / 没有题目不能发布 |
| 500 | `INTERNAL_ERROR` / `SURVEY_DATA_INVALID` | 服务器内部错误 / 问卷数据异常 |

第二阶段新增的错误码：

| 状态码 | 错误码 | 含义 |
|---|---|---|
| 403 | `NOT_OWNER` / `NOT_DIRECTLY_ACCESSIBLE` | 看得到但不是所有者，不能修改 / 只通过别人的题库看到的版本不能加入题库 |
| 404 | `QUESTION_NOT_FOUND` / `BANK_NOT_FOUND` / `ITEM_NOT_FOUND` | 题目（版本）不存在或无权访问 / 题库不存在或无权访问 / 题库中没有这道题 |
| 409 | `QUESTION_LOCKED` / `QUESTION_HAS_CHILDREN` / `QUESTION_IN_BANK` / `VERSION_CONFLICT` | 版本已被问卷使用 / 有其他版本从它派生或恢复 / 在题库中 / 同时创建版本冲突 |
| 409 | `QUESTION_ALREADY_IN_SURVEY` / `OPTION_ID_CONFLICT` / `NOT_FROM_LIBRARY` / `ALREADY_IN_LIBRARY` | 同一道题已在问卷中 / 选项 id 与问卷中其他题重复 / 不是来自已保存题目的题，不能换版本 / 已存入过 |
| 409 | `ALREADY_IN_BANK` | 同一道题已在题库中 |

## 接口总览（46 个，其中第二阶段新增 24 个）

| 模块 | 方法 | 路径 | 说明 |
|---|---|---|---|
| 账号 | POST | `/api/auth/register` | 注册 |
| | POST | `/api/auth/login` | 登录，返回令牌 |
| | GET | `/api/auth/me` | 当前用户 |
| 问卷管理 | POST | `/api/surveys` | 创建问卷（草稿） |
| | GET | `/api/surveys` | 我的问卷列表 |
| | GET | `/api/surveys/{id}` | 问卷详情（含题目和警告） |
| | PATCH | `/api/surveys/{id}` | 修改基本信息和设置 |
| | DELETE | `/api/surveys/{id}` | 删除草稿 |
| | POST | `/api/surveys/{id}/publish` | 发布 |
| | POST | `/api/surveys/{id}/close` | 关闭 |
| 题目 | POST | `/api/surveys/{id}/questions` | 添加题目 |
| | PUT | `/api/surveys/{id}/questions/{qid}` | 修改题目（含跳转规则） |
| | DELETE | `/api/surveys/{id}/questions/{qid}` | 删除题目 |
| | PUT | `/api/surveys/{id}/questions/order` | 调整题目顺序 |
| | POST | `/api/surveys/{id}/questions/from-library` | **第二阶段**：从已有题目添加（复制并记录来源） |
| | PUT | `/api/surveys/{id}/questions/{qid}/version` | **第二阶段**：换成同一道题的其他版本 |
| | POST | `/api/surveys/{id}/questions/{qid}/save-to-library` | **第二阶段**：存入我的题目 |
| 填写 | GET | `/api/s/{shortCode}` | 填写者获取问卷 |
| | POST | `/api/s/{shortCode}/path` | 路径预览（下一题与错误，不保存） |
| | POST | `/api/s/{shortCode}/responses` | 提交答卷 |
| 统计 | GET | `/api/surveys/{id}/stats` | 整份问卷统计 |
| | GET | `/api/surveys/{id}/stats/questions/{qid}` | 单题统计 |
| | GET | `/api/surveys/{id}/responses` | 答卷列表 |
| 我的题目（第二阶段） | POST | `/api/questions` | 新建题目（v1） |
| | GET | `/api/questions` | 版本列表（我的 / 共享给我的 / 公开的） |
| | GET | `/api/questions/groups` | 按题目分组的列表 |
| | GET | `/api/questions/{id}` | 版本详情（含能否删除） |
| | PUT | `/api/questions/{id}` | 直接修改未锁定的版本 |
| | DELETE | `/api/questions/{id}` | 删除版本 |
| | POST | `/api/questions/{id}/versions` | 创建新版本 |
| | POST | `/api/questions/{id}/restore` | 恢复旧版本（复制为新版本） |
| | GET | `/api/questions/{id}/history` | 版本历史 |
| | PUT | `/api/questions/{id}/sharing` | 共享设置 |
| | GET | `/api/questions/{id}/usage` | 被哪些问卷使用 |
| | GET | `/api/questions/{id}/stats` | 单题跨问卷统计 |
| 题库（第二阶段） | POST | `/api/banks` | 新建题库 |
| | GET | `/api/banks` | 题库列表 |
| | GET | `/api/banks/{id}` | 题库详情（含条目和提示） |
| | PATCH | `/api/banks/{id}` | 修改名称、说明 |
| | DELETE | `/api/banks/{id}` | 删除题库 |
| | PUT | `/api/banks/{id}/sharing` | 共享设置 |
| | POST | `/api/banks/{id}/items` | 加入题目 |
| | PUT | `/api/banks/{id}/items/{rootId}` | 换成这道题的其他版本 |
| | DELETE | `/api/banks/{id}/items/{rootId}` | 移除 |
| 其他 | GET | `/api/meta` | 题型、运算符表、长度上限（前端使用） |
| | GET | `/api/health` | 健康检查 |

运行服务后，http://127.0.0.1:8000/docs 提供可交互的接口文档（点 Authorize 填入令牌即可调试）。

## 1. 账号

### `POST /api/auth/register` 注册

| 参数（请求体） | 类型 | 说明 |
|---|---|---|
| `username` | string | 3–20 个字符，只能包含字母、数字、下划线；不区分大小写（保存为小写） |
| `password` | string | 至少 8 个字符，最多 72 字节 |

<details><summary>请求与返回示例</summary>

```json
// 请求
{ "username": "Alice_01", "password": "password123" }
// 201
{ "id": "6ad6008f4c5dce2dcadf114f", "username": "alice_01", "createdAt": "2026-10-19T11:35:43.182000Z" }
// 409
{ "code": "USERNAME_TAKEN", "message": "用户名已被注册" }
```
</details>

### `POST /api/auth/login` 登录

参数同注册。注册成功后不会自动登录，需再调用登录接口。

<details><summary>请求与返回示例</summary>

```json
// 请求
{ "username": "alice_01", "password": "password123" }
// 200
{ "accessToken": "eyJhbGciOiJIUzI1NiIs...", "tokenType": "bearer", "expiresIn": 86400,
  "user": { "id": "6ad6008f4c5dce2dcadf114f", "username": "alice_01", "createdAt": "2026-10-19T11:35:43.182000Z" } }
// 401（用户名不存在和密码错误返回完全相同的提示）
{ "code": "INVALID_CREDENTIALS", "message": "用户名或密码错误" }
```
</details>

### `GET /api/auth/me` 当前用户

无参数，返回 `{id, username, createdAt}`；未登录 401 `NOT_AUTHENTICATED`，令牌过期 401 `TOKEN_EXPIRED`。

## 2. 问卷管理

### `POST /api/surveys` 创建问卷

| 参数（请求体） | 类型 | 必填 | 说明 |
|---|---|---|---|
| `title` | string | 是 | 1–100 个字符 |
| `description` | string | 否 | 0–1000 个字符 |
| `allowAnonymous` | boolean | 否 | 默认 false |
| `submissionPolicy` | string | 否 | `once`（默认）/ `latest` / `all` |
| `deadline` | string \| null | 否 | 带时区的时间，必须晚于当前时间；null 表示不限 |

<details><summary>请求与返回示例</summary>

```json
// 请求
{ "title": "水果偏好调查", "description": "了解大家吃水果的习惯", "allowAnonymous": true,
  "submissionPolicy": "latest", "deadline": "2026-11-30T23:59:59+08:00" }
// 201（问卷详情，下面的“问卷详情”格式）
{ "id": "6ad6046148384937d865e193", "shortCode": "NSiZ9e", "url": "http://127.0.0.1:8000/survey/NSiZ9e",
  "title": "水果偏好调查", "description": "了解大家吃水果的习惯", "status": "draft", "isExpired": false,
  "settings": { "allowAnonymous": true, "submissionPolicy": "latest", "deadline": "2026-11-30T15:59:59Z" },
  "version": 1, "questions": [], "warnings": [],
  "createdAt": "2026-10-19T11:52:01.136000Z", "updatedAt": "2026-10-19T11:52:01.136000Z",
  "publishedAt": null, "closedAt": null }
// 422
{ "code": "VALIDATION_ERROR", "message": "提交内容不合法",
  "errors": [ { "field": "deadline", "message": "截止时间必须晚于当前时间" } ] }
```
</details>

### `GET /api/surveys` 我的问卷列表

无参数。返回数组，新的在前；每项不含题目，含 `questionCount`（题目数）与 `responseCount`（答卷数，口径与统计一致）。

<details><summary>返回示例</summary>

```json
[ { "id": "6ad6046148384937d865e193", "shortCode": "NSiZ9e", "url": "http://127.0.0.1:8000/survey/NSiZ9e",
    "title": "水果偏好调查", "status": "published", "isExpired": false,
    "settings": { "allowAnonymous": true, "submissionPolicy": "latest", "deadline": null },
    "questionCount": 5, "responseCount": 12,
    "createdAt": "...", "updatedAt": "...", "publishedAt": "...", "closedAt": null } ]
```
</details>

### `GET /api/surveys/{id}` 问卷详情

返回完整问卷（格式同创建问卷的返回），含 `questions`（含跳转规则）和 `warnings`（规则重叠、永远不会成立的规则、永远不会显示的题，不影响保存和发布）。

### `PATCH /api/surveys/{id}` 修改问卷

只提交要修改的字段（`title`、`description`、`allowAnonymous`、`submissionPolicy`、`deadline`）；`deadline: null` 表示改为不限。

| 问卷状态 | 可修改 |
|---|---|
| 草稿 | 全部 |
| 已发布 | 标题、说明、截止时间（必须晚于当前时间；已过期的问卷延长后恢复收集） |
| 已关闭 | 不能修改 |

<details><summary>返回示例</summary>

```json
// 200：问卷详情
// 409：已发布问卷修改提交策略（与当前值相同则不算修改）
{ "code": "FIELD_LOCKED", "message": "问卷已发布，不能修改提交策略（会影响已收集答卷的统计口径）",
  "errors": [ { "field": "submissionPolicy", "message": "问卷已发布，不能修改提交策略（会影响已收集答卷的统计口径）" } ] }
```
</details>

### `DELETE /api/surveys/{id}` 删除草稿

成功返回 204；已发布或已关闭的问卷 409 `INVALID_STATUS`。

### `POST /api/surveys/{id}/publish` 发布、`POST /api/surveys/{id}/close` 关闭

无请求体，成功返回问卷详情。发布条件：草稿、至少 1 道题、截止时间未过；只有已发布的问卷可以关闭，关闭后不能重新打开。

<details><summary>错误示例</summary>

```json
{ "code": "NO_QUESTIONS", "message": "问卷至少需要 1 道题才能发布" }
{ "code": "INVALID_STATUS", "message": "只有已发布的问卷可以关闭（当前状态：草稿）" }
```
</details>

## 3. 题目（只有草稿可以修改）

四个接口都可带查询参数 `expectedUpdatedAt`（读取问卷时看到的 `updatedAt`）：带了则检查期间问卷是否被修改过，被修改过返回 409 `EDIT_CONFLICT`。都返回修改后的完整问卷（含系统生成的 id 和 `warnings`）。每次修改后对整份问卷做一次合法性检查，不合法则拒绝本次修改。

### `POST /api/surveys/{id}/questions` 添加题目

| 参数（请求体） | 类型 | 说明 |
|---|---|---|
| `type` | string | `single_choice` / `multiple_choice` / `text` / `number` |
| `title` | string | 1–200 个字符 |
| `options` | `[{text}]` | 选择题必填，1–50 个，文字 1–100 个字符且不重复；id 由系统生成 |
| `validation` | object | `required`（默认 false）；多选 `minSelect`、`maxSelect`；文本 `minLength`、`maxLength`（≤ 10000）；数字 `min`、`max`、`integerOnly`。字段与题型不匹配直接拒绝 |
| `position` | integer | 可选，插入到第几题（从 1 开始），默认末尾 |

添加时**不接受跳转规则**（新题的选项 id 尚未生成），添加后通过修改题目设置。

<details><summary>请求与返回示例</summary>

```json
// 请求
{ "type": "multiple_choice", "title": "你喜欢哪些水果？",
  "options": [ {"text": "苹果"}, {"text": "香蕉"}, {"text": "榴莲"} ],
  "validation": { "required": true, "minSelect": 1, "maxSelect": 2 } }
// 201：完整问卷，其中新题为
{ "id": "q_m2n3p4", "type": "multiple_choice", "title": "你喜欢哪些水果？",
  "options": [ {"id": "o_g7h8i9", "text": "苹果"}, {"id": "o_j1k2l3", "text": "香蕉"}, {"id": "o_x9y8z7", "text": "榴莲"} ],
  "validation": { "required": true, "minSelect": 1, "maxSelect": 2 } }
// 422
{ "code": "VALIDATION_ERROR", "message": "题目设置不合法",
  "errors": [ { "questionId": "q_m2n3p4", "field": "validation.minSelect",
                "message": "第 2 题：最少选择数（5）不能大于选项数（3）" } ] }
```
</details>

### `PUT /api/surveys/{id}/questions/{qid}` 修改题目

整体替换一道题（id 不变）：`type`、`title`、`options`（保留的选项带原 `id`，新增选项只写 `text`，未出现的选项视为删除）、`validation`、`logic`（不提交表示没有跳转规则）。

`logic` 格式：`{ "rules": [ { "when": { "op": 运算符, "value": 值 }, "goto": 后面某题的 id 或 "END" } ], "defaultNext": null | "END" | 后面某题的 id }`。运算符见 [README 八、关键逻辑说明 → 2. 跳转](../README.md#2-跳转)。

<details><summary>请求与返回示例</summary>

```json
// 请求：选了“不喜欢”就跳到第 5 题，否则顺序进入下一题
{ "type": "single_choice", "title": "你喜欢吃水果吗？",
  "options": [ {"id": "o_a1b2c3", "text": "喜欢"}, {"id": "o_d4e5f6", "text": "不喜欢"} ],
  "validation": { "required": true },
  "logic": { "rules": [ { "when": { "op": "eq", "value": "o_d4e5f6" }, "goto": "q_p0x7mn" } ], "defaultNext": null } }
// 200：完整问卷
// 422：往前跳
{ "code": "VALIDATION_ERROR", "message": "题目设置不合法",
  "errors": [ { "questionId": "q_k3x9ab", "field": "logic.rules[0].goto",
                "message": "第 2 题第 1 条规则：只能跳转到后面的题目或 END（目标是第 1 题）" } ] }
```
</details>

### `DELETE /api/surveys/{id}/questions/{qid}` 删除题目

返回完整问卷；被其他题的跳转规则指向时 409：

```json
{ "code": "QUESTION_REFERENCED", "message": "第 1 题「你喜欢吃水果吗？」的第 1 条规则跳转到这道题，请先修改该规则",
  "errors": [ { "field": "id", "questionId": "q_p0x7mn", "message": "第 1 题「你喜欢吃水果吗？」的第 1 条规则跳转到这道题" } ] }
```

### `PUT /api/surveys/{id}/questions/order` 调整顺序

请求体 `{ "questionIds": [...] }`，必须恰好包含全部题目 id；调整后出现往前跳时 422（顺序不变）。

## 4. 填写（填写者，均需登录）

### `GET /api/s/{shortCode}` 获取问卷

返回填写者视角的问卷：题目只含 `id`、`type`、`title`、`options`、`validation`（**不含跳转规则**，也不含 `ownerId` 等内部字段）。已关闭或已过期时 `accepting: false`、`questions: null` 并给出 `notice`；草稿只有创建者能预览（`preview: true`），其他人 404 `SURVEY_NOT_PUBLISHED`。

<details><summary>返回示例</summary>

```json
{ "shortCode": "Food26", "title": "大学生饮食习惯调查", "description": "...",
  "settings": { "allowAnonymous": false, "submissionPolicy": "latest", "deadline": null },
  "status": "published", "isExpired": false, "accepting": true, "notice": null,
  "isOwner": false, "preview": false,
  "questions": [ { "id": "q_...", "type": "single_choice", "title": "你目前是在校大学生（含研究生）吗？",
                   "options": [ {"id": "o_...", "text": "是"}, {"id": "o_...", "text": "否"} ],
                   "validation": { "required": true } } ],
  "mySubmission": { "count": 1, "lastSubmittedAt": "2026-10-20T08:30:00Z", "canSubmit": true, "reason": null,
                    "latestAnswers": [ { "questionId": "q_...", "value": "o_..." } ] } }
```

`mySubmission.latestAnswers` 只在 `latest` 策略下返回本人最新一份答案（用于再次填写时预填）。
</details>

### `POST /api/s/{shortCode}/path` 路径预览

请求体 `{ "answers": [ { "questionId": "...", "value": ... } ] }`（最多 200 项）。答案中**没有**的题视为“还没答到”，值为 `null` 表示“看过但不答”。返回 200（有错误也是 200，错误放在 `errors` 中），不保存。

<details><summary>请求与返回示例</summary>

```json
// 请求：第 1 题选了“不喜欢”
{ "answers": [ { "questionId": "q_k3x9ab", "value": "o_d4e5f6" } ] }
// 200：跳到第 5 题
{ "path": ["q_k3x9ab", "q_p0x7mn"], "nextQuestionId": "q_p0x7mn", "finished": false, "errors": [] }
```
</details>

### `POST /api/s/{shortCode}/responses` 提交答卷

请求体同路径预览。后端**从第一题开始重新计算跳转路径并校验**：路径上必答题未答或答案不合法 → 422（只返回第一个错误，不保存）；路径外的答案丢弃。成功返回 201 和实际保存的（规范化后的）答案。

| 值的格式 | 示例 |
|---|---|
| 单选 | 选项 id：`"o_a1b2c3"` |
| 多选 | 选项 id 数组：`["o_g7h8i9", "o_x9y8z7"]`（保存时按选项顺序排列） |
| 文本 | 字符串（保存时去掉首尾空白） |
| 数字 | JSON 数字（不接受字符串；整数题 `7.0` 保存为 `7`；整数须在 64 位范围内） |

<details><summary>请求与返回示例</summary>

```json
// 请求
{ "answers": [ { "questionId": "q_k3x9ab", "value": "o_a1b2c3" },
               { "questionId": "q_m2n3p4", "value": ["o_x9y8z7", "o_g7h8i9"] },
               { "questionId": "q_r5s6t7", "value": 7.0 } ] }
// 201
{ "id": "6ad610bc6f7a52178c8edbcd", "submittedAt": "2026-10-19T12:44:44.219000Z", "isLatest": true,
  "answers": [ { "questionId": "q_k3x9ab", "value": "o_a1b2c3" },
               { "questionId": "q_m2n3p4", "value": ["o_g7h8i9", "o_x9y8z7"] },
               { "questionId": "q_r5s6t7", "value": 7 } ] }
// 422
{ "code": "VALIDATION_ERROR", "message": "答案不合法",
  "errors": [ { "questionId": "q_r5s6t7", "field": "value", "message": "第 3 题：必须为整数" } ] }
// 409（once 策略再次提交）
{ "code": "ALREADY_SUBMITTED", "message": "你已经填写过这份问卷（每人只能填写一次）" }
```
</details>

## 5. 统计（只有问卷创建者可以查看）

统计口径：`latest` 只算每人最新一份；`once`、`all` 算全部答卷。每道题同时返回**答卷数** `answerCount` 与**作答人数** `respondentCount`（按填写人去重，匿名问卷也返回数字）。匿名问卷不返回任何填写人信息。

### `GET /api/surveys/{id}/stats` 整份问卷统计

选择题返回全部选项的人数（次数），没人选的为 0；填空题返回最新 20 条内容和总数 `itemsTotal`；数字题另有平均值 `average`（没人作答时为 null）。

<details><summary>返回示例</summary>

```json
{ "surveyId": "...", "title": "水果偏好调查", "status": "published",
  "allowAnonymous": false, "submissionPolicy": "once", "scope": "全部答卷（每人一份）",
  "totalResponses": 4, "totalRespondents": 4,
  "questions": [
    { "questionId": "q_k3x9ab", "type": "single_choice", "title": "你喜欢吃水果吗？",
      "answerCount": 4, "respondentCount": 4,
      "options": [ {"id": "o_a1b2c3", "text": "喜欢", "count": 3}, {"id": "o_d4e5f6", "text": "不喜欢", "count": 1} ] },
    { "questionId": "q_r5s6t7", "type": "number", "title": "你每周吃几次水果？",
      "answerCount": 3, "respondentCount": 3, "average": 3.3333333333333335, "itemsTotal": 3,
      "items": [ { "value": 0, "submittedAt": "...", "username": "zhao_liu" },
                 { "value": 3, "submittedAt": "...", "username": "li_si" },
                 { "value": 7, "submittedAt": "...", "username": "zhang_san" } ] } ] }
```

匿名问卷的 `items` 中没有 `username` 字段。
</details>

### `GET /api/surveys/{id}/stats/questions/{qid}` 单题统计

查询参数 `offset`（默认 0）、`limit`（默认 50，最多 200）：填空题内容分页，可以查看全部。返回问卷层面的总数、`question`（格式同上）、`offset`、`limit`。

### `GET /api/surveys/{id}/responses` 答卷列表

查询参数 `offset`（默认 0）、`limit`（默认 20，最多 100）。口径与统计一致（`latest` 不含历史版本），新的在前。

<details><summary>返回示例</summary>

```json
{ "surveyId": "...", "scope": "每人最新一份答卷", "total": 12, "offset": 0, "limit": 20,
  "items": [ { "id": "6ad6...", "submittedAt": "...", "username": "demo_s12",
               "answers": [ { "questionId": "q_...", "value": "o_..." } ] } ] }
```

匿名问卷的每一项没有 `username`。
</details>

## 6. 其他

- `GET /api/meta`：题型列表、各题型允许的校验字段、**运算符表**（直接来自 `app/logic/operators.py`）、各项长度上限。前端的跳转规则编辑器据此显示可选的运算符，不维护副本。不需要登录。
- `GET /api/health`：`{"status": "ok", "database": "ok"}`；数据库不可用时 503。

---

# 第二阶段新增接口

> 题目保存与复用、版本、共享、题库、被哪些问卷使用、单题跨问卷统计。设计依据见 [DATABASE_DESIGN.md 第十节](DATABASE_DESIGN.md)。
> 页面上的“我的题目”对应接口 `/api/questions`，“题库”对应 `/api/banks`。第一阶段的接口和返回格式都没有变化（问卷题目多了一个可选字段 `source`，见第 8 节）。

**权限约定**：看不到的题目、题库与不存在一样返回 404（不暴露是否存在）；看得到但不是所有者却要修改返回 403 `NOT_OWNER`。**共享名单**（`sharing`）只返回给所有者，其他人看到的是 `null`。所有者显示为用户名，不返回用户 id。

## 7. 我的题目：题目与版本

每个版本是一条记录，返回格式（`QuestionVersionOut`）：

```json
{ "id": "6ae3...fae", "rootId": "6ae3...fae", "parentId": null, "restoredFrom": null, "version": 1,
  "owner": "alice", "isMine": true, "locked": false,
  "type": "single_choice", "title": "你的性别",
  "options": [ {"id": "o_3gd4wa", "text": "男"}, {"id": "o_pxvhep", "text": "女"} ],
  "validation": {},
  "sharing": { "public": false, "userIds": [], "usernames": [] },
  "canDelete": null, "deleteBlockedReason": null,
  "createdAt": "2026-10-29T09:59:49.315Z", "updatedAt": "2026-10-29T09:59:49.315Z" }
```

| 字段 | 说明 |
|---|---|
| `rootId` | 属于哪道题（最初那个版本的 id）；`parentId` 从哪个版本改来；`restoredFrom` 恢复时内容来自哪个版本 |
| `locked` | 已被问卷使用：不能直接修改，只能基于它创建新版本 |
| `validation` | 同第一阶段，但**不含 `required`**（是否必答在问卷中设置）；题目中也没有跳转规则 |
| `sharing` | 只对所有者返回，否则为 `null` |
| `canDelete`、`deleteBlockedReason` | 只在详情接口中对所有者返回：能否删除、不能时的原因；其他接口中为 `null` |

### `POST /api/questions` 新建题目

请求体 `{type, title, options?, validation?}`，规则同第一阶段的添加题目（选项只写 `text`），但 `validation` 中不能有 `required`，也不接受 `logic`。返回 201 和 v1（`rootId` 等于自己的 `id`，默认不共享）。

### `GET /api/questions` 版本列表、`GET /api/questions/groups` 按题目分组

| 查询参数 | 说明 |
|---|---|
| `scope` | `mine` 我的（默认）/ `shared` 共享给我的 / `public` 公开的（不含自己的）/ `all` 全部可访问的 |
| `rootId` | 只看某道题的版本（仅 `/api/questions`） |
| `offset`、`limit` | 分页，`limit` 默认 20、最多 100 |

`/api/questions` 每个版本一项；**`/api/questions/groups` 同一道题只出现一次**（页面使用），代表版本 `latest` 为该范围内版本号最大的版本，`versions` 列出该范围内这道题的所有版本：

```json
{ "items": [ { "rootId": "6ae3...fae",
               "latest": { "id": "6ae3...fb0", "version": 3, "restoredFrom": "6ae3...fae", "owner": "alice", "isMine": false,
                           "title": "你的性别", "sharing": null, "...": "（同 QuestionVersionOut）" },
               "versions": [ {"id": "6ae3...fae", "version": 1, "owner": "alice"},
                             {"id": "6ae3...faf", "version": 2, "owner": "alice"},
                             {"id": "6ae3...fb0", "version": 3, "owner": "alice"} ] } ],
  "total": 1, "offset": 0, "limit": 20 }
```

### `GET /api/questions/{id}` 版本详情

可访问时返回 `QuestionVersionOut`；所有者另外得到 `canDelete` 和 `deleteBlockedReason`（如“这个版本已被问卷使用，不能删除”）。

### `PUT /api/questions/{id}` 直接修改

只有所有者、只能修改**未锁定**的版本。请求体同新建（整体提交；保留的选项带原 `id`，新增选项不带 `id`，未提交的视为删除），`type` 必须与原版本相同。可带查询参数 `expectedUpdatedAt` 检查编辑冲突。

| 情况 | 返回 |
|---|---|
| 已锁定 | 409 `{"code": "QUESTION_LOCKED", "message": "这个版本已被问卷使用，不能直接修改；请基于它创建新版本"}` |
| 不是所有者 | 403 `{"code": "NOT_OWNER", "message": "这是别人共享给你的题目，不能直接修改；可以基于它创建自己的新版本"}` |
| 改了题型 | 422，`errors` 字段 `type`：“同一道题的各个版本题型必须相同；要换题型请新建一道题” |
| 期间被修改 | 409 `EDIT_CONFLICT` |

### `POST /api/questions/{id}/versions` 创建新版本

基于一个可访问的版本（锁定与否都可以，别人共享的也可以）创建**自己的**新版本：请求体同直接修改。`parentId` 为该版本，`version` 为这道题现有最大版本号 + 1；**选项 id 保持不变**：保留的选项（包括只改了文字的）带原 id，新增选项生成在这道题所有版本中都没用过的 id。新版本继承自己在这道题上的共享设置。返回 201。

```json
// 请求：基于 v1，把“女”改为“女性”，新增“其他”
{ "type": "single_choice", "title": "你的性别",
  "options": [ {"id": "o_3gd4wa", "text": "男"}, {"id": "o_pxvhep", "text": "女性"}, {"text": "其他"} ] }
// 201：v2，options 为 [ {"id": "o_3gd4wa", "text": "男"}, {"id": "o_pxvhep", "text": "女性"}, {"id": "o_zxb7ij", "text": "其他"} ]
```

### `POST /api/questions/{id}/restore` 恢复旧版本

把 `{id}` 的内容复制成一个新版本（`restoredFrom` = `{id}`），旧版本不变。请求体可选 `{"parentId": "..."}`：接在哪个版本后面（必须是同一道题）；不填时接在**自己**在这道题下版本号最大的版本后面，自己还没有版本时接在被恢复的版本后面。返回 201。

### `GET /api/questions/{id}/history` 版本历史

这道题的全部版本，按版本号排序；无权查看的版本只有版本号和父子关系（`accessible: false`，`detail: null`），版本树不会断开：

```json
{ "rootId": "6ae3...fae",
  "versions": [ { "id": "6ae3...fae", "version": 1, "parentId": null, "restoredFrom": null, "accessible": true, "detail": { "...": "QuestionVersionOut" } },
                { "id": "6ae3...faf", "version": 2, "parentId": "6ae3...fae", "restoredFrom": null, "accessible": true, "detail": { "...": "..." } },
                { "id": "6ae3...fb0", "version": 3, "parentId": "6ae3...faf", "restoredFrom": "6ae3...fae", "accessible": true, "detail": { "...": "..." } } ] }
```

### `PUT /api/questions/{id}/sharing` 共享设置

只有所有者。请求体 `{"public": true|false, "usernames": ["bob", ...]}`，**整体替换**原设置（空数组 = 不共享给任何人）；以整道题为单位，同时作用于自己在这道题下的所有版本。用户名去首尾空格、去重；不存在的用户、共享给自己、超过 100 个用户时 422（如 `{"field": "usernames[0]", "message": "用户「nobody」不存在"}`），原设置不变。不改 `updatedAt`。

```json
// 200
{ "question": { "...": "QuestionVersionOut", "sharing": { "public": false, "userIds": ["6ae3...fad"], "usernames": ["bob"] } },
  "updatedVersions": 3 }
```

### `DELETE /api/questions/{id}` 删除版本

只有所有者；成功 204。被问卷用过（409 `QUESTION_LOCKED`）、有其他版本从它派生或恢复（409 `QUESTION_HAS_CHILDREN`）、在任何人的题库中（409 `QUESTION_IN_BANK`）的版本不能删除——删除不能影响已有问卷和别人的题库。

## 8. 问卷使用已保存的题

问卷题目（第一阶段 `questions[]` 的每一项）新增**可选字段** `source`，记录来自哪个版本；没有 `source` 的题（第一阶段的题、问卷中直接建的题）一切照旧。`source` 由系统维护，请求中带 `source` 会被拒绝（422）。填写者获取问卷时看不到 `source`。

```json
{ "id": "q_w2y9bk", "type": "single_choice", "title": "你的性别",
  "options": [ {"id": "o_3gd4wa", "text": "男"}, {"id": "o_pxvhep", "text": "女"} ],
  "validation": { "required": true },
  "source": { "questionId": "6ae3...fae", "rootId": "6ae3...fae", "version": 1 } }
```

### `POST /api/surveys/{id}/questions/from-library` 从已有题目添加

只有草稿。请求体 `{"questionId": 版本 id, "required": false, "position": null}`：把这个版本的内容**复制**进问卷（选项 id 沿用），记录 `source`，版本随之锁定。跳转规则添加后通过“修改题目”设置。可带 `expectedUpdatedAt`。返回 201 和完整问卷。

| 情况 | 返回 |
|---|---|
| 同一道题（同一 `rootId`）已在问卷中 | 409 `QUESTION_ALREADY_IN_SURVEY`“这道题已经在问卷中（第 1 题），同一道题在一份问卷中只能出现一次” |
| 选项 id 与问卷中其他题重复（概率极低） | 409 `OPTION_ID_CONFLICT` |
| 版本不可访问 / 问卷不是草稿 / 已有 100 道题 | 404 / 409 `INVALID_STATUS` / 422 |

### `PUT /api/surveys/{id}/questions/{qid}` 修改来自已保存题目的题

仍用第一阶段的修改接口（整体提交）。对有 `source` 的题，**只能改 `validation.required` 和跳转规则 `logic`**；题型、题目、选项（含文字和 id）、其他校验必须与当前相同，否则 422（字段 `source`，提示“在‘我的题目’中创建新版本后换版本”）。

### `PUT /api/surveys/{id}/questions/{qid}/version` 换版本

只有草稿。请求体 `{"questionId": 目标版本 id}`，必须是同一道题的可访问版本。题目在问卷中的 id、`required`、跳转规则保留，内容换成新版本，`source` 更新，新版本加锁。跳转规则引用的选项在新版本中不存在时 422（指出是哪个选项）；问卷中直接建的题 409 `NOT_FROM_LIBRARY`。返回完整问卷。

### `POST /api/surveys/{id}/questions/{qid}/save-to-library` 存入我的题目

只有问卷创建者；**任何状态的问卷都可以**（只补来源信息，不改题目内容和答卷）。用这道题的内容生成新题 v1（选项 id 沿用、`validation` 去掉 `required`、不含跳转规则、创建即锁定、不共享），并给原题补上 `source`。已有 `source` 的题 409 `ALREADY_IN_LIBRARY`；期间问卷被修改 409 `EDIT_CONFLICT`（此时撤销 v1）。返回 201：

```json
{ "survey": { "...": "完整问卷，这道题多了 source" },
  "question": { "id": "6ae3...fb2", "version": 1, "locked": true, "type": "text", "title": "备注", "validation": {}, "...": "..." } }
```

## 9. 题库

一个题库的每一项是一道题的一个**固定版本**；同一道题在一个题库中只有一项，所以条目用 `rootId` 标识。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/banks` | 新建，请求体 `{name, description?}`（名称 1–100 字，说明 0–1000 字） |
| GET | `/api/banks?scope=mine\|shared\|public\|all&offset=&limit=` | 列表（不含条目，含 `itemCount`） |
| GET | `/api/banks/{id}` | 详情（含条目） |
| PATCH | `/api/banks/{id}` | 修改名称、说明（只提交要改的字段） |
| DELETE | `/api/banks/{id}` | 删除（不影响问卷和题目），204 |
| PUT | `/api/banks/{id}/sharing` | 共享设置，请求体与规则同题目共享 |
| POST | `/api/banks/{id}/items` | 加入一个版本 `{questionId}`；放进题库**不加锁** |
| PUT | `/api/banks/{id}/items/{rootId}` | 把这道题的一项换成另一个版本 `{questionId}` |
| DELETE | `/api/banks/{id}/items/{rootId}` | 移除这一项 |

**只有创建者能修改题库**；共享后别人可以查看、把其中的版本用在自己的问卷中、基于它们创建自己的新版本（这些版本即使没有单独共享给他也可以）。加入的版本必须是创建者**直接**可访问的（自己的、共享给自己的、公开的），只通过别人的题库看到的版本不能再加入题库（403 `NOT_DIRECTLY_ACCESSIBLE`）。同一道题再加入 409 `ALREADY_IN_BANK`；每个题库最多 200 项。

详情中每一项：`available` 是否可用（题库创建者**现在**仍能访问该版本），不可用时没有 `question`；`newerVersion` 和 `notice` **只对创建者**返回（有新版本可换、不可用的原因和处理办法），其他人为 `null`：

```json
{ "id": "6ae3...fb6", "name": "常用题", "description": "每学期都用", "owner": "alice", "isMine": true, "itemCount": 1,
  "sharing": { "public": false, "userIds": [], "usernames": [] },
  "items": [ { "questionId": "6ae3...fae", "rootId": "6ae3...fae", "addedAt": "...", "available": true,
               "question": { "...": "QuestionVersionOut（v1）" },
               "newerVersion": { "questionId": "6ae3...fb0", "version": 3 },
               "notice": "有新版本 v3 可换" } ],
  "createdAt": "...", "updatedAt": "..." }
```

不可用时 `notice` 如“原作者 carol 已取消共享（或不再公开）这道题，你已不能使用这个版本；请移除这一项，或换成 v2”。

## 10. 被哪些问卷使用、单题跨问卷统计

### `GET /api/questions/{id}/usage` 被哪些问卷使用

查询参数 `scope`：`version`（默认，只看这个版本）/ `question`（整道题的所有版本）。能访问这个版本的人都可以查；**自己的问卷**显示标题、状态、链接，**别人的问卷只给数量**。草稿、已发布、已关闭都计入；只依据问卷题目的 `source`。

```json
{ "scope": "question", "questionId": "6ae3...fae", "rootId": "6ae3...fae",
  "mine": [ { "id": "6ae3...fb1", "title": "年度调查", "status": "published", "isExpired": false,
              "shortCode": "czx3rn", "url": "http://127.0.0.1:8000/survey/czx3rn",
              "surveyQuestionId": "q_w2y9bk", "questionId": "6ae3...faf", "version": 2 } ],
  "mineCount": 1, "othersCount": 0, "totalCount": 1 }
```

### `GET /api/questions/{id}/stats` 单题跨问卷统计

只统计**自己的已发布、已关闭**问卷中使用这道题的题目；每份问卷按它自己的提交策略选答卷（与第 5 节口径相同）；**不显示填写人**（无论问卷是否匿名）。

| 查询参数 | 说明 |
|---|---|
| `versionId` | 只统计这些版本（可重复）；不填则合并整道题的所有版本 |
| `surveyId` | 只统计这些问卷（可重复），必须是自己的、使用这道题的、已发布或已关闭的问卷；与 `versionId` 同时给出时取交集 |
| `offset`、`limit` | 文本、数字题合并后的内容分页，`limit` 默认 20、最多 200 |

- `overall`：问卷数、答卷数（各问卷相加）、**作答人数（跨问卷去重）**；单选、多选的选项**按选项 id 合并**，文字取参与统计的版本中含有该选项的最新版本，在参与统计的最新版本中已被删除的选项照常计数并标注 `onlyInOldVersions: true`；数字题的 `average` 按全部答案计算；文本、数字题的 `items` 每条附所在问卷。
- `surveys`：每份问卷各自的数据（与第 5 节单题统计一致）。

```json
{ "questionId": "6ae3...fae", "rootId": "6ae3...fae", "type": "single_choice", "title": "你的性别",
  "versionFilter": null, "surveyFilter": null,
  "overall": { "surveyCount": 1, "answerCount": 3, "respondentCount": 1,
               "options": [ {"id": "o_3gd4wa", "text": "男", "count": 1, "onlyInOldVersions": false},
                            {"id": "o_pxvhep", "text": "女性", "count": 2, "onlyInOldVersions": false},
                            {"id": "o_zxb7ij", "text": "其他", "count": 0, "onlyInOldVersions": false} ],
               "average": null, "items": null, "itemsTotal": null },
  "surveys": [ { "surveyId": "6ae3...fb1", "title": "年度调查", "status": "published", "isExpired": false,
                 "url": "http://127.0.0.1:8000/survey/czx3rn", "submissionPolicy": "all",
                 "surveyQuestionId": "q_w2y9bk", "questionId": "6ae3...faf", "version": 2,
                 "answerCount": 3, "respondentCount": 1,
                 "options": [ {"id": "o_3gd4wa", "text": "男", "count": 1}, {"id": "o_pxvhep", "text": "女性", "count": 2},
                              {"id": "o_zxb7ij", "text": "其他", "count": 0} ],
                 "average": null } ] }
```

数字、文本题的 `items` 每一项为 `{surveyId, surveyTitle, value, submittedAt}`，`itemsTotal` 为总条数。
