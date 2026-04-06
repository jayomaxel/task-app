(function () {
  const STORAGE_KEY = "timeManager.local-data.v1"
  const VALID_STATUSES = new Set(["todo", "doing", "done"])
  const SUPPORTED_ROUTES = [
    /^\/api\/tasks$/,
    /^\/api\/tasks\/\d+$/,
    /^\/api\/timeline$/,
    /^\/api\/ai\/decompose$/,
    /^\/api\/ai\/prioritize$/,
    /^\/api\/ai\/schedule$/,
  ]
  const memoryFallback = new Map()

  class LocalApiError extends Error {
    constructor(message, status = 400) {
      super(message)
      this.name = "LocalApiError"
      this.status = status
    }
  }

  function getStorageItem(key) {
    try {
      return window.localStorage.getItem(key)
    } catch (_error) {
      return memoryFallback.has(key) ? memoryFallback.get(key) : null
    }
  }

  function setStorageItem(key, value) {
    try {
      window.localStorage.setItem(key, value)
    } catch (_error) {
      memoryFallback.set(key, value)
    }
  }

  function loadStore() {
    const raw = getStorageItem(STORAGE_KEY)
    if (!raw) return { version: 1, lastId: 0, tasks: [] }

    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        const tasks = parsed.map(normalizeStoredTask).filter(Boolean)
        return { version: 1, lastId: getMaxTaskId(tasks), tasks }
      }

      const tasks = Array.isArray(parsed.tasks) ? parsed.tasks.map(normalizeStoredTask).filter(Boolean) : []
      return {
        version: 1,
        lastId: Math.max(Number(parsed.lastId) || 0, getMaxTaskId(tasks)),
        tasks,
      }
    } catch (_error) {
      return { version: 1, lastId: 0, tasks: [] }
    }
  }

  function saveStore(store) {
    const next = {
      version: 1,
      lastId: Math.max(Number(store.lastId) || 0, getMaxTaskId(store.tasks)),
      tasks: store.tasks.map(normalizeStoredTask).filter(Boolean),
    }
    setStorageItem(STORAGE_KEY, JSON.stringify(next))
    return next
  }

  function getMaxTaskId(tasks) {
    return tasks.reduce((maxId, task) => Math.max(maxId, Number(task.id) || 0), 0)
  }

  function normalizeStoredTask(task) {
    if (!task || typeof task !== "object") return null

    const id = Number(task.id)
    if (!Number.isInteger(id) || id <= 0) return null

    const createdAt = safeIso(task.created_at) || new Date().toISOString()
    return {
      id,
      title: String(task.title || "").trim() || `任务 ${id}`,
      description: String(task.description || "").trim(),
      priority: clampPriority(task.priority),
      status: normalizeStatus(task.status, "todo"),
      parent_id: normalizeNullableId(task.parent_id),
      due_date: safeIso(task.due_date),
      estimated_minutes: safePositiveInt(task.estimated_minutes),
      scheduled_start: safeIso(task.scheduled_start),
      scheduled_end: safeIso(task.scheduled_end),
      created_at: createdAt,
      updated_at: safeIso(task.updated_at) || createdAt,
    }
  }

  function normalizeStatus(value, fallback) {
    const status = String(value || fallback || "todo").trim().toLowerCase()
    return VALID_STATUSES.has(status) ? status : String(fallback || "todo")
  }

  function clampPriority(value) {
    const priority = Number(value)
    if (!Number.isFinite(priority)) return 3
    return Math.max(1, Math.min(5, Math.round(priority)))
  }

  function safePositiveInt(value) {
    if (value == null || value === "") return null
    const number = Number(value)
    if (!Number.isInteger(number) || number <= 0) return null
    return number
  }

  function safeIso(value) {
    if (value == null || value === "") return null
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return null
    return date.toISOString()
  }

  function normalizeNullableId(value) {
    if (value == null || value === "") return null
    if (String(value).trim().toLowerCase() === "null") return null
    const id = Number(value)
    if (!Number.isInteger(id) || id <= 0) return null
    return id
  }

  function parseBody(options) {
    if (!options || options.body == null || options.body === "") return {}
    if (typeof options.body === "string") {
      try {
        return JSON.parse(options.body)
      } catch (_error) {
        throw new LocalApiError("JSON 格式无效", 400)
      }
    }
    if (typeof options.body === "object") return options.body
    throw new LocalApiError("请求体必须是 JSON", 400)
  }

  function parsePriority(value, defaultValue = 3) {
    if (value == null || value === "") return defaultValue
    const priority = Number(value)
    if (!Number.isInteger(priority) || priority < 1 || priority > 5) {
      throw new LocalApiError("priority 必须在 1 到 5 之间", 400)
    }
    return priority
  }

  function parseEstimatedMinutes(value) {
    if (value == null || value === "") return null
    const minutes = Number(value)
    if (!Number.isInteger(minutes) || minutes <= 0) {
      throw new LocalApiError("estimated_minutes 必须是大于 0 的整数", 400)
    }
    return minutes
  }

  function parseStatus(value, defaultValue = "todo") {
    if (value == null || value === "") return defaultValue
    const status = String(value).trim().toLowerCase()
    if (!VALID_STATUSES.has(status)) {
      throw new LocalApiError("status 只能是 todo / doing / done", 400)
    }
    return status
  }

  function parseOptionalId(value, fieldName) {
    if (value == null || value === "") return null
    if (String(value).trim().toLowerCase() === "null") return null
    const id = Number(value)
    if (!Number.isInteger(id) || id <= 0) {
      throw new LocalApiError(`${fieldName} 必须是整数或 null`, 400)
    }
    return id
  }

  function parseTaskIds(value) {
    if (value == null) return []
    if (!Array.isArray(value)) throw new LocalApiError("task_ids 必须是数组", 400)
    return value.map((item) => {
      const id = Number(item)
      if (!Number.isInteger(id) || id <= 0) {
        throw new LocalApiError("task_ids 中的每一项都必须是整数", 400)
      }
      return id
    })
  }

  function parseIso(value, fieldName) {
    if (value == null || value === "") return null
    if (String(value).trim().toLowerCase() === "null") return null
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) {
      throw new LocalApiError(`${fieldName} 必须是合法的 ISO 时间字符串`, 400)
    }
    return date.toISOString()
  }

  function ensureTaskExists(tasks, taskId) {
    const task = tasks.find((item) => item.id === taskId)
    if (!task) throw new LocalApiError(`任务不存在: ${taskId}`, 404)
    return task
  }

  function ensureParentExists(tasks, parentId) {
    if (parentId == null) return
    ensureTaskExists(tasks, parentId)
  }

  function createsCycle(tasks, taskId, parentId) {
    let currentId = parentId
    while (currentId != null) {
      if (currentId === taskId) return true
      const parent = tasks.find((item) => item.id === currentId)
      currentId = parent ? parent.parent_id : null
    }
    return false
  }

  function buildTaskResponse(tasks, task) {
    return {
      ...task,
      subtask_count: tasks.reduce((count, item) => count + (item.parent_id === task.id ? 1 : 0), 0),
    }
  }

  function compareDesc(valueA, valueB, fallback = 0) {
    return getTimeValue(valueB, fallback) - getTimeValue(valueA, fallback)
  }

  function compareAsc(valueA, valueB, fallback = Number.MAX_SAFE_INTEGER) {
    return getTimeValue(valueA, fallback) - getTimeValue(valueB, fallback)
  }

  function getTimeValue(value, fallback) {
    if (!value) return fallback
    const time = new Date(value).getTime()
    return Number.isNaN(time) ? fallback : time
  }

  function sortTasks(tasks, sortKey) {
    const sorted = tasks.slice()
    sorted.sort((a, b) => {
      if (sortKey === "priority") {
        const priorityDiff = clampPriority(b.priority) - clampPriority(a.priority)
        return priorityDiff || compareDesc(a.created_at, b.created_at)
      }
      if (sortKey === "due_date") {
        const dueDiff = compareAsc(a.due_date, b.due_date)
        return dueDiff || compareDesc(a.created_at, b.created_at)
      }
      if (sortKey === "scheduled_start") {
        const scheduledDiff = compareAsc(a.scheduled_start, b.scheduled_start)
        return scheduledDiff || compareDesc(a.created_at, b.created_at)
      }
      return compareDesc(a.created_at, b.created_at)
    })
    return sorted
  }

  function listTasks(searchParams) {
    const store = loadStore()
    let tasks = store.tasks.slice()
    const status = searchParams.get("status")
    const sortKey = (searchParams.get("sort") || "created_at").trim() || "created_at"

    if (!["priority", "due_date", "scheduled_start", "created_at"].includes(sortKey)) {
      throw new LocalApiError("sort 只能是 priority / due_date / scheduled_start / created_at", 400)
    }

    if (status) {
      const normalizedStatus = parseStatus(status)
      tasks = tasks.filter((task) => task.status === normalizedStatus)
    }

    if (searchParams.has("parent_id")) {
      const rawParentId = searchParams.get("parent_id")
      const parentId = parseOptionalId(rawParentId, "parent_id")
      tasks = parentId == null
        ? tasks.filter((task) => task.parent_id == null)
        : tasks.filter((task) => task.parent_id === parentId)
    }

    return {
      tasks: sortTasks(tasks, sortKey).map((task) => buildTaskResponse(store.tasks, task)),
    }
  }

  function listTimeline() {
    const store = loadStore()
    const timeline = store.tasks
      .filter((task) => task.status !== "done" && (task.due_date || task.scheduled_start))
      .slice()
      .sort((a, b) => {
        const effectiveA = a.scheduled_start || a.due_date
        const effectiveB = b.scheduled_start || b.due_date
        const effectiveDiff = compareAsc(effectiveA, effectiveB)
        return effectiveDiff || compareAsc(a.created_at, b.created_at, 0)
      })
      .map((task) => buildTaskResponse(store.tasks, task))

    return { timeline }
  }

  function insertTask(store, payload) {
    const now = new Date().toISOString()
    const task = {
      id: store.lastId + 1,
      title: payload.title,
      description: payload.description || "",
      priority: clampPriority(payload.priority),
      status: payload.status || "todo",
      parent_id: payload.parent_id ?? null,
      due_date: payload.due_date ?? null,
      estimated_minutes: payload.estimated_minutes ?? null,
      scheduled_start: payload.scheduled_start ?? null,
      scheduled_end: payload.scheduled_end ?? null,
      created_at: now,
      updated_at: now,
    }

    store.lastId = task.id
    store.tasks.push(task)
    return task
  }

  function createTask(data) {
    const store = loadStore()
    const title = String(data.title || "").trim()
    if (!title) throw new LocalApiError("title 为必填项", 400)

    const parentId = parseOptionalId(data.parent_id, "parent_id")
    ensureParentExists(store.tasks, parentId)

    const task = insertTask(store, {
      title,
      description: String(data.description || "").trim(),
      priority: parsePriority(data.priority, 3),
      status: parseStatus(data.status, "todo"),
      parent_id: parentId,
      due_date: parseIso(data.due_date, "due_date"),
      estimated_minutes: parseEstimatedMinutes(data.estimated_minutes),
      scheduled_start: parseIso(data.scheduled_start, "scheduled_start"),
      scheduled_end: parseIso(data.scheduled_end, "scheduled_end"),
    })

    const nextStore = saveStore(store)
    return buildTaskResponse(nextStore.tasks, task)
  }

  function updateTask(taskId, data) {
    const allowedFields = new Set([
      "title",
      "description",
      "priority",
      "status",
      "parent_id",
      "due_date",
      "estimated_minutes",
      "scheduled_start",
      "scheduled_end",
    ])

    const unknownFields = Object.keys(data).filter((key) => !allowedFields.has(key))
    if (unknownFields.length) {
      throw new LocalApiError(`不支持更新的字段: ${unknownFields.join(", ")}`, 400)
    }

    if (!Object.keys(data).length) {
      throw new LocalApiError("请求体不能为空", 400)
    }

    const store = loadStore()
    const task = ensureTaskExists(store.tasks, taskId)

    if (Object.prototype.hasOwnProperty.call(data, "title")) {
      const title = String(data.title || "").trim()
      if (!title) throw new LocalApiError("title 不能为空", 400)
      task.title = title
    }

    if (Object.prototype.hasOwnProperty.call(data, "description")) {
      task.description = String(data.description || "").trim()
    }

    if (Object.prototype.hasOwnProperty.call(data, "priority")) {
      task.priority = parsePriority(data.priority, task.priority)
    }

    if (Object.prototype.hasOwnProperty.call(data, "status")) {
      task.status = parseStatus(data.status, task.status)
    }

    if (Object.prototype.hasOwnProperty.call(data, "parent_id")) {
      const parentId = parseOptionalId(data.parent_id, "parent_id")
      if (parentId === taskId) throw new LocalApiError("parent_id 不能等于当前任务 id", 400)
      ensureParentExists(store.tasks, parentId)
      if (createsCycle(store.tasks, taskId, parentId)) {
        throw new LocalApiError("parent_id 不能设置为当前任务的子任务", 400)
      }
      task.parent_id = parentId
    }

    if (Object.prototype.hasOwnProperty.call(data, "due_date")) {
      task.due_date = parseIso(data.due_date, "due_date")
    }

    if (Object.prototype.hasOwnProperty.call(data, "estimated_minutes")) {
      task.estimated_minutes = parseEstimatedMinutes(data.estimated_minutes)
    }

    if (Object.prototype.hasOwnProperty.call(data, "scheduled_start")) {
      task.scheduled_start = parseIso(data.scheduled_start, "scheduled_start")
    }

    if (Object.prototype.hasOwnProperty.call(data, "scheduled_end")) {
      task.scheduled_end = parseIso(data.scheduled_end, "scheduled_end")
    }

    task.updated_at = new Date().toISOString()
    const nextStore = saveStore(store)
    return buildTaskResponse(nextStore.tasks, task)
  }

  function deleteTask(taskId) {
    const store = loadStore()
    ensureTaskExists(store.tasks, taskId)

    const removeIds = new Set([taskId])
    let changed = true
    while (changed) {
      changed = false
      store.tasks.forEach((task) => {
        if (task.parent_id != null && removeIds.has(task.parent_id) && !removeIds.has(task.id)) {
          removeIds.add(task.id)
          changed = true
        }
      })
    }

    store.tasks = store.tasks.filter((task) => !removeIds.has(task.id))
    saveStore(store)
    return { message: "deleted" }
  }

  function containsAnyKeyword(text, keywords) {
    return keywords.some((keyword) => text.includes(keyword))
  }

  function buildDecomposeTemplate(title, description) {
    const text = `${title} ${description}`.toLowerCase()

    if (containsAnyKeyword(text, ["开发", "实现", "编码", "代码", "接口", "页面", "功能", "bug", "测试", "前端", "后端"])) {
      return [
        {
          title: "确认需求与边界",
          description: `围绕“${title}”明确输入、输出、依赖和验收标准。`,
          estimated_minutes: 45,
        },
        {
          title: "完成核心实现",
          description: `先把“${title}”的主流程打通，再补齐关键细节。`,
          estimated_minutes: 90,
        },
        {
          title: "联调并验证关键场景",
          description: `检查“${title}”的正常流程、异常输入和边界情况。`,
          estimated_minutes: 60,
        },
        {
          title: "整理收尾与待优化项",
          description: `修正发现的问题，并记录“${title}”后续可继续优化的点。`,
          estimated_minutes: 30,
        },
      ]
    }

    if (containsAnyKeyword(text, ["写", "撰写", "报告", "汇报", "ppt", "文档", "方案", "总结", "简历", "邮件"])) {
      return [
        {
          title: "收集素材与关键信息",
          description: `为“${title}”整理背景资料、数据和需要表达的重点。`,
          estimated_minutes: 30,
        },
        {
          title: "搭建内容结构",
          description: `先列出“${title}”的大纲，确定开头、主体和结尾。`,
          estimated_minutes: 45,
        },
        {
          title: "完成主体内容",
          description: `根据大纲把“${title}”的核心内容完整写出来。`,
          estimated_minutes: 90,
        },
        {
          title: "校对润色并准备交付",
          description: `检查语句、格式和重点表达，确保“${title}”可以直接提交。`,
          estimated_minutes: 30,
        },
      ]
    }

    if (containsAnyKeyword(text, ["学习", "复习", "考试", "课程", "刷题", "练习", "阅读"])) {
      return [
        {
          title: "梳理学习目标与重点",
          description: `明确“${title}”这次要掌握的范围、章节或知识点。`,
          estimated_minutes: 30,
        },
        {
          title: "分块学习核心内容",
          description: `把“${title}”拆成几个知识块，先学习最关键的部分。`,
          estimated_minutes: 90,
        },
        {
          title: "做题或输出检验理解",
          description: `通过练习、复述或笔记确认“${title}”是否真正掌握。`,
          estimated_minutes: 60,
        },
        {
          title: "总结薄弱点并查漏补缺",
          description: `回顾“${title}”的易错点，整理下一轮需要补强的内容。`,
          estimated_minutes: 30,
        },
      ]
    }

    if (containsAnyKeyword(text, ["面试", "会议", "答辩", "演讲", "出行", "活动", "准备"])) {
      return [
        {
          title: "明确目标与结果",
          description: `先确认“${title}”要达到什么效果，输出形式是什么。`,
          estimated_minutes: 30,
        },
        {
          title: "准备资料与必需物品",
          description: `整理“${title}”需要的材料、文件、设备或人员信息。`,
          estimated_minutes: 45,
        },
        {
          title: "进行重点演练或执行",
          description: `把“${title}”里最关键的一段先跑通或先演练一遍。`,
          estimated_minutes: 60,
        },
        {
          title: "检查细节并完成收尾",
          description: `再次确认时间、顺序和注意事项，让“${title}”可以顺利落地。`,
          estimated_minutes: 30,
        },
      ]
    }

    return [
      {
        title: "明确目标与交付结果",
        description: `围绕“${title}”确认最终要完成什么，避免中途返工。`,
        estimated_minutes: 30,
      },
      {
        title: "准备资料与资源",
        description: `提前整理“${title}”所需的信息、工具和依赖项。`,
        estimated_minutes: 45,
      },
      {
        title: "执行核心工作",
        description: `集中时间推进“${title}”最关键的主体部分。`,
        estimated_minutes: 90,
      },
      {
        title: "检查结果并收尾",
        description: `复查“${title}”的完成质量，补上遗漏并整理下一步。`,
        estimated_minutes: 30,
      },
    ]
  }

  function decomposeTask(data) {
    const store = loadStore()
    const requestedTaskId = parseOptionalId(data.task_id, "task_id")
    let parentTask = null
    let title = String(data.title || "").trim()
    let description = String(data.description || "").trim()

    if (requestedTaskId != null) {
      parentTask = ensureTaskExists(store.tasks, requestedTaskId)
      title = parentTask.title
      description = parentTask.description || ""
    } else {
      if (!title) throw new LocalApiError("未提供 task_id 时，title 为必填项", 400)
      parentTask = insertTask(store, {
        title,
        description,
        priority: 3,
        status: "todo",
        parent_id: null,
        due_date: null,
        estimated_minutes: null,
        scheduled_start: null,
        scheduled_end: null,
      })
    }

    const subtasks = buildDecomposeTemplate(title, description).map((item) =>
      insertTask(store, {
        title: item.title,
        description: item.description,
        priority: 3,
        status: "todo",
        parent_id: parentTask.id,
        due_date: null,
        estimated_minutes: item.estimated_minutes,
        scheduled_start: null,
        scheduled_end: null,
      })
    )

    const nextStore = saveStore(store)
    return {
      subtasks: subtasks.map((task) => buildTaskResponse(nextStore.tasks, task)),
    }
  }

  function prioritizeTasksLocally(tasks) {
    return tasks
      .map((task) => {
        let priority = 2
        const reasons = []

        if (task.due_date) {
          const deltaHours = (new Date(task.due_date).getTime() - Date.now()) / 3600000
          if (deltaHours <= 24) {
            priority += 2
            reasons.push("截止时间很近")
          } else if (deltaHours <= 72) {
            priority += 1
            reasons.push("三天内需要完成")
          }
        }

        const text = `${task.title || ""} ${task.description || ""}`.toLowerCase()
        if (containsAnyKeyword(text, ["紧急", "马上", "立即", "今天", "截止", "客户", "汇报", "考试", "面试"])) {
          priority += 1
          reasons.push("任务描述包含紧急关键词")
        }

        const estimatedMinutes = safePositiveInt(task.estimated_minutes) || 60
        if (estimatedMinutes <= 30) {
          reasons.push("耗时较短，适合优先清理")
        } else if (estimatedMinutes >= 180) {
          priority -= 1
          reasons.push("耗时较长，建议预留完整时间段")
        }

        return {
          id: task.id,
          priority: clampPriority(priority),
          reason: reasons.length ? reasons.join("；") : "根据截止时间和任务信息综合判断。",
        }
      })
      .sort((a, b) => (b.priority - a.priority) || (a.id - b.id))
  }

  function prioritizeTasks(data) {
    const store = loadStore()
    const taskIds = parseTaskIds(data.task_ids)
    const taskSet = new Set(taskIds)
    const tasks = taskIds.length
      ? store.tasks.filter((task) => taskSet.has(task.id))
      : store.tasks.filter((task) => task.status !== "done")

    if (taskIds.length && !tasks.length) {
      throw new LocalApiError("未找到可分析的任务", 404)
    }

    const priorities = prioritizeTasksLocally(tasks)
    const updatedAt = new Date().toISOString()

    priorities.forEach((item) => {
      const task = store.tasks.find((row) => row.id === item.id)
      if (!task) return
      task.priority = item.priority
      task.updated_at = updatedAt
    })

    saveStore(store)
    return { priorities }
  }

  function normalizeAvailableSlots(slots) {
    if (!Array.isArray(slots)) return []
    return slots
      .map((slot) => {
        if (!slot || typeof slot !== "object") return null
        const start = safeIso(slot.start)
        const end = safeIso(slot.end)
        if (!start || !end) return null
        if (new Date(end).getTime() <= new Date(start).getTime()) return null
        return { start, end }
      })
      .filter(Boolean)
      .sort((a, b) => compareAsc(a.start, b.start))
  }

  function scheduleTasksLocally(tasks, availableSlots) {
    const slots = normalizeAvailableSlots(availableSlots).map((slot) => ({
      start: new Date(slot.start),
      end: new Date(slot.end),
    }))

    const sortedTasks = tasks.slice().sort((a, b) => {
      const priorityDiff = clampPriority(b.priority) - clampPriority(a.priority)
      if (priorityDiff) return priorityDiff
      const dueDiff = compareAsc(a.due_date, b.due_date)
      if (dueDiff) return dueDiff
      return (safePositiveInt(a.estimated_minutes) || 60) - (safePositiveInt(b.estimated_minutes) || 60)
    })

    return sortedTasks.map((task) => {
      const durationMinutes = safePositiveInt(task.estimated_minutes) || 60

      for (const slot of slots) {
        const remainingMinutes = Math.floor((slot.end.getTime() - slot.start.getTime()) / 60000)
        if (remainingMinutes < durationMinutes) continue

        const scheduledStart = new Date(slot.start)
        const scheduledEnd = new Date(slot.start.getTime() + durationMinutes * 60000)
        slot.start = scheduledEnd

        return {
          task_id: task.id,
          scheduled_start: scheduledStart.toISOString(),
          scheduled_end: scheduledEnd.toISOString(),
          status: "已安排",
        }
      }

      return {
        task_id: task.id,
        scheduled_start: "",
        scheduled_end: "",
        status: "未能安排",
        reason: "可用时间不足，已优先安排更高优先级任务。",
      }
    })
  }

  function scheduleTasks(data) {
    const taskIds = parseTaskIds(data.task_ids)
    const availableSlots = data.available_slots
    if (!taskIds.length) throw new LocalApiError("task_ids 为必填项", 400)
    if (!Array.isArray(availableSlots) || !availableSlots.length) {
      throw new LocalApiError("available_slots 为必填项，且必须是非空数组", 400)
    }

    const store = loadStore()
    const taskSet = new Set(taskIds)
    const tasks = store.tasks.filter((task) => taskSet.has(task.id))
    if (!tasks.length) throw new LocalApiError("未找到可规划的任务", 404)

    const schedule = scheduleTasksLocally(tasks, availableSlots)
    const updatedAt = new Date().toISOString()

    schedule.forEach((item) => {
      const task = store.tasks.find((row) => row.id === item.task_id)
      if (!task) return
      task.scheduled_start = item.scheduled_start || null
      task.scheduled_end = item.scheduled_end || null
      task.updated_at = updatedAt
    })

    saveStore(store)
    return { schedule }
  }

  function supports(url) {
    const path = new URL(url, window.location.origin).pathname
    return SUPPORTED_ROUTES.some((pattern) => pattern.test(path))
  }

  async function handle(url, options = {}) {
    const requestUrl = new URL(url, window.location.origin)
    const path = requestUrl.pathname
    const method = String(options.method || "GET").toUpperCase()
    const taskMatch = path.match(/^\/api\/tasks\/(\d+)$/)

    if (path === "/api/tasks" && method === "GET") {
      return listTasks(requestUrl.searchParams)
    }

    if (path === "/api/tasks" && method === "POST") {
      return createTask(parseBody(options))
    }

    if (taskMatch && method === "PUT") {
      return updateTask(Number(taskMatch[1]), parseBody(options))
    }

    if (taskMatch && method === "DELETE") {
      return deleteTask(Number(taskMatch[1]))
    }

    if (path === "/api/timeline" && method === "GET") {
      return listTimeline()
    }

    if (path === "/api/ai/decompose" && method === "POST") {
      return decomposeTask(parseBody(options))
    }

    if (path === "/api/ai/prioritize" && method === "POST") {
      return prioritizeTasks(parseBody(options))
    }

    if (path === "/api/ai/schedule" && method === "POST") {
      return scheduleTasks(parseBody(options))
    }

    throw new LocalApiError("本地存储模式暂不支持该请求", 404)
  }

  window.TimeManagerLocalApi = {
    mode: "local",
    supports,
    handle,
  }
})()
