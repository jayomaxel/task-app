# TimeManager Task App

一个面向中文用户的 AI 时间管理 Web 应用，提供任务管理、优先级分析、任务拆解、日程规划和时间轴视图。

当前仓库里的主应用是 `task-app`。页面由 Flask 提供，前端是单页应用，支持 PWA 安装；仓库中还保留了一份历史原型 `taskflow-ai-src/` 作为参考，但不是当前主界面。

## 第一部分：项目现状与技术栈

### 1.1 当前架构概览

项目是一个 Flask + 原生前端的时间管理应用，支持本地存储和远程数据库两种模式。

| 层级 | 技术 | 说明 |
| --- | --- | --- |
| 后端 | Flask (Python) | `app.py` 约 600 行，包含主要 API 路由和数据库操作 |
| AI 服务 | OpenAI SDK | `ai_service.py` 约 670 行，支持 SiliconFlow / OpenAI / Claude / GitHub Models |
| 前端 | 原生 HTML / CSS / JS | `static/index.html` 为单文件 SPA，`static/local-api.js` 提供本地存储模拟 |
| 数据库 | PostgreSQL | 单表 `tasks`，支持 `parent_id` 父子关系 |
| 部署 | Docker + Gunicorn | `Dockerfile` 已就绪，可直接构建部署 |

### 1.2 当前数据库 `tasks` 表结构

当前只有一张 `tasks` 表，字段如下：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `SERIAL PRIMARY KEY` | 自增主键 |
| `title` | `TEXT NOT NULL` | 任务标题 |
| `description` | `TEXT NOT NULL DEFAULT ''` | 任务描述 |
| `priority` | `INTEGER` | 优先级，范围 1-5，5 最高 |
| `status` | `TEXT` | `todo` / `doing` / `done` |
| `parent_id` | `INTEGER` | 父任务 ID，外键关联 `tasks(id)`，级联删除 |
| `due_date` | `TIMESTAMPTZ` | 截止时间 |
| `estimated_minutes` | `INTEGER` | 预估耗时，单位分钟 |
| `scheduled_start` | `TIMESTAMPTZ` | 排程开始时间 |
| `scheduled_end` | `TIMESTAMPTZ` | 排程结束时间 |
| `created_at` | `TIMESTAMPTZ` | 创建时间 |
| `updated_at` | `TIMESTAMPTZ` | 更新时间 |

### 1.3 当前 AI 能力

- `POST /api/ai/decompose`：将大任务拆解为 3-6 个子任务
- `POST /api/ai/prioritize`：AI 分析优先级并回写
- `POST /api/ai/schedule`：根据空闲时段安排任务

AI 调用统一封装在 `ai_service.py` 中，使用 OpenAI Python SDK 兼容接口，支持多 provider 切换。当前实现中，快速模型主要用于任务拆解，智能模型主要用于优先级分析和日程规划。

### 1.4 当前前端视图

- Today 视图：今日任务
- All 视图：全部任务列表
- Timeline 视图：时间轴
- AI Assistant 视图：AI 交互面板

## 第二部分：运行模式与启动

项目当前有两套数据工作方式：

### 1. 默认模式：本地存储模式

- 前端默认把 `APP_STORAGE_MODE` 设为 `"local"`
- 任务数据保存在浏览器 `localStorage`
- 不依赖 PostgreSQL
- AI 相关按钮会走前端内置的本地逻辑，用于演示和快速体验

适合场景：

- 本地预览 UI
- 快速演示产品流程
- 无数据库环境下直接体验

### 2. 后端模式：数据库 + AI Provider

后端已经实现了 PostgreSQL 存储和真实 AI 接口：

- `GET /api/tasks`
- `POST /api/tasks`
- `PUT /api/tasks/:id`
- `DELETE /api/tasks/:id`
- `GET /api/timeline`
- `POST /api/ai/decompose`
- `POST /api/ai/prioritize`
- `POST /api/ai/schedule`

如果你要启用这一模式，需要：

1. 配置 `DATABASE_URL`
2. 配置一个 AI Provider 的 Key
3. 将前端中的 `APP_STORAGE_MODE` 从 `"local"` 改成 `"remote"`

## 本地启动

### 方式一：直接体验默认本地模式

这也是最简单的启动方式，不需要数据库，也不需要 AI Key。

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

启动后访问：

```text
http://127.0.0.1:5000
```

说明：

- 页面由 Flask 提供
- 任务数据默认保存在浏览器本地
- 清理浏览器站点数据后，本地任务会一起被清掉

### 方式二：启用数据库和真实 AI 能力

