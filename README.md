# 基于 MongoDB 的在线问卷系统

一个简化版的在线问卷系统（类似问卷星 / Google Forms）：注册用户创建问卷，设置题目、校验规则和跳转规则，发布后通过链接 `/survey/<shortCode>` 分发；其他用户登录后填写，创建者查看实时统计。第二阶段增加了**题目保存与复用、版本管理、共享、题库和单题跨问卷统计**。所有数据存储在 MongoDB 中。

> 课程项目**第二阶段**：在第一阶段代码的基础上修改扩展（第一阶段的代码见标签 `phase1`），第一阶段的功能和数据保持可用。
> - **GitHub 仓库（第二阶段）**：https://github.com/honeySeae/mongodb-survey-system-phase2
> - 第一阶段仓库：https://github.com/honeySeae/mongodb-survey-system（保留不动）
> - **示例数据**：第一阶段示例问卷 http://127.0.0.1:8000/survey/Food26（`python -m scripts.seed_demo`）；第二阶段示例（三个学期的课程评价，`python -m scripts.seed_phase2`），见[十、示例数据](#十示例数据)

## 目录

[一、项目简介](#一项目简介) · [二、快速开始](#二快速开始) · [三、部署](#三部署) · [四、技术栈与版本](#四技术栈与版本) · [五、项目结构](#五项目结构) · [六、数据库设计](#六数据库设计) · [七、API 说明](#七api-说明) · [八、关键逻辑说明](#八关键逻辑说明) · [九、测试](#九测试) · [十、示例数据](#十示例数据) · [十一、文档索引](#十一文档索引)

---

## 一、项目简介

| 功能 | 说明 |
|---|---|
| 账号 | 注册、登录（JWT），密码用 bcrypt 哈希；登录后只能看到自己创建的问卷 |
| 问卷管理 | 创建（标题、说明、是否匿名、提交策略、截止时间）、我的问卷列表、发布、关闭、删除草稿；每份问卷有 `/survey/<shortCode>` 链接 |
| 题型 | 单选（选项、必答）；多选（至少 / 最多 / 必须选几项）；文本填空（最少 / 最多字数）；数字填空（最小值、最大值、是否整数） |
| 跳转 | 按单选、多选、数字的答案跳到后面的题或结束问卷；规则存在问卷数据中，用下拉框设置，保存时检查合法性 |
| 填写 | 填写前需登录；逐题展开，由后端计算下一题；不合法时提示错误；**提交时后端重新计算跳转路径并校验**；支持多人同时填写、匿名、多次填写（三种提交策略） |
| 统计 | 单选各选项人数与作答人数；多选各选项被选次数；填空列出全部内容，数字题给出平均值；整份问卷统计与单题统计；聚合管道实时计算；匿名问卷不返回填写人 |

**第二阶段新增**（需求见老师的第二阶段需求变更说明，设计见 [docs/DATABASE_DESIGN.md 第十节](docs/DATABASE_DESIGN.md)）：

| 需求 | 实现 | 页面 |
|---|---|---|
| 一、保存常用题目，重复使用 | 题目独立保存在 `questions` 集合；做问卷时“从已有题目添加”，**复制**进问卷并记录来源（`source`）；问卷中直接建的题可以“存入我的题目”（已发布的问卷也可以） | 我的题目；问卷编辑页 |
| 二、把题目分享给别人 | 以整道题为单位共享给指定用户或公开；被共享的人可以使用、基于它创建自己的新版本，不能修改；共享名单只有所有者看得到 | 题目详情 → 共享设置 |
| 三、修改题目不影响已有问卷 | 问卷里是副本；被问卷用过的版本**锁定**，只能创建新版本 | 题目详情 |
| 四、修改历史、恢复旧版本 | 每个版本一条记录，`parentId` 记录从哪个版本改来；版本历史以树形显示并说明每个版本改了什么；恢复 = 把旧版本复制成新版本 | 题目详情 → 版本历史 |
| 五、同一道题的不同版本同时存在 | 不设“当前版本”，不同问卷可以用不同版本；问卷中的题可以“换版本” | 问卷编辑页 |
| 六、查看题目被哪些问卷使用 | 按版本或整道题查询；自己的问卷显示标题、状态、链接，别人的只显示数量 | 题目详情 |
| 七、题库 | `questionBanks` 集合，每一项是一个固定版本；有新版本时提示“有新版本 vN 可换”；可共享；做问卷时“从已有题目添加 → 题库” | 题库 |
| 八、单题跨问卷统计 | 合并同一道题各版本在自己所有问卷中的回答（按选项 id 合并，作答人数跨问卷去重），可按版本、按问卷筛选，同时给出每份问卷各自的结果 | 题目详情 → 跨问卷统计 |

---

## 二、快速开始

**环境要求**：Python 3.11 及以上；MongoDB 5.0 及以上（统计中的 `$lookup` 写法需要 5.0+）。Node.js 22+ 和 Chrome / Edge 只有界面测试需要，没有时这些测试自动跳过。

### 1. 安装依赖

```bash
git clone https://github.com/honeySeae/mongodb-survey-system-phase2.git && cd mongodb-survey-system-phase2
python -m venv .venv
.venv\Scripts\activate            # Windows（PowerShell / cmd）
# source .venv/bin/activate       # Mac / Linux
pip install -r requirements.txt
```

### 2. 启动 MongoDB

- **Windows**：首次需要安装 MongoDB 并创建 `C:\data\mongod.cfg`（只监听 127.0.0.1，步骤见 [docs/DEPLOY.md](docs/DEPLOY.md#windows默认方式开发时使用)）。之后**每次开发或运行测试前双击 [`scripts/start_mongo.bat`](scripts/start_mongo.bat) 并保持窗口开着**；也可以直接运行 `mongod --config C:\data\mongod.cfg`。
- **Mac**：`brew services start mongodb-community`（安装见 [docs/DEPLOY.md](docs/DEPLOY.md#machomebrew)）。
- **Linux 服务器**：见[三、部署](#三部署)。
- 验证：`mongosh --eval "db.runCommand({ping:1})"` 输出 `{ ok: 1 }`。

### 3. 配置 `.env`

```bash
copy .env.example .env      # Windows；Mac / Linux：cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # 生成 JWT_SECRET，填入 .env
```

| 变量 | 作用 | 本地示例 |
|---|---|---|
| `MONGO_URI` | MongoDB 连接串 | `mongodb://127.0.0.1:27017` |
| `MONGO_DB_NAME` | 数据库名（测试自动改用 `survey_test`） | `survey_dev` |
| `JWT_SECRET` | 登录令牌签名密钥，**至少 32 个字符**；`.env.example` 中的示例值会被拒绝 | 用上面的命令生成 |
| `JWT_EXPIRE_MINUTES` | 登录有效期（分钟） | `1440` |
| `PUBLIC_BASE_URL` | 对外访问地址，用于生成问卷链接，结尾不加 `/` | `http://127.0.0.1:8000` |
| `BCRYPT_ROUNDS` | 可选，bcrypt 强度，默认 12 | 不设置 |

`MONGO_URI`、`JWT_SECRET`、`PUBLIC_BASE_URL` 没有默认值，缺少或不合法时程序拒绝启动并给出提示。

### 4. 初始化数据库、启动服务、生成示例数据

```bash
python -m scripts.init_db          # 可选：创建集合、$jsonSchema 校验和索引（启动服务时也会自动执行，可重复执行）
uvicorn app.main:app --reload      # 启动服务
python -m scripts.seed_demo        # 第一阶段示例问卷 Food26（另开一个终端，或先于服务运行均可）
python -m scripts.seed_phase2      # 第二阶段示例数据：题目版本、共享、题库、跨问卷统计
```

已有第一阶段数据的数据库**不需要迁移**：启动时自动创建第二阶段的新集合和索引，旧问卷、旧答卷原样可用（验证见 [docs/COMPAT_VERIFICATION.md](docs/COMPAT_VERIFICATION.md)）。

浏览器打开 **http://127.0.0.1:8000**（进入登录页）；接口文档 http://127.0.0.1:8000/docs ；健康检查 `/api/health` 返回 `{"status":"ok","database":"ok"}`。

> 本地请用 `127.0.0.1`，不要用 `localhost`：Windows 会先尝试 IPv6 的 `::1`，而 uvicorn 默认只监听 IPv4，每个请求要多等约 2 秒。

运行测试见[九、测试](#九测试)。

---

## 三、部署

本项目目前只在本地运行，没有部署到服务器。本节和 docs/DEPLOY.md 只是部署说明，其中的服务器步骤没有在服务器上实际验证过。

部署到阿里云 Linux 服务器（Ubuntu 24.04、systemd）的完整步骤见 **[docs/DEPLOY.md](docs/DEPLOY.md#二部署到-linux-服务器阿里云)**。要点：

- MongoDB 只监听本机（`bindIp: 127.0.0.1`），安全组**只开放 8000 端口，不开放 27017**；
- **必须重新生成 `JWT_SECRET`**，`PUBLIC_BASE_URL` 改为服务器的公网地址；
- 生成示例问卷时用 `--owner-password` 换掉创建者密码。

---

## 四、技术栈与版本

**前端**：原生 HTML + CSS + JavaScript（ES 模块），由后端静态托管；不使用任何前端框架、CDN 或外部字体。

| 组件 | 版本 | 用途 |
|---|---|---|
| Python | 3.14.2（要求 3.11+） | 开发语言 |
| FastAPI / Uvicorn | 0.147.0 / 0.54.0 | Web 框架 / ASGI 服务器 |
| PyMongo | 4.19.0 | MongoDB 驱动 |
| Pydantic / pydantic-settings | 2.14.1 / 2.16.0 | 请求响应模型、读取配置 |
| bcrypt / PyJWT / python-dotenv | 5.0.0 / 2.15.1 / 1.2.4 | 密码哈希 / 登录令牌 / 读取 `.env` |
| MongoDB | 8.3.11（要求 5.0+） | 数据库 |
| pytest / httpx2 / pytest-cov | 9.1.1 / 2.14.0 / 7.1.0 | 测试框架 / TestClient 的 HTTP 客户端 / 覆盖率 |
| Node.js / Chrome | 24.14.0 / 155（可选） | 界面测试（无界面 Chrome）、前端纯函数测试 |

全部 Python 依赖及版本见 [`requirements.txt`](requirements.txt)。**没有使用任何现成的问卷系统框架或库**（如 SurveyJS、xiaoju-survey）。

---

## 五、项目结构

```
app/            后端：routers（接口）→ services（业务流程）→ logic / stats（纯函数）→ repositories（数据库读写）
  logic/        operators.py 运算符表、question_rules.py 题目设置检查、survey_check.py 跳转规则检查、
                validation.py 答案校验、jump.py 路径计算、survey_state.py 问卷状态规则；
                第二阶段：question_versions.py 版本内容规则、question_access.py 访问权限
  stats/        pipelines.py 统计聚合管道；第二阶段：cross_pipelines.py 跨问卷统计管道
  services/     第二阶段：question_library.py 题目与版本、banks.py 题库、usage.py 使用情况、cross_stats.py 跨问卷统计；
                questions.py 中新增“从已有题目添加 / 换版本 / 存入我的题目”
  db_schema.py  五个集合的 $jsonSchema 校验规则与索引
static/         前端页面：登录、我的问卷、编辑、填写、统计；第二阶段：我的题目、题目详情、题库、跨问卷统计
scripts/        init_db.py 初始化数据库；seed_demo.py 第一阶段示例问卷；seed_phase2.py 第二阶段示例数据；
                verify_phase1_compat.py 兼容性验证；sport_survey_e2e.py 端到端测试；start_mongo.bat
tests/          pytest 测试；tests/ui/ 界面测试；tests/js/ 前端纯函数测试
docs/           设计文档、API 说明、部署、测试用例、兼容性验证、AI 使用日志（第一、二阶段）
```

关键逻辑（校验、跳转、统计管道）都是不访问数据库的纯函数，便于单独测试和第二阶段修改。

---

## 六、数据库设计

> 完整设计（字段表、取值、业务规则、设计理由、统计管道、为什么适合 MongoDB、第二阶段扩展点、修订记录）见 **[docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md)**。

| 集合 | 作用 | 一条文档代表 | 主要字段 |
|---|---|---|---|
| `users` | 用户账号（创建者和填写者是同一种用户） | 一个用户 | `username`、`passwordHash`、`createdAt` |
| `surveys` | 问卷，**题目、选项、校验规则、跳转规则都嵌入其中** | 一份问卷 | `ownerId`、`shortCode`、`status`、`settings`、`questions[]` |
| `responses` | 填写结果 | 一次提交 | `surveyId`、`respondentId`、`isLatest`、`answers[{questionId, value}]` |
| `questions`（第二阶段） | 保存的题目，**每个版本一个文档** | 一道题的一个版本 | `rootId`（属于哪道题）、`parentId`（从哪个版本改来）、`restoredFrom`、`version`、`ownerId`、`type`、`title`、`options`、`validation`（不含必答）、`sharing`、`lockedAt` |
| `questionBanks`（第二阶段） | 题库 | 一个题库 | `ownerId`、`name`、`description`、`items[{questionId, rootId, addedAt}]`、`sharing` |

**题目为什么嵌入问卷**：题目总是和问卷一起读取，一次查询拿到整份问卷；题目数量有限（上限 100 道），远小于 16MB；只有创建者编辑，整份问卷一次写入，跳转规则的合法性在同一文档内即可检查；数组顺序就是题目顺序。题目和选项使用**稳定 id**（`q_` / `o_` + 6 位），跳转规则和答卷引用 id 而不是“第几题”，调整顺序、改选项文字都不会使规则和旧答卷出错。

**答卷为什么单独成集合**：答卷数量没有上限，嵌入会让问卷文档无限增长；多人同时提交不会争抢同一文档；统计需要对大量答卷做聚合。`answers` 用 `{questionId, value}` 数组，所有题型的统计管道可以共用前三步，一个 `answers.questionId` 索引覆盖所有题。

**索引**：`users.username` 唯一；`surveys.shortCode` 唯一；`surveys {ownerId, createdAt}`；`responses {surveyId, submittedAt}`；`responses {surveyId, respondentId}` **唯一、部分索引 `isLatest: true`**（每人每份问卷最多一份“最新”答卷，也是并发提交的最终保证）；`responses.answers.questionId`。三个集合都有 `$jsonSchema` 校验（`validationLevel: moderate`、不禁止额外字段，为第二阶段留余地），见 `app/db_schema.py`。

**第二阶段：问卷里存题目的副本，用 `source` 记录来源**。问卷题目新增可选字段 `source: {questionId, rootId, version}`。问卷使用已保存的题时，把这个版本的内容**复制**进问卷，而不是只存一个引用：

- 填写、校验、跳转、单份问卷统计都只读问卷文档，第一阶段的这些代码完全不用改，一次查询拿到整份问卷的做法也不变；
- 修改题目永远不会改动已有问卷（需求三），不需要到处检查“这个题是否被用过”；
- 第一阶段设计中已为此预留（题目嵌入问卷时说明过“将来可新增题库集合，复制嵌入，原结构不变”）；
- `source` 保留了与原题的联系，用于“被哪些问卷使用”和跨问卷统计；版本被问卷用过就锁定，保证副本与来源版本内容一致；
- **旧数据不迁移**：没有 `source` 的题就是问卷里直接建的题，一切照旧。

第二阶段的新结构为什么适合 MongoDB、为什么不用关系表（含与关系表的逐项对比），见[设计文档 10.12](docs/DATABASE_DESIGN.md)。

**为什么每个版本一个文档**：版本要能单独被问卷引用、单独共享、单独锁定，并且同一道题的不同版本可以属于不同的人（别人基于共享的题创建的版本属于别人）。版本之间用 `rootId`（同一道题）和 `parentId`（从哪个版本改来）连成一棵树；选项 id 跨版本保持不变，跨问卷统计因此可以直接按选项 id 合并。

**第二阶段的索引**：`questions {rootId, version}` 唯一（版本号不重复、取最大版本号）、`{ownerId, updatedAt}`、`sharing.userIds`、`sharing.public`（部分索引）、`parentId`、`restoredFrom`；`questionBanks {ownerId, updatedAt}`、`sharing.userIds`、`sharing.public`、`items.questionId`；`surveys` 新增 `questions.source.questionId`、`{questions.source.rootId, ownerId}`（被哪些问卷使用、跨问卷统计）。

**关键业务规则**：

- **匿名**：填写前必须登录，始终记录 `respondentId`（用于防止重复填写），匿名问卷的统计和答卷列表不返回填写人；
- **提交策略**：`once` 每人一次；`latest` 可重填、以最后一次为准；`all` 每次都算。所有提交都保留，用 `isLatest` 区分；
- **问卷状态**：草稿 → 已发布 → 已关闭；超过截止时间视同关闭，延长后恢复；发布后题目、匿名设置、提交策略锁定。

---

## 七、API 说明

> 每个接口的参数、请求与返回示例、错误码见 **[docs/API.md](docs/API.md)**。运行服务后也可以在 http://127.0.0.1:8000/docs 交互调试。

除注册、登录、`/api/meta`、`/api/health` 外都需要请求头 `Authorization: Bearer <accessToken>`。请求和响应均为 JSON；错误统一为 `{code, message, errors?}`，例如 `{"code": "VALIDATION_ERROR", "message": "提交内容不合法", "errors": [{"field": "username", "message": "用户名只能包含字母、数字和下划线"}]}`。访问别人的问卷与访问不存在的问卷一样返回 404。

| 模块 | 方法 | 路径 | 用途 |
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
| 填写 | GET | `/api/s/{shortCode}` | 填写者获取问卷（不含跳转规则） |
| | POST | `/api/s/{shortCode}/path` | 路径预览（下一题与错误，不保存） |
| | POST | `/api/s/{shortCode}/responses` | 提交答卷 |
| 统计 | GET | `/api/surveys/{id}/stats` | 整份问卷统计 |
| | GET | `/api/surveys/{id}/stats/questions/{qid}` | 单题统计（填空题内容可分页） |
| | GET | `/api/surveys/{id}/responses` | 答卷列表 |
| 其他 | GET | `/api/meta` | 题型、运算符表、长度上限（前端使用） |
| | GET | `/api/health` | 健康检查 |

**第二阶段新增 24 个接口**（第一阶段的接口参数和返回格式都没有变；问卷题目多了可选字段 `source`）：

| 模块 | 方法 | 路径 | 用途 |
|---|---|---|---|
| 问卷中的题目 | POST | `/api/surveys/{id}/questions/from-library` | 从已有题目添加（复制并记录来源，版本加锁） |
| | PUT | `/api/surveys/{id}/questions/{qid}/version` | 换成同一道题的其他版本 |
| | POST | `/api/surveys/{id}/questions/{qid}/save-to-library` | 存入我的题目 |
| 我的题目 | POST / GET | `/api/questions` | 新建题目（v1）/ 版本列表（`scope=mine\|shared\|public\|all`） |
| | GET | `/api/questions/groups` | 按题目分组的列表 |
| | GET / PUT / DELETE | `/api/questions/{id}` | 版本详情（含能否删除）/ 直接修改未锁定的版本 / 删除 |
| | POST | `/api/questions/{id}/versions` | 创建新版本 |
| | POST | `/api/questions/{id}/restore` | 恢复旧版本 |
| | GET | `/api/questions/{id}/history` | 版本历史 |
| | PUT | `/api/questions/{id}/sharing` | 共享设置 |
| | GET | `/api/questions/{id}/usage` | 被哪些问卷使用 |
| | GET | `/api/questions/{id}/stats` | 单题跨问卷统计（`versionId`、`surveyId` 筛选） |
| 题库 | POST / GET | `/api/banks` | 新建 / 列表 |
| | GET / PATCH / DELETE | `/api/banks/{id}` | 详情 / 修改名称说明 / 删除 |
| | PUT | `/api/banks/{id}/sharing` | 共享设置 |
| | POST | `/api/banks/{id}/items` | 加入题目 |
| | PUT / DELETE | `/api/banks/{id}/items/{rootId}` | 换版本 / 移除 |

看不到的题目、题库与不存在一样返回 404；看得到但不是所有者却要修改返回 403。

---

## 八、关键逻辑说明

### 1. 校验

校验写成不访问数据库的纯函数，分两个时机：

- **保存题目时**（`app/logic/question_rules.py`）：各题型只允许自己的设置字段；`min ≤ max`、`minLength ≤ maxLength`、`minSelect ≤ maxSelect ≤ 选项数`；类型严格（布尔值不当数字、`"3"` 不当 3）。
- **提交答案时**（`app/logic/validation.py`）：必答；单选必须是本题选项；多选不重复、数量限制；文本按 Unicode 字符计字数；数字必须是 JSON 数字、在范围内、整数题必须为整数且在 64 位范围内。选填题未作答不校验，一旦作答就必须合法。保存前规范化：文本去首尾空白、多选按选项顺序、整数题 `3.0` 存为 `3`。

### 2. 跳转

每道题的 `logic` 中有若干条规则 `{when: {op, value}, goto}` 和一个 `defaultNext`，存在问卷数据中，程序只负责解释。

| 题型 | 运算符 |
|---|---|
| 单选 | `eq`（选择了）、`in`（选择了其中之一） |
| 多选 | `contains`、`containsAny`、`containsAll`、`equals` |
| 数字 | `eq` `ne` `gt` `gte` `lt` `lte`、`between`（含两端） |

- **约定**：规则按顺序检查，**第一条成立的生效**；**只能往后跳**或跳到 `END`；都不成立时走 `defaultNext`（为空则顺序进入下一题）；选填题未作答不匹配任何规则；被跳过的题不显示、不校验、不保存。
- **保存时检查**（`app/logic/survey_check.py`）：运算符与题型匹配、值合法、只能引用本题选项、目标在本题之后；每次修改和调整顺序后都检查整份问卷。规则重叠、永远不会成立的规则、永远不会显示的题给出警告。
- **路径计算**（`app/logic/jump.py`）：从第 1 题开始，校验当前题 → 按规则找下一题，遇到第一个错误即停。填写时的逐题预览和提交用同一个函数；**提交时后端从第一题重新计算**，只保存路径上作答的题，路径外的答案丢弃。

### 3. 统计

用 MongoDB 聚合管道实时计算（`app/stats/pipelines.py`），各题型共用前三步：

```js
{ $match: { surveyId: S, ...口径, "answers.questionId": Q } },  // 使用索引
{ $unwind: "$answers" },
{ $match: { "answers.questionId": Q } }
```

之后单选按值分组计数，多选再 `$unwind` 一次后计数，数字用 `$avg`，填空列出内容（分页）。**口径**：`latest` 只算 `isLatest: true`，`once`、`all` 算全部答卷，问卷列表、统计、答卷列表三处数字一致。**匿名**：实名问卷用 `$lookup` 只取用户名；匿名问卷的管道不含 `$lookup`、不输出 `respondentId`。各题型完整管道见[设计文档 6.8](docs/DATABASE_DESIGN.md)。

### 4. 版本与锁定（第二阶段）

- **新建** v1；**创建新版本**：`parentId` = 被修改的版本，版本号 = 这道题现有最大版本号 + 1（唯一索引防止并发重号，冲突时重新取号）；**题型不能改**；**选项 id 保持不变**，新增选项的 id 在这道题所有版本中都不重复。规则是纯函数（`app/logic/question_versions.py`），内容检查复用第一阶段的题目设置检查。
- **锁定**：版本被加进任何问卷（包括草稿、别人的问卷）就永久锁定，只能创建新版本。加进问卷时**先加锁再复制**，直接修改的条件更新带 `lockedAt: null`，两者同时发生时问卷里的副本仍与版本内容一致。
- **恢复**：把旧版本复制成新版本（`restoredFrom`），接在自己最新的版本后面；旧版本不变。
- **问卷中来自已保存题目的题**只能改是否必答和跳转规则；可以在草稿中“换版本”（保留题目 id、必答、跳转规则；规则用到的选项在新版本中不存在时拒绝）。

### 5. 共享与权限（第二阶段）

可访问 = 自己的、公开的、共享给自己的，或在一个自己可访问的题库中且题库创建者现在仍能访问（`app/logic/question_access.py`、`app/services/question_library.py` 的 `bank_granted`）。共享以整道题为单位（一次更新自己在这道题下的所有版本），新版本继承；别人改出的版本属于别人、默认不共享。只有所有者能修改版本和共享设置，只有创建者能修改题库。删除不能影响已有问卷和别人的题库：被用过、有子版本、在任何题库中的版本不能删。

### 6. 单题跨问卷统计（第二阶段）

找出自己的、已发布或已关闭的、使用这道题（`questions.source.rootId`）的问卷，每份问卷中这道题的 id 不同、提交策略也可能不同，用一个管道同时统计（`app/stats/cross_pipelines.py`）：

```js
{ $match: { $or: [ { surveyId: S1, ...口径1, "answers.questionId": Q1 }, { surveyId: S2, ...口径2, "answers.questionId": Q2 } ] } },
{ $unwind: "$answers" },
{ $match: { $or: [ { surveyId: S1, "answers.questionId": Q1 }, { surveyId: S2, "answers.questionId": Q2 } ] } },
{ $facet: { perSurvey: [...], overall: [...作答人数按 respondentId 跨问卷去重...], byOption: [...], items: [...], average: [...] } }
```

选项按 id 合并（各版本沿用选项 id），文字取参与统计的版本中含有该选项的最新版本；在参与统计的最新版本中已被删除的选项照常计数，并标注“仅出现在旧版本中”。不显示填写人（管道中没有 `$lookup`，不输出 `respondentId`）。每份问卷各自的数字与第一阶段的单题统计一致。

---

## 九、测试

```bash
pytest                                                      # 全部测试（含界面测试）
pytest -m "not ui"                                          # 只跑后端测试（不需要 Node.js 和 Chrome）
pytest --cov=app --cov=scripts --cov-report=term-missing    # 代码覆盖率
```

在项目根目录、激活虚拟环境并启动 MongoDB 后运行。测试使用独立数据库（`survey_test`、`survey_ui_test`），不影响开发数据。

**运行结果**（第二阶段，2026-10-29）：**862 个测试全部通过**（第一阶段 660 个原样保留并继续通过，第二阶段新增 202 个，含 4 个界面测试）。覆盖率：`app/` 99%（不计两个手动执行的脚本时，`app/` 与 `scripts/` 合计也是 99%）。

**兼容性验证**（`python -m scripts.verify_phase1_compat`）：用 `phase1` 标签的代码生成第一阶段的数据，再切换到当前代码，检查旧数据不被改动、各页面返回与第一阶段完全相同、注册登录 / 建问卷 / 填写 / 跳转 / 校验 / 统计正常、旧问卷的题能存入我的题目——**27 项全部通过**，见 [docs/COMPAT_VERIFICATION.md](docs/COMPAT_VERIFICATION.md)。

第一阶段（2026-10-22）：660 个测试全部通过，另有一项基于开发者手工创建的问卷的端到端测试（15 位模拟填写人、6 份不合法答卷、43 项统计核对，全部一致）。

**代表性用例**（第一阶段 99 条、第二阶段 86 条用例，以及端到端测试、界面测试和手工测试见 **[docs/TEST_CASES.md](docs/TEST_CASES.md)**）。“水果问卷”是设计文档 3.4 的示例问卷：第 1 题选“不喜欢”跳到第 5 题，第 4 题填 0 结束。

| 测试点 | 测试步骤 | 输入 | 期望输出 | 实际结果 |
|---|---|---|---|---|
| 年龄 0–120 整数（需求原文） | 校验“0–120 的整数”数字题的答案 | 121；119.5；`3.0` | “不能大于 120”；“必须为整数”；保存为 `3` | “不能大于 120”；“必须为整数”；`3.0` 保存为整数 `3`，通过 |
| 多条规则命中顺序 | 多选题设两条规则后计算答题路径 | 规则 ① `containsAll [A, B]` → 第 4 题，② `contains A` → 第 3 题；答案选 A、B | 按第一条跳到第 4 题 | 路径为 [第 1 题, 第 4 题]，通过 |
| 往前跳被拒绝 | 保存跳转规则时整体检查 | 第 2 题的规则跳到第 1 题 | 拒绝，“只能跳转到后面的题目或 END（目标是第 1 题）” | 错误字段 `logic.rules[0].goto`，信息为“第 2 题第 1 条规则：只能跳转到后面的题目或 END（目标是第 1 题）”，通过 |
| 被跳过的必答题、多余答案 | 登录后向已发布的水果问卷提交答案 | 第 1 题选“不喜欢”，同时提交第 2~4 题的答案（含不合法值）和一个不存在的题目 id | 201，只保存第 1、5 题 | 201，返回和数据库中保存的题目都是 [第 1 题, 第 5 题]，通过 |
| 三种提交策略 | 同一人向 once / latest / all 问卷各提交多次 | 完整合法的答案 | once：第二次 409；latest：只有最后一份 isLatest；all：三份都计入 | once：第二次 409 `ALREADY_SUBMITTED`，库中 1 份；latest：3 份的 isLatest 为 [false, false, true]；all：3 份都保存，统计时都计入，通过 |
| 截止/关闭后提交 | 问卷关闭或截止时间已过后提交 | 完整合法的答案 | 409 `SURVEY_CLOSED` / `SURVEY_EXPIRED`，不保存 | 409，`SURVEY_CLOSED`“问卷已关闭，不再接受填写”或 `SURVEY_EXPIRED`“问卷已截止，不再接受填写”，库中没有答卷，通过 |
| 统计与匿名 | 4 人按不同路径填写水果问卷后，创建者查看统计和答卷列表 | 4 份答卷（实名 / 匿名各一份问卷） | 喜欢 3、不喜欢 1；数字平均 10/3；匿名问卷返回内容中没有任何用户名和用户 id | 喜欢 3、不喜欢 1；第 4 题内容 [0, 3, 7]，平均值 10/3；匿名问卷 3 个接口的返回中找不到任何用户名、用户 id 和 username/respondentId 字段，通过 |

**第二阶段代表性用例**：

| 测试点 | 测试步骤 | 输入 | 期望输出 | 实际结果 |
|---|---|---|---|---|
| 版本与恢复 | 年龄 v1 → v2（改题目）→ v3（改最大值）；另一道题 v1 → v2（改坏了）后恢复 v1 | v2：题目改为“你的年龄（周岁）”；v3：最大值改为 120；另一道题 v2 题目为“改坏了”，恢复 v1 时不指定父版本 | 版本号、父版本正确；恢复生成新版本 | 历史为 [(1, 无), (2, v1), (3, v2)]，v1 内容不变；恢复得到 v3，`restoredFrom` v1、`parentId` v2，内容同 v1 |
| 修改不影响已有问卷 | 问卷发布后直接修改所用版本，再创建新版本 | 改题目 | 直接修改被拒；问卷不变 | 409 `QUESTION_LOCKED`；新版本创建成功；问卷题目仍为原文 |
| 只能改必答和跳转 | 修改问卷中来自已保存题目的题 | 改必答、设跳转；改题目、选项文字等 | 前者成功；后者拒绝 | 前者 200 且 `source` 保留；改内容的 5 种都是 422 |
| 共享与题库 | alice 把未单独共享的题放进题库并共享给 bob | 未单独共享的年龄 v1 | bob 能用、能派生、不能改 | bob 选进问卷 201、派生 201、修改 403 |
| 只在旧版本中的选项 | v1 有“保密”，v2 改为“不想说”，v3 删除；三份问卷各自填写后跨问卷统计 | 性别 v1（男、女、保密）→ v2（“保密”改为“不想说”）→ v3（删除该选项）；v1 的问卷 bob 选保密、carol 选男，v2 的问卷 bob 选不想说，v3 的问卷 bob 选女 | 照常计数，标注只在旧版本中 | [男 1, 女 1, 不想说 2（仅旧版本）]，答卷 4 = 各选项之和 |
| 跨问卷统计口径 | S1（once，v1）2 份；S2（all，v2）3 份，bob 在两份问卷都填了 | S1（v1：男、女，once）：bob 男、carol 女；S2（v2：“女”改为“女性”、新增“其他”，all）：bob 女性两次、carol 其他 | 答卷数相加，作答人数跨问卷去重；每份问卷与单题统计一致 | 问卷 2、答卷 5、作答人数 2；两份问卷的数字与第一阶段单题统计完全相同 |

---

## 十、示例数据

### 第一阶段示例问卷

`scripts/seed_demo.py` 生成一份已发布的示例问卷 **“大学生饮食习惯调查”**（12 道题，覆盖四种题型、单选/多选/数字三类跳转和各种校验）和 12 位填写人的 13 份答卷。

| 项目 | 内容 |
|---|---|
| **访问链接** | 本地 **http://127.0.0.1:8000/survey/Food26**；部署后 `<PUBLIC_BASE_URL>/survey/Food26` |
| 填写人账号 | `demo_s01` ~ `demo_s12`，密码均为 `demo123456`；也可以自己注册新账号填写 |
| 创建者账号 | `demo_owner`，本地密码 `demo123456`（线上用 `--owner-password` 另设）；登录后在“我的问卷”中点“统计结果” |
| 设置 | 已发布、实名、`latest`（可以重填，以最后一次为准）、不限截止时间 |

```bash
python -m scripts.seed_demo                        # 已存在时不重复生成，直接输出链接和账号
python -m scripts.seed_demo --reset                # 只删除示例问卷及其答卷后重新生成（链接仍为 Food26）
python -m scripts.seed_demo --owner-password XXX   # 指定创建者密码（部署到服务器时使用）
```

先启动 MongoDB 即可运行，不需要先启动服务。链接代码固定为 `Food26`；若已被另一份问卷占用，脚本报错停止，不会覆盖。**建议试的路径**：第 1 题选“否”直接结束；第 4 题选“基本不吃”跳到第 6 题；第 7 题不选“外卖”直接到第 10 题；年龄填 150 或 18.5 会提示错误；提交后再次打开会预填上次的答案。

### 第二阶段示例数据

`python -m scripts.seed_phase2`（`--reset` 重新生成）生成《数据库原理》连续三个学期的课程评价，演示第二阶段的全部功能：

| 内容 | 说明 |
|---|---|
| 账号 | 老师 **`demo_teacher`**（主要演示账号）、同事 `demo_colleague`，密码均为 `demo123456`；填写人沿用 `demo_s01` ~ `demo_s12` |
| 题目版本 | “总体满意度”v1 → v2（删掉“很不满意”，“一般”改为“说不上好坏”）→ v3（试改）→ v4（恢复 v2 的内容）；同事基于它创建了自己的 v5 |
| 问卷 | 2025 秋（`Db25Fa`，只能填一次，用 v1）、2026 春（`Db26Sp`，以最后一次为准，用 v2）、2026 秋（`Db26Fa`，每次都算，用 v4，选“不满意”跳到建议），各 6 份答卷；同事的助教课评价（`DbTa26`） |
| 共享与题库 | “总体满意度”共享给同事，“对课程的建议”公开（它是 2025 秋问卷中直接建的、发布后存入我的题目）；题库“课程评价常用题”共享给同事，显示“有新版本可换”和一项不可用的条目 |

**建议查看**（用 `demo_teacher` 登录）：我的题目 →“你对这门课的总体满意度”→ 版本历史、被哪些问卷使用、**跨问卷统计**（3 份问卷、17 份答卷、作答人数 12；“很不满意”标注“仅出现在旧版本中”；可按问卷、按版本筛选）；“每周课后学习时间”的跨问卷统计（平均 3.75）；题库“课程评价常用题”。再用 `demo_colleague` 登录查看“共享给我的”和共享的题库。

---

## 十一、文档索引

| 文档 | 内容 |
|---|---|
| [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md) | 数据库设计：集合、字段、索引、业务规则、设计理由、统计聚合管道、为第二阶段预留的扩展点；**第十节为第二阶段设计**；修订记录 |
| [docs/API.md](docs/API.md) | API 说明：每个接口的参数、请求与返回示例、错误码 |
| [docs/DEPLOY.md](docs/DEPLOY.md) | MongoDB 安装配置（Windows / Mac）、部署到 Linux 服务器（阿里云） |
| [docs/TEST_CASES.md](docs/TEST_CASES.md) | 测试用例（步骤、输入、期望输出、实际结果）、运行记录、端到端测试、界面测试截图、手工测试（第一阶段、第二阶段） |
| [docs/COMPAT_VERIFICATION.md](docs/COMPAT_VERIFICATION.md) | 第一阶段 → 第二阶段兼容性验证的步骤与结果（27 项） |
| [docs/sport_survey_e2e_result.md](docs/sport_survey_e2e_result.md) | 端到端测试（开发者手工创建的问卷）的完整核对结果 |
| [docs/AI_LOG.md](docs/AI_LOG.md) | 第一阶段 AI 使用日志：每一步的提示词、AI 产出、是否修改、AI 的错误与开发者的决定 |
| [docs/AI_LOG_PHASE2.md](docs/AI_LOG_PHASE2.md) | 第二阶段 AI 使用日志 |
| [docs/KICKOFF_PROMPT.md](docs/KICKOFF_PROMPT.md) | 开工时给 AI 的提示词 |
| [CLAUDE.md](CLAUDE.md) | 给 AI（Claude Code）的项目约束与工作方式 |
