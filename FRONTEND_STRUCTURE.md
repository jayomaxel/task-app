# TimeManager 前端设计结构梳理

更新时间：2026-04-05

## 1. 结论

- 当前真正生效的前端是 `task-app/static/index.html`，由 Flask 在 `/` 路由直接返回静态页面。
- 当前前端不是多路由网站，而是一个单页 PWA；“页面”实际表现为底部导航切换的 4 个主视图。
- 仓库里另外还有一套参考原型：`taskflow-ai-src/templates/index.html` + `taskflow-ai-src/static/js/app.js`。这套原型仍保留在仓库中，但它不是当前 `task-app` 正在使用的 UI。
- `task-app/taskflow-ai-src/` 是参考原型的镜像副本，结构与根目录 `taskflow-ai-src/` 基本一致，本文不重复展开。

## 2. 前端入口与文件分布

### 当前生效前端

- 页面入口：`task-app/app.py:372-376`
- 主页面：`task-app/static/index.html:1-2209`
- PWA manifest：`task-app/static/manifest.json:1-22`
- Service Worker：`task-app/static/sw.js:1-76`

### 参考原型前端

- 原型入口：`taskflow-ai-src/app.py:14-17`
- 原型模板：`taskflow-ai-src/templates/index.html:1-139`
- 原型脚本：`taskflow-ai-src/static/js/app.js:1-360`

## 3. 当前前端总结构

当前页面在 DOM 上的主结构可以概括为：

```text
/
└─ app-shell
   ├─ app-main
   │  ├─ Today 视图
   │  ├─ All 视图
   │  ├─ Timeline 视图
   │  └─ AI Assistant 视图
   ├─ 浮动新建按钮
   ├─ 底部导航
   ├─ 新建/编辑任务底部弹窗
   ├─ 任务操作底部弹窗
   ├─ Toast 提示层
   └─ Loading 遮罩层
```

对应代码位置：

- 视觉变量、主题和基础布局：`task-app/static/index.html:9-979`
- 页面主骨架：`task-app/static/index.html:982-1229`
- 全局状态与初始化：`task-app/static/index.html:1231-1277`
- 事件绑定：`task-app/static/index.html:1279-1368`
- 数据刷新与视图切换：`task-app/static/index.html:1370-1423`

## 4. 当前前端页面视图

### 4.1 Today 视图

定位：底部导航中的“今天”页，是默认首页。

结构：

- 顶部 Hero 卡片
  - 日期标题 `todayDateLabel`
  - 未完成任务统计 `todayPendingCount`
  - 今日摘要 `todaySummaryText`
- 优先任务列表 `todayTaskList`

交互特点：

- 只展示顶级、未完成任务
- 点击任务卡片上的展开子任务按钮时，会切换到 “All” 视图继续查看母子结构

代码引用：

- HTML 结构：`task-app/static/index.html:984-1004`
- 今日头部数据计算：`task-app/static/index.html:1425-1438`
- 列表渲染：`task-app/static/index.html:1474-1479`
- 任务卡复用：`task-app/static/index.html:1612-1657`

### 4.2 All 视图

定位：任务总览页。

结构：

- 页面标题和说明
- 过滤 Chips
  - `all`
  - `doing`
  - `done`
- 分层任务列表 `allTaskList`

交互特点：

- 以母任务/子任务树状方式展示
- 支持展开/收起子任务
- 支持按状态筛选
- 当某个母任务本身不匹配筛选条件，但其子任务命中筛选时，母任务会以“上下文父节点”形式保留显示

代码引用：

- HTML 结构：`task-app/static/index.html:1007-1019`
- 筛选事件绑定：`task-app/static/index.html:1310-1315`
- 排序与树结构：`task-app/static/index.html:1440-1466`
- 列表渲染：`task-app/static/index.html:1481-1525`
- 展开/收起与菜单点击：`task-app/static/index.html:1953-1968`

### 4.3 Timeline 视图

定位：时间轴视图，用于按时间查看截止日期与 AI 规划时间。

结构：

- 时间轴容器 `timelineContainer`
- 三类分组
  - `overdue`
  - `today`
  - `future`
- 每个日期下展示若干 `timeline-card`

交互特点：