先安装依赖，再配置环境变量：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

然后准备环境变量，推荐放进 `.env`：

```env
APP_ENV=development
PORT=5000
DATABASE_URL=postgresql://username:password@localhost:5432/timemanager

AI_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
OAI_MODEL_FAST=gpt-4o-mini
OAI_MODEL_SMART=gpt-4o
```

最后启动：

```bash
python app.py
```

注意：

- 后端会在第一次访问数据库时自动创建 `tasks` 表和相关索引
- 当前前端默认仍会优先走本地存储模式
- 如果你要让页面真正调用后端 API，需要把 `static/index.html` 里的 `APP_STORAGE_MODE` 改成 `"remote"`

## Docker 运行

构建镜像：

```bash
docker build -t task-app .
```

运行容器：

```bash
docker run --rm -p 5000:5000 --env-file .env task-app
```

默认容器启动命令：

```bash
gunicorn -w 2 -b 0.0.0.0:5000 --timeout 120 app:app
```

## 环境变量说明

### 通用

| 变量名 | 说明 |
| --- | --- |
| `APP_ENV` | 运行环境，`development` 时会启用 Flask debug |
| `PORT` | 服务端口，默认 `5000` |
| `DATABASE_URL` | PostgreSQL 连接串 |
| `AI_PROVIDER` | AI 提供商，可选 `siliconflow` / `openai` / `claude` / `github` |

### SiliconFlow

| 变量名 | 说明 |
| --- | --- |
| `SILICONFLOW_API_KEY` | SiliconFlow API Key |
| `SILICONFLOW_BASE_URL` | 默认 `https://api.siliconflow.cn/v1` |
| `SF_MODEL_FAST` | 快速模型，默认 `Qwen/Qwen3-8B` |
| `SF_MODEL_SMART` | 智能模型，默认 `deepseek-ai/DeepSeek-V3` |

### OpenAI

| 变量名 | 说明 |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI API Key |
| `OPENAI_BASE_URL` | 默认 `https://api.openai.com/v1` |
| `OAI_MODEL_FAST` | 快速模型，默认 `gpt-4o-mini` |
| `OAI_MODEL_SMART` | 智能模型，默认 `gpt-4o` |

### Claude

| 变量名 | 说明 |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude API Key |
| `CLAUDE_BASE_URL` | 默认 `https://api.anthropic.com/v1` |
| `CLAUDE_MODEL_FAST` | 快速模型 |
| `CLAUDE_MODEL_SMART` | 智能模型 |

### GitHub Models

| 变量名 | 说明 |
| --- | --- |
| `GITHUB_TOKEN` | GitHub Models Token |
| `GITHUB_BASE_URL` | 默认 `https://models.github.ai/inference` |
| `GITHUB_MODEL_FAST` | 快速模型 |
| `GITHUB_MODEL_SMART` | 智能模型 |

## API 概览

### 任务接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/tasks` | 获取任务列表，支持排序与筛选 |
| `POST` | `/api/tasks` | 创建任务 |
| `PUT` | `/api/tasks/<id>` | 更新任务 |
| `DELETE` | `/api/tasks/<id>` | 删除任务 |
| `GET` | `/api/timeline` | 获取时间轴数据 |

### AI 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/ai/decompose` | 拆解任务，生成子任务 |
| `POST` | `/api/ai/prioritize` | 分析优先级并回写任务 |
| `POST` | `/api/ai/schedule` | 根据空闲时段安排任务 |

## 项目结构

```text
task-app/
├─ app.py                    Flask 入口和 API
├─ ai_service.py             AI Provider 封装与兜底逻辑
├─ static/
│  ├─ index.html             主页面，包含主要前端逻辑
│  ├─ local-api.js           本地存储模式接口模拟
│  ├─ manifest.json          PWA manifest
│  └─ sw.js                  Service Worker
├─ templates/                预留目录
├─ Dockerfile
├─ requirements.txt
├─ FIGMA_DESIGN_BRIEF.md
├─ FRONTEND_STRUCTURE.md
└─ taskflow-ai-src/          历史原型/参考代码
```

## 适合继续迭代的方向

- 把 `static/index.html` 拆分成模块化前端结构
- 增加 `.env.example`
- 为本地模式和远程模式提供显式配置开关
- 增加自动化测试和 API 文档
- 增加用户登录与多账号隔离

## 说明

- 当前主应用以前端单文件页面为主，适合快速迭代原型
- 仓库里的 `taskflow-ai-src/` 是历史参考，不是主运行入口
- 如果你只是想快速体验产品，直接使用默认本地模式即可
