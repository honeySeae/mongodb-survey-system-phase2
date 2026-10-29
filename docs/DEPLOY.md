# MongoDB 安装与部署

> README 的“快速开始”只保留每次开发要用的命令；本文件是 MongoDB 的首次安装配置（Windows / Mac）和部署到 Linux 服务器（阿里云）的完整步骤。

## 一、本地安装 MongoDB

### Windows（默认方式，开发时使用）

首次准备（只需一次）：

1. 从 [MongoDB 官网](https://www.mongodb.com/try/download/community) 安装 MongoDB Community Server 和 mongosh（安装时不必勾选 “Install MongoD as a Service”）。
2. 创建数据目录和日志目录：

   ```powershell
   mkdir C:\data\db, C:\data\log
   ```

3. 创建配置文件 `C:\data\mongod.cfg`（只监听本机）：

   ```yaml
   storage:
     dbPath: C:\data\db
   systemLog:
     destination: file
     path: C:\data\log\mongod.log
     logAppend: true
   net:
     port: 27017
     bindIp: 127.0.0.1
   ```

**每次开发或运行测试前，双击 [`scripts/start_mongo.bat`](../scripts/start_mongo.bat)，并保持它的窗口开着。**

- 窗口里不会滚动输出，日志写在 `C:\data\log\mongod.log`，这是正常的；按 `Ctrl+C` 停止。
- 若窗口提示 “MongoDB has stopped”，最常见的原因是已经有一个 MongoDB 在运行。
- 配置文件不在默认位置时：`scripts\start_mongo.bat D:\path\to\mongod.cfg`。
- 不用脚本时也可以直接运行：`mongod --config C:\data\mongod.cfg`。
- 验证：`mongosh --eval "db.runCommand({ping:1})"` 输出 `{ ok: 1 }`。

<details>
<summary>可选：在 Windows 上注册为系统服务（开机自动启动）</summary>

注册后就不要再运行 `start_mongo.bat`（二者使用同一端口和数据目录）。**以管理员身份**打开 PowerShell（开始菜单搜索 PowerShell → 右键 → 以管理员身份运行），执行（路径中的 `8.3` 换成实际安装的版本）：

```powershell
& "C:\Program Files\MongoDB\Server\8.3\bin\mongod.exe" --config "C:\data\mongod.cfg" --install
net start MongoDB
```

| 操作 | 命令（管理员 PowerShell） |
|---|---|
| 启动 / 停止 | `net start MongoDB` / `net stop MongoDB` |
| 查看状态 | `sc.exe query MongoDB` |
| 卸载服务（不删除数据） | `net stop MongoDB` 后 `sc.exe delete MongoDB` |

</details>

### Mac（Homebrew）

```bash
brew tap mongodb/brew
brew install mongodb-community mongosh
brew services start mongodb-community   # 后台服务；或手动：mongod --dbpath ~/data/db（先 mkdir -p ~/data/db）
```

## 二、部署到 Linux 服务器（阿里云）

以 **Ubuntu 24.04**（自带 Python 3.12）为例。以下命令在服务器上执行。

**1. 安装 MongoDB 并确认只监听本机**

```bash
sudo apt-get install -y gnupg curl
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" \
  | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
sudo apt-get update && sudo apt-get install -y mongodb-org
sudo systemctl enable --now mongod
grep -A2 "^net:" /etc/mongod.conf      # 应为 bindIp: 127.0.0.1（默认值，不要改成 0.0.0.0）
```

> **安全要求：MongoDB 只监听本机（`bindIp: 127.0.0.1`），不要在阿里云安全组中开放 27017 端口。** 应用和数据库在同一台服务器上，通过 `127.0.0.1` 访问即可；对外开放数据库端口会让任何人都能尝试连接。

**2. 获取代码、安装依赖**

```bash
sudo apt-get install -y python3-venv git
git clone https://github.com/honeySeae/mongodb-survey-system-phase2.git /opt/survey && cd /opt/survey
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

**3. 配置 `.env`（必须重新生成 `JWT_SECRET`）**

```bash
cp .env.example .env
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"   # 复制输出作为 JWT_SECRET
nano .env
```

```ini
MONGO_URI=mongodb://127.0.0.1:27017
MONGO_DB_NAME=survey
JWT_SECRET=<上面生成的随机字符串>
JWT_EXPIRE_MINUTES=1440
PUBLIC_BASE_URL=http://<服务器公网 IP 或域名>:8000
```

> **安全要求：部署时必须重新生成 `JWT_SECRET`**，不要沿用本地开发的密钥。知道密钥的人可以伪造任何用户的登录令牌。程序会拒绝 `.env.example` 中的示例值和少于 32 个字符的密钥（启动失败并提示生成命令；报错信息不回显密钥）。

**4. 用 systemd 运行服务**

创建 `/etc/systemd/system/survey.service`：

```ini
[Unit]
Description=Online survey system
After=network.target mongod.service

[Service]
WorkingDirectory=/opt/survey
ExecStart=/opt/survey/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /opt/survey
sudo systemctl daemon-reload && sudo systemctl enable --now survey
curl http://127.0.0.1:8000/api/health       # {"status":"ok","database":"ok"}
```

**5. 安全组**：在阿里云控制台的安全组中**只开放 8000 端口**（入方向 TCP 8000），**不开放 27017**。

**6. 生成示例问卷（更换创建者密码）**

```bash
cd /opt/survey && sudo -u www-data .venv/bin/python -m scripts.seed_demo --owner-password '<只有你知道的密码>'
```

输出中的链接即为线上示例问卷地址。报告中只写填写人账号，不写创建者密码。

**更新代码**：`git pull && .venv/bin/pip install -r requirements.txt && sudo systemctl restart survey`。