- 时间基准优先使用 `scheduled_start`，否则回退到 `due_date`
- 卡片中展示优先级、相对日期、预计时长、AI 规划时间段
- 卡片右侧保留操作菜单入口

代码引用：

- HTML 结构：`task-app/static/index.html:1022-1028`
- 时间轴渲染主逻辑：`task-app/static/index.html:1527-1578`
- 时间轴卡片：`task-app/static/index.html:1580-1609`

### 4.4 AI Assistant 视图

定位：底部导航中的 AI 助手页。

这一页实际上包含 3 个独立功能区，而不是 1 个弹窗：

#### A. 任务拆解

结构：

- 任务标题输入
- 任务描述输入
- 关联母任务选择器
- `AI 拆解` 按钮
- 拆解结果区 `decomposeResultBox`

交互特点：

- 可直接输入新任务，也可基于已有母任务做拆解
- 后端返回结果后，前端使用逐条 reveal 的方式把子任务显式显示出来

代码引用：

- HTML 结构：`task-app/static/index.html:1032-1067`
- 结果渲染：`task-app/static/index.html:1725-1734`
- 提示文案联动：`task-app/static/index.html:1673-1680`
- 提交处理：`task-app/static/index.html:1796-1828`

#### B. 优先级分析

结构：

- `开始分析` 按钮
- `一键应用（已同步）` 按钮
- 结果区 `prioritizeResultBox`

交互特点：

- 分析前会记录当前优先级，结果区同时展示“当前值 -> 建议值”
- 当前实现里结果已经由后端写回数据库，页面中的“应用”更偏刷新确认

代码引用：

- HTML 结构：`task-app/static/index.html:1070-1087`
- 结果渲染：`task-app/static/index.html:1736-1746`
- 提交处理：`task-app/static/index.html:1830-1853`

#### C. 日程规划

结构：

- 可增删的空闲时间段输入区 `slotList`
- 待规划任务勾选列表 `scheduleTaskList`
- `AI 规划` 按钮
- `确认保存（已同步）` 按钮
- 结果区 `scheduleResultBox`

交互特点：

- 默认勾选所有未完成任务
- 支持“全选 / 全不选”
- 任务选择与时间段输入都保存在前端状态里
- 规划结果展示具体开始/结束时间，无法安排时展示原因

代码引用：

- HTML 结构：`task-app/static/index.html:1090-1119`
- 任务勾选列表渲染：`task-app/static/index.html:1683-1703`
- 时间段输入渲染：`task-app/static/index.html:1705-1723`
- 结果渲染：`task-app/static/index.html:1748-1760`
- 提交处理：`task-app/static/index.html:1855-1888`
- 全选逻辑：`task-app/static/index.html:1930-1935`

## 5. 当前前端弹窗与浮层

### 5.1 新建 / 编辑任务 Bottom Sheet

定位：从右下角浮动按钮进入，或从任务操作菜单进入编辑。

结构：

- 标题 `taskSheetTitle`
- 副标题 `taskSheetSubtitle`
- 隐藏字段
  - `taskId`
  - `taskPriorityValue`
- 表单字段
  - 标题
  - 描述
  - 优先级选择器
  - 截止日期
  - 预计耗时
  - 母任务选择器
- 操作按钮
  - 保存
  - 取消

交互特点：

- 既承担“新建任务”，也承担“编辑任务”
- 打开时自动回填表单
- 提交后根据是否存在 `taskId` 决定调用 `POST /api/tasks` 或 `PUT /api/tasks/:id`

代码引用：

- HTML 结构：`task-app/static/index.html:1146-1198`
- 打开/关闭：`task-app/static/index.html:1970-1986`
- 提交逻辑：`task-app/static/index.html:1762-1794`
- 优先级选择器：`task-app/static/index.html:1890-1903`

### 5.2 任务操作 Bottom Sheet

定位：任务卡右侧的 `⋯` 菜单按钮进入。

结构：

- 任务标题
- 任务状态与优先级摘要
- 操作按钮
  - 编辑任务
  - 标记完成 / 标记为未完成
  - 删除任务
  - 取消

交互特点：

- 打开时根据任务状态动态切换文案
- 删除前还会再触发一次浏览器原生 `confirm`

