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

## 第二部分：Task Chain 功能规格（规划）

以下内容为规划中的 Task Chain 设计规格，用于描述下一阶段的数据模型、状态机、历史记录与 API 设计。当前代码库尚未完整实现这一部分能力。

### 2.1 核心理念

任务链路不是普通的子任务列表，而是一组具有明确前后关系、依赖关系和执行路径的子任务链。每个子任务都知道自己从哪来、到哪去、前置是什么、阻塞了谁。

整条链可以由 AI 规划，也可以被用户随时手动调整，两者共存且不冲突。

### 2.2 子任务数据模型扩展

在现有 `tasks` 表基础上，规划新增以下字段：

| 新增字段 | 类型 | 说明 |
| --- | --- | --- |
| `chain_id` | `UUID` | 所属链路 ID，同一链路的子任务共享此值 |
| `chain_order` | `INTEGER` | 链路内排序序号，从 `0` 开始 |
| `depends_on` | `INTEGER[]` | 前置依赖任务 ID 数组，空数组表示无依赖 |
| `objective` | `TEXT` | 任务目标，描述此步骤要达成什么 |
| `preconditions` | `TEXT` | 前置条件描述，自然语言表达 |
| `next_suggestion` | `TEXT` | AI 生成的下一步建议 |
| `risk_notes` | `TEXT` | 可选的风险说明或备注 |
| `block_reason` | `TEXT` | 当状态为 `blocked` 时记录阻塞原因 |
| `modified_by` | `TEXT` | 最后修改来源，取值为 `user` / `ai` |
| `modification_note` | `TEXT` | 修改说明，记录为什么改、改了什么 |

### 2.3 任务状态扩展

`status` 字段计划从当前 3 种状态扩展为 6 种：

| 状态 | 含义 | 颜色建议 |
| --- | --- | --- |
| `todo` | 待开始 | 灰色 |
| `doing` | 进行中 | 蓝色 |
| `done` | 已完成 | 绿色 |
| `blocked` | 被阻塞，等待外部条件或前置任务 | 红色 |
| `skipped` | 已跳过，不再执行但保留记录 | 黄色 |
| `cancelled` | 已取消 | 深灰色 |

### 2.4 链路变更历史表 `task_chain_logs`

规划新增 `task_chain_logs` 表，用来记录链路的每一次变更：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `SERIAL PRIMARY KEY` | 日志主键 |
| `chain_id` | `UUID` | 关联链路 |
| `task_id` | `INTEGER` | 被变更的任务，可为 `NULL` 表示链路级操作 |
| `action` | `TEXT` | 操作类型：`create` / `update` / `delete` / `reorder` / `merge` / `split` / `ai_adjust` |
| `actor` | `TEXT` | 操作者：`user` / `ai` |
| `reason` | `TEXT` | 变更原因 |
| `before_snapshot` | `JSONB` | 变更前快照 |
| `after_snapshot` | `JSONB` | 变更后快照 |
| `impact_summary` | `TEXT` | 对后续任务的影响说明 |
| `created_at` | `TIMESTAMPTZ` | 变更时间 |

### 2.5 新增 API 端点