代码引用：

- HTML 结构：`task-app/static/index.html:1200-1218`
- 打开/关闭：`task-app/static/index.html:1988-2001`
- 编辑跳转：`task-app/static/index.html:2003-2006`
- 标记完成：`task-app/static/index.html:2009-2020`
- 删除任务：`task-app/static/index.html:2022-2030`

### 5.3 Toast 提示层

用途：显示成功/失败提示。

代码引用：

- HTML：`task-app/static/index.html:1220-1221`
- 显示逻辑：`task-app/static/index.html:2066-2074`

### 5.4 Loading 遮罩层

用途：所有 API 请求期间展示统一 loading。

代码引用：

- HTML：`task-app/static/index.html:1224-1228`
- 通用请求封装：`task-app/static/index.html:2033-2053`
- 显示/隐藏：`task-app/static/index.html:2055-2064`

### 5.5 原生确认框

当前并没有自定义删除确认弹窗，删除时走的是浏览器原生 `window.confirm(...)`。

代码引用：

- 删除确认：`task-app/static/index.html:2025`

## 6. 当前前端复用组件/视图单元

虽然当前代码还是单文件组织，但已经存在明确的“组件边界”：

- 任务卡 `renderTaskCard()`：`task-app/static/index.html:1612-1657`
- 时间轴卡 `renderTimelineCard()`：`task-app/static/index.html:1580-1609`
- 任务树分支 `renderTaskBranch()`：`task-app/static/index.html:1496-1525`
- 日程任务选择项：`task-app/static/index.html:1683-1703`
- 时间段输入项：`task-app/static/index.html:1705-1723`
- 三类 AI 结果列表
  - 拆解结果：`task-app/static/index.html:1725-1734`
  - 优先级结果：`task-app/static/index.html:1736-1746`
  - 日程规划结果：`task-app/static/index.html:1748-1760`

## 7. 当前前端状态与交互流

### 7.1 状态中心

当前页面没有使用框架，状态集中在 `state` 对象里：

- 当前激活 tab
- All 页筛选状态
- 任务列表
- 时间轴列表
- 已展开的母任务集合
- 当前 action sheet 任务 id
- AI 三个子模块的结果和中间状态

代码引用：

- 状态对象：`task-app/static/index.html:1231-1249`

### 7.2 初始化流程

页面加载顺序：

1. 缓存 DOM 节点
2. 绑定事件
3. 初始化优先级选择器
4. 初始化日程时间段输入
5. 设置今日头部
6. 注册 PWA
7. 加载任务与时间轴

代码引用：

- `init()`：`task-app/static/index.html:1267-1277`
- `cacheElements()`：`task-app/static/index.html:1279-1303`
- `bindEvents()`：`task-app/static/index.html:1305-1368`
- `refreshAll()`：`task-app/static/index.html:1379-1384`

### 7.3 视图切换

- 通过 `state.activeTab` 控制底部导航与 tab-panel 的显隐
- 不是路由切换，没有 URL 层面的页面变化

代码引用：

- `setActiveTab()`：`task-app/static/index.html:1410-1413`
- `updateNav()`：`task-app/static/index.html:1415-1422`

## 8. 当前前端接口依赖

### 页面基础数据

| 接口 | 用途 | 前端调用位置 | 后端实现位置 |
| --- | --- | --- | --- |
| `GET /api/tasks?sort=created_at` | 拉取任务列表 | `task-app/static/index.html:1386-1389` | `task-app/app.py:381-419` |
| `GET /api/timeline` | 拉取时间轴数据 | `task-app/static/index.html:1391-1394` | `task-app/app.py:708-725` |

### 任务 CRUD

| 接口 | 用途 | 前端调用位置 | 后端实现位置 |
| --- | --- | --- | --- |
| `POST /api/tasks` | 新建任务 | `task-app/static/index.html:1783-1789` | `task-app/app.py:422-469` |
| `PUT /api/tasks/:id` | 更新任务 / 标记完成 | `task-app/static/index.html:1783-1789`, `2012-2016` | `task-app/app.py:472-553` |
| `DELETE /api/tasks/:id` | 删除任务 | `task-app/static/index.html:2027` | `task-app/app.py:556-565` |

### AI 能力

| 接口 | 用途 | 前端调用位置 | 后端实现位置 |
| --- | --- | --- | --- |
| `POST /api/ai/decompose` | 任务拆解 | `task-app/static/index.html:1812-1816` | `task-app/app.py:568-635` |
| `POST /api/ai/prioritize` | 优先级分析 | `task-app/static/index.html:1832-1836` | `task-app/app.py:638-665` |
| `POST /api/ai/schedule` | 日程规划 | `task-app/static/index.html:1873-1877` | `task-app/app.py:668-705` |

## 9. PWA 相关结构

当前前端具备基础 PWA 能力：

- HTML 中注册 `manifest.json`
- 页面加载后注册 `sw.js`
- `sw.js` 对首页和 manifest 走 Cache First
- `/api/*` 走 Network First

代码引用：

- `manifest` 引入：`task-app/static/index.html:8`
- Service Worker 注册：`task-app/static/index.html:1370-1377`
- Manifest 内容：`task-app/static/manifest.json:1-22`
- Service Worker 逻辑：`task-app/static/sw.js:1-76`

## 10. 参考原型前端结构

这部分不是当前主应用，但属于仓库中的前端设计资源，后续如果要回溯历史方案会用到。

### 原型页面结构

原型同样是单页，但结构更简单：

- 顶部 Header
  - 品牌标题
  - 主题切换按钮
  - 语音输入按钮
- 中间输入区
  - 文本输入框
  - Generate Plan
  - Clear
  - 字数统计
- Loading 区块
- 结果区
  - 分类卡片区
  - 建议时间表
  - Save / Export 操作区
- Footer

代码引用：

- 原型模板结构：`taskflow-ai-src/templates/index.html:29-138`
- 原型初始化：`taskflow-ai-src/static/js/app.js:2-13`
- 事件绑定：`taskflow-ai-src/static/js/app.js:15-47`
- 语音输入：`taskflow-ai-src/static/js/app.js:49-88`
- 主题切换：`taskflow-ai-src/static/js/app.js:90-104`
- 生成计划：`taskflow-ai-src/static/js/app.js:112-149`
- 结果渲染：`taskflow-ai-src/static/js/app.js:151-214`
- 保存与导出：`taskflow-ai-src/static/js/app.js:244-321`
- 提示消息：`taskflow-ai-src/static/js/app.js:342-360`

### 原型接口依赖

| 接口 | 用途 | 前端调用位置 | 后端实现位置 |
| --- | --- | --- | --- |
| `POST /api/plan` | 生成日计划 | `taskflow-ai-src/static/js/app.js:126-132` | `taskflow-ai-src/app.py:19-38` |
| `POST /api/save-plan` | 保存计划 | `taskflow-ai-src/static/js/app.js:251-260` | `taskflow-ai-src/app.py:40-56` |
| `GET /api/load-plan` | 读取计划 | 当前前端脚本未直接调用 | `taskflow-ai-src/app.py:58-72` |

## 11. 前端代码引用清单

如果你后面要继续拆组件、补设计稿或重构，优先看这几处：

- 当前主前端入口：`task-app/app.py:372-376`
- 当前主页面（HTML + CSS + JS 全部在内）：`task-app/static/index.html:1-2209`
- 当前 PWA 配置：`task-app/static/manifest.json:1-22`
- 当前 Service Worker：`task-app/static/sw.js:1-76`
- 参考原型模板：`taskflow-ai-src/templates/index.html:1-139`
- 参考原型脚本：`taskflow-ai-src/static/js/app.js:1-360`
- 参考原型后端入口：`taskflow-ai-src/app.py:14-72`

## 12. 如果后续要拆分组件，建议的边界

这不是当前代码现状，而是基于现有结构最自然的拆分方式：

- `AppShell`
- `TodayView`
- `AllTasksView`
- `TimelineView`
- `AiAssistantView`
- `DecomposePanel`
- `PrioritizePanel`
- `SchedulePanel`
- `TaskSheet`
- `TaskActionSheet`
- `TaskCard`
- `TimelineCard`
- `Toast`
- `LoadingOverlay`
- `api.ts` 或 `services/api.js`
- `state.ts` 或 `store.js`