为支持链路化任务，规划新增以下接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/chains` | 创建新链路，支持 AI 拆分或手动创建 |
| `GET` | `/api/chains/<chain_id>` | 获取完整链路，包含全部子任务和依赖关系 |
| `PUT` | `/api/chains/<chain_id>` | 更新链路元信息 |
| `DELETE` | `/api/chains/<chain_id>` | 删除整条链路 |
| `POST` | `/api/chains/<chain_id>/tasks` | 在链路中添加子任务 |
| `PUT` | `/api/chains/<chain_id>/tasks/<task_id>` | 更新链路中的某个子任务 |
| `DELETE` | `/api/chains/<chain_id>/tasks/<task_id>` | 从链路中删除子任务 |
| `PUT` | `/api/chains/<chain_id>/reorder` | 调整链路内任务顺序和依赖 |
| `POST` | `/api/chains/<chain_id>/merge` | 合并多个子任务为一个 |
| `POST` | `/api/chains/<chain_id>/split` | 将一个子任务拆分为多个 |
| `GET` | `/api/chains/<chain_id>/logs` | 获取链路变更历史 |
| `POST` | `/api/ai/chain-decompose` | AI 链路化拆分任务，作为原有 `decompose` 的升级版本 |
| `POST` | `/api/ai/chain-adjust` | AI 基于自然语言指令调整链路 |
| `POST` | `/api/ai/chain-continue` | AI 在现有链路基础上继续规划 |

## 第三部分：AI 链路拆分与动态调整（规划）

以下内容描述的是 Task Chain 场景下的 AI 拆分和后端处理方案，当前代码库尚未完整实现这些接口。

### 3.1 AI 链路拆分 `/api/ai/chain-decompose`

该接口规划用于替代原有 `/api/ai/decompose`，返回带有依赖关系的链路化结构。

#### 3.1.1 请求格式

```http
POST /api/ai/chain-decompose
Content-Type: application/json
```

```json
{
  "title": "开发用户注册模块",
  "description": "包含邮箱注册、手机注册、第三方登录",
  "context": "这是一个 Flask 后端项目，前端原生 JS"
}
```

#### 3.1.2 AI 返回格式

Prompt 应要求 AI 严格输出以下链路化结构：

```json
{
  "chain_title": "开发用户注册模块",
  "tasks": [
    {
      "temp_id": "t1",
      "title": "设计数据库 users 表",
      "objective": "确定用户表字段和索引",
      "preconditions": "无",
      "depends_on": [],
      "estimated_minutes": 45,
      "risk_notes": "需要确认是否支持多种登录方式的统一 ID",
      "next_suggestion": "完成后开始写注册 API"
    },
    {
      "temp_id": "t2",
      "title": "实现邮箱注册 API",
      "objective": "POST /api/register 接收邮箱和密码",
      "preconditions": "users 表已创建",
      "depends_on": ["t1"],
      "estimated_minutes": 90,
      "risk_notes": "需处理邮箱验证逻辑",
      "next_suggestion": "注册完成后做登录接口"
    }
  ]
}
```

#### 3.1.3 后端处理逻辑

后端的预期处理流程如下：

1. 生成 `chain_id`，类型为 `UUID`
2. 第一轮遍历 `tasks`，创建真实任务记录，并建立 `temp_id -> real_id` 的映射
3. 第二轮遍历 `tasks`，将 `depends_on` 中的 `temp_id` 替换为真实 `task_id` 后写回数据库
4. 写入 `task_chain_logs`，其中 `action = 'create'`，`actor = 'ai'`
5. 返回完整链路结果

### 3.2 AI 链路调整 `/api/ai/chain-adjust`

该接口规划用于让用户通过自然语言描述链路调整需求，由 AI 理解上下文后输出结构化调整指令。

#### 3.2.1 请求格式

```http
POST /api/ai/chain-adjust
Content-Type: application/json
```

```json
{
  "chain_id": "uuid-xxx",
  "instruction": "第三步做不了了，客户说不需要手机注册，删掉它，然后把第四步提前",
  "current_chain": [],
  "context": "可选的额外上下文"
}
```

说明：

- `chain_id` 表示要被调整的目标链路
- `instruction` 是用户的自然语言修改意图
- `current_chain` 是当前完整链路快照，供 AI 基于上下文做判断
- `context` 为可选扩展上下文，例如项目背景、业务限制或外部依赖

#### 3.2.2 AI 返回格式

AI 应返回结构化的调整指令，而不是直接返回自然语言描述：

```json
{
  "adjustments": [
    {
      "action": "delete",
      "task_id": 15,
      "reason": "客户确认不需要手机注册"
    },
    {
      "action": "update",
      "task_id": 16,
      "changes": {
        "chain_order": 2,
        "depends_on": [13],
        "preconditions": "邮箱注册完成后直接做第三方登录"
      },
      "reason": "前置任务删除后调整依赖"
    }
  ],
  "impact_summary": "删除手机注册后链路从 5 步缩减为 4 步，第三方登录提前，总预估时间减少 60 分钟",
  "chain_status_note": "链路已优化，无阻塞节点"
}
```

#### 3.2.3 后端处理逻辑

后端的预期处理流程如下：

6. 读取 `chain_id` 对应的完整链路，构建 `current_chain`
7. 将 `current_chain` 与 `instruction` 一起发送给 AI，优先使用 smart model
8. 解析 AI 返回的 `adjustments` 数组
9. 按顺序逐条执行变更动作，例如 `delete` / `update` / `insert` / `reorder` / `merge` / `split`
10. 每条变更执行前保存 `before_snapshot`，执行后保存 `after_snapshot`
11. 写入 `task_chain_logs`，保留完整变更历史
12. 返回调整后的完整链路以及变更摘要

这一设计的关键点是：AI 负责生成“调整建议”，后端负责执行、校验、持久化和审计。

### 3.3 AI 续规划 `/api/ai/chain-continue`

该接口规划用于在用户已经完成部分任务，或者中途插入新需求时，让 AI 基于现有进度继续规划后续步骤，而不是从头重新生成整条链路。

#### 3.3.1 请求格式

```http
POST /api/ai/chain-continue
Content-Type: application/json
```

```json
{
  "chain_id": "uuid-xxx",
  "current_chain": [],
  "instruction": "前三步已经完成了，后面还需要加上部署和测试环节"
}
```

说明：

- `chain_id` 表示当前续规划所针对的链路
- `current_chain` 是链路的完整当前状态，必须包含已完成、进行中、未开始和被阻塞节点
- `instruction` 描述用户对后续规划的新增要求或变化

#### 3.3.2 AI 行为要求

AI 在生成续规划结果时应遵守以下原则：

- 保留已经完成的任务，不修改其标题、顺序和依赖
- 尽量不干扰已确认的在途任务，除非用户明确要求调整
- 在链路末尾追加新增任务，或在必要时插入合理的新节点
- 为新增任务正确设置 `depends_on`
- 更新整体 `impact_summary`，说明新增任务对工期、步骤数和后续依赖的影响

#### 3.3.3 预期结果

对于示例请求，AI 的目标不是重建整条链路，而是基于现有状态进行增量规划。例如：

- 保留前三步已完成节点不变
- 在后续阶段追加“测试环节”和“部署环节”
- 将新任务的依赖设置为最后一个尚未完成或刚完成的关键节点
- 生成新的链路摘要，说明链路长度、总预估时间和新增风险点的变化

这一接口的核心价值在于“延续性规划”：链路会随着真实进度自然演化，而不是每次都被整条重算。

## 第四部分：用户手动编辑与 AI 协同（规划）

以下内容描述的是 Task Chain 场景下用户手动编辑链路、以及与 AI 协同工作的规则。当前代码库尚未完整实现这些能力。

### 4.1 用户可执行的手动操作

| 操作 | API | 说明 |
| --- | --- | --- |
| 新增子任务 | `POST /api/chains/<chain_id>/tasks` | 支持指定插入位置和依赖 |
| 删除子任务 | `DELETE /api/chains/<chain_id>/tasks/<task_id>` | 删除后自动重连依赖链 |
| 修改任务内容 | `PUT /api/chains/<chain_id>/tasks/<task_id>` | 可修改标题、描述、目标等字段 |
| 调整顺序 | `PUT /api/chains/<chain_id>/reorder` | 支持拖拽排序，传入新的顺序数组 |
| 修改依赖 | `PUT /api/chains/<chain_id>/tasks/<task_id>` | 直接修改 `depends_on` 数组 |
| 合并任务 | `POST /api/chains/<chain_id>/merge` | 传入需要合并的 `task_ids` |
| 拆分任务 | `POST /api/chains/<chain_id>/split` | 传入 `task_id` 和拆分后的子任务数据 |
| 标记状态 | `PUT /api/chains/<chain_id>/tasks/<task_id>` | 支持设置 `status = blocked / skipped / done` 等 |

### 4.2 协同规则

#### 4.2.1 `modified_by` 标记

每次修改都应记录 `modified_by = 'user'` 或 `modified_by = 'ai'`。

当 AI 在调整链路时，如果发现某个任务的 `modified_by = 'user'`，应遵守以下规则：

- 优先保留用户修改过的内容
- 如果必须变更用户修改过的字段，需要在 `modification_note` 中明确说明原因
- 不允许静默覆盖用户手动设置的状态、描述或其他关键字段

#### 4.2.2 删除任务时的依赖重连

当删除链路中间的任务 B 时，如果原链路关系是 `A -> B -> C`，后端应自动将 C 的 `depends_on` 从 `[B]` 改为 `[A]`。

也就是说，被删除任务的下游节点会继承它的上游依赖，从而避免链路被直接断开。

#### 4.2.3 状态传播

当某个任务被标记为 `blocked` 时，所有直接或间接依赖它的下游任务都应自动变为 `blocked`，前提是这些下游任务当前仍处于 `todo` 状态。

当阻塞解除时，这些因为依赖阻塞而被动变更的下游任务应恢复为 `todo`。

#### 4.2.4 并发安全

为了防止 AI 调整和用户编辑同时操作同一条链路，后端在执行链路级数据库变更时应使用 `SELECT ... FOR UPDATE` 行级锁。

前端在 AI 调整进行中时，应显示 loading 状态，并禁用链路编辑相关按钮，避免产生冲突操作。

## 第五部分：运行模式与启动

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

## 第六部分：每日空闲时间与日程规划（规划）

以下内容描述的是面向日计划生成的空闲时间管理与 AI 排程方案，当前代码库尚未完整实现这些能力。

### 6.1 功能概述

用户每天早上填写当日空闲时间段，系统结合任务链路的优先级和依赖关系，智能安排当日任务。

空闲时间可以随时修改，系统需要支持实时重新计算排程可能性，但不应在用户未确认的情况下自动覆盖已有安排。

### 6.2 新建 `daily_availability` 表

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `SERIAL PRIMARY KEY` | 主键 |
| `user_id` | `TEXT` | 用户标识 |
| `date` | `DATE` | 日期 |
| `slots` | `JSONB` | 当日空闲时间段数组 |
| `notes` | `TEXT` | 当日备注，例如“下午有会议” |
| `created_at` | `TIMESTAMPTZ` | 创建时间 |
| `updated_at` | `TIMESTAMPTZ` | 更新时间 |

#### 6.2.1 `slots` JSONB 结构

```json
[
  { "start": "09:00", "end": "12:00", "label": "上午" },
  { "start": "14:00", "end": "17:30", "label": "下午" },
  { "start": "20:00", "end": "22:00", "label": "晚上" }
]
```

### 6.3 新增 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/daily-availability?date=2026-04-07` | 获取某日空闲时间 |
| `PUT` | `/api/daily-availability` | 设置或更新某日空闲时间 |
| `POST` | `/api/ai/daily-plan` | AI 基于空闲时间和链路任务生成当日计划 |

### 6.4 AI 当日计划生成逻辑

后端预期处理流程如下：

13. 读取指定日期的 `daily_availability`
14. 读取所有未完成链路任务，并按优先级与依赖关系排序
15. 过滤掉 `blocked` / `skipped` 状态的任务
16. 只安排 `depends_on` 已全部完成、即依赖已解锁的任务
17. 调用 AI，优先使用 smart model，将任务排入当天空闲时间段
18. 返回排程结果，并写入 `scheduled_start` / `scheduled_end`

重要说明：

- 当空闲时间发生修改时，前端应提示用户“是否重新排程”
- 系统不应自动重排，避免覆盖用户已经手动调整过的安排
- AI 排程结果应与任务链路状态保持一致，不能跳过未解锁依赖直接安排后续步骤

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
