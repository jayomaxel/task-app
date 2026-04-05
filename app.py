import atexit
import os
from contextlib import contextmanager
from datetime import date, datetime
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from psycopg2 import extras
from psycopg2.pool import ThreadedConnectionPool

from ai_service import decompose_task, prioritize_tasks as ai_prioritize_tasks
from ai_service import schedule_tasks as ai_schedule_tasks

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
VALID_STATUSES = {"todo", "doing", "done"}
SORT_OPTIONS = {
    "priority": "t.priority DESC NULLS LAST, t.created_at DESC",
    "due_date": "t.due_date ASC NULLS LAST, t.created_at DESC",
    "scheduled_start": "t.scheduled_start ASC NULLS LAST, t.created_at DESC",
    "created_at": "t.created_at DESC",
}
TASK_SELECT_SQL = """
SELECT
    t.id,
    t.title,
    t.description,
    t.priority,
    t.status,
    t.parent_id,
    t.due_date,
    t.estimated_minutes,
    t.scheduled_start,
    t.scheduled_end,
    t.created_at,
    t.updated_at,
    (
        SELECT COUNT(*)
        FROM tasks child
        WHERE child.parent_id = t.id
    ) AS subtask_count
FROM tasks t
"""

DB_POOL: Optional[ThreadedConnectionPool] = None
DB_POOL_LOCK = Lock()

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.json.ensure_ascii = False


class APIError(Exception):
    """统一的 API 异常类型。"""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class BadRequestError(APIError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 400)


class NotFoundError(APIError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 404)


class ServiceUnavailableError(APIError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 503)


def get_db_pool() -> ThreadedConnectionPool:
    """懒加载数据库连接池，避免导入模块时就强依赖数据库在线。"""
    global DB_POOL

    if DB_POOL is not None:
        return DB_POOL

    with DB_POOL_LOCK:
        if DB_POOL is not None:
            return DB_POOL

        if not DATABASE_URL:
            raise ServiceUnavailableError("DATABASE_URL 未配置")

        try:
            pool = ThreadedConnectionPool(minconn=1, maxconn=5, dsn=DATABASE_URL)
            _init_db_schema(pool)
            DB_POOL = pool
            return DB_POOL
        except APIError:
            raise
        except Exception as exc:
            raise ServiceUnavailableError(f"数据库连接不可用: {exc}") from exc


def _init_db_schema(pool: ThreadedConnectionPool) -> None:
    """初始化任务表，方便当前阶段直接启动。"""
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
                    status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'doing', 'done')),
                    parent_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
                    due_date TIMESTAMPTZ NULL,
                    estimated_minutes INTEGER NULL CHECK (estimated_minutes IS NULL OR estimated_minutes > 0),
                    scheduled_start TIMESTAMPTZ NULL,
                    scheduled_end TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_parent_id ON tasks(parent_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_scheduled_start ON tasks(scheduled_start)")
        conn.commit()
    except Exception as exc:
        conn.rollback()
        try:
            pool.closeall()
        except Exception:
            pass
        raise ServiceUnavailableError(f"初始化数据库表失败: {exc}") from exc
    finally:
        pool.putconn(conn)


@contextmanager
def get_db_connection():
    """统一封装连接获取和归还，确保 finally 中释放连接。"""
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def close_db_pool() -> None:
    """进程退出时关闭连接池。"""
    global DB_POOL
    if DB_POOL is not None:
        try:
            DB_POOL.closeall()
        finally:
            DB_POOL = None


atexit.register(close_db_pool)


def get_json_data() -> Dict[str, Any]:
    """安全读取 JSON 请求体。"""
    if not request.is_json:
        raise BadRequestError("请求体必须是 JSON")

    data = request.get_json(silent=True)
    if data is None:
        raise BadRequestError("JSON 格式无效")
    if not isinstance(data, dict):
        raise BadRequestError("JSON 请求体必须是对象")
    return data


def serialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """把数据库返回值转换成可 JSON 序列化的字典。"""
    result: Dict[str, Any] = {}
    for key, value in dict(row).items():
        if isinstance(value, (datetime, date)):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def build_task_response(row: Dict[str, Any]) -> Dict[str, Any]:
    """标准化单个任务对象。"""
    task = serialize_row(row)
    task["subtask_count"] = int(task.get("subtask_count") or 0)
    return task


def parse_status(value: Any, *, required: bool = False, default: Optional[str] = None) -> Optional[str]:
    """校验任务状态。"""
    if value is None:
        if required and default is None:
            raise BadRequestError("status 不能为空")
        return default

    status = str(value).strip().lower()
    if not status:
        if required and default is None:
            raise BadRequestError("status 不能为空")
        return default
    if status not in VALID_STATUSES:
        raise BadRequestError("status 只能是 todo / doing / done")
    return status


def parse_priority(value: Any, *, default: Optional[int] = None) -> Optional[int]:
    """校验优先级。"""
    if value is None or value == "":
        return default
    try:
        priority = int(value)
    except (TypeError, ValueError) as exc:
        raise BadRequestError("priority 必须是整数") from exc
    if priority < 1 or priority > 5:
        raise BadRequestError("priority 必须在 1 到 5 之间")
    return priority


def parse_estimated_minutes(value: Any, *, default: Optional[int] = None) -> Optional[int]:
    """校验预估耗时。"""
    if value is None or value == "":
        return default
    try:
        minutes = int(value)
    except (TypeError, ValueError) as exc:
        raise BadRequestError("estimated_minutes 必须是整数") from exc
    if minutes <= 0:
        raise BadRequestError("estimated_minutes 必须大于 0")
    return minutes


def parse_optional_int(value: Any, field_name: str) -> Optional[int]:
    """校验可空整数字段。"""
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() == "null":
        return None
    if value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BadRequestError(f"{field_name} 必须是整数或 null") from exc


def parse_optional_datetime(value: Any, field_name: str) -> Optional[datetime]:
    """校验 ISO 时间字符串。"""
    if value is None or value == "":
        return None

    text = str(value).strip()
    if text.lower() == "null":
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise BadRequestError(f"{field_name} 必须是合法的 ISO 时间字符串") from exc


def parse_task_ids(value: Any) -> List[int]:
    """校验任务 ID 列表。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise BadRequestError("task_ids 必须是数组")

    task_ids: List[int] = []
    for item in value:
        try:
            task_ids.append(int(item))
        except (TypeError, ValueError) as exc:
            raise BadRequestError("task_ids 中的每一项都必须是整数") from exc
    return task_ids


def ensure_parent_exists(conn, parent_id: Optional[int]) -> None:
    """校验母任务是否存在。"""
    if parent_id is None:
        return

    with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
        cur.execute("SELECT id FROM tasks WHERE id = %s", (parent_id,))
        if cur.fetchone() is None:
            raise NotFoundError(f"母任务不存在: {parent_id}")


def fetch_task_by_id(conn, task_id: int) -> Dict[str, Any]:
    """读取单个任务及子任务数量。"""
    with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
        cur.execute(f"{TASK_SELECT_SQL} WHERE t.id = %s", (task_id,))
        row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"任务不存在: {task_id}")
    return build_task_response(row)


def fetch_tasks_for_ai(conn, task_ids: Sequence[int], *, allow_all_undone: bool = False) -> List[Dict[str, Any]]:
    """读取 AI 所需任务字段。"""
    where_clauses: List[str] = []
    params: List[Any] = []

    if task_ids:
        where_clauses.append("t.id = ANY(%s)")
        params.append(list(task_ids))
    elif allow_all_undone:
        where_clauses.append("t.status <> 'done'")
    else:
        raise BadRequestError("task_ids 不能为空")

    query = """
    SELECT
        t.id,
        t.title,
        t.description,
        t.priority,
        t.status,
        t.parent_id,
        t.due_date,
        t.estimated_minutes,
        t.scheduled_start,
        t.scheduled_end,
        t.created_at,
        t.updated_at
    FROM tasks t
    """
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    query += " ORDER BY t.created_at DESC"

    with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    tasks = [serialize_row(row) for row in rows]
    if task_ids and not tasks:
        raise NotFoundError("未找到指定任务")
    return tasks


@app.errorhandler(APIError)
def handle_api_error(error: APIError):
    return jsonify({"error": error.message}), error.status_code


@app.errorhandler(404)
def handle_route_not_found(_error):
    return jsonify({"error": "接口不存在"}), 404


@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    print(f"[ERROR] {error}")
    return jsonify({"error": "服务暂时不可用"}), 503


@app.route("/")
def index():
    """首页返回静态页面。"""
    try:
        return send_from_directory(app.static_folder, "index.html")
    except FileNotFoundError as exc:
        raise NotFoundError("static/index.html 不存在") from exc


@app.get("/api/tasks")
def get_tasks():
    """查询任务列表。"""
    status = request.args.get("status")
    parent_id_raw = request.args.get("parent_id")
    sort_key = request.args.get("sort", "created_at").strip() or "created_at"

    if sort_key not in SORT_OPTIONS:
        raise BadRequestError("sort 只能是 priority / due_date / scheduled_start / created_at")

    where_clauses: List[str] = []
    params: List[Any] = []

    if status:
        where_clauses.append("t.status = %s")
        params.append(parse_status(status, required=True))

    if parent_id_raw is not None:
        if parent_id_raw.strip().lower() == "null":
            where_clauses.append("t.parent_id IS NULL")
        else:
            parent_id = parse_optional_int(parent_id_raw, "parent_id")
            if parent_id is None:
                where_clauses.append("t.parent_id IS NULL")
            else:
                where_clauses.append("t.parent_id = %s")
                params.append(parent_id)

    query = TASK_SELECT_SQL
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    query += f" ORDER BY {SORT_OPTIONS[sort_key]}"

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    return jsonify({"tasks": [build_task_response(row) for row in rows]})


@app.post("/api/tasks")
def create_task():
    """创建任务。"""
    data = get_json_data()
    title = str(data.get("title") or "").strip()
    if not title:
        raise BadRequestError("title 为必填项")

    description = str(data.get("description") or "").strip()
    priority = parse_priority(data.get("priority"), default=3)
    status = parse_status(data.get("status"), default="todo")
    parent_id = parse_optional_int(data.get("parent_id"), "parent_id")
    due_date = parse_optional_datetime(data.get("due_date"), "due_date")
    estimated_minutes = parse_estimated_minutes(data.get("estimated_minutes"))

    with get_db_connection() as conn:
        ensure_parent_exists(conn, parent_id)

        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO tasks (
                    title,
                    description,
                    priority,
                    status,
                    parent_id,
                    due_date,
                    estimated_minutes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    title,
                    description,
                    priority,
                    status,
                    parent_id,
                    due_date,
                    estimated_minutes,
                ),
            )
            task_id = int(cur.fetchone()["id"])

        task = fetch_task_by_id(conn, task_id)

    return jsonify(task), 201


@app.put("/api/tasks/<int:task_id>")
def update_task(task_id: int):
    """更新任务。"""
    data = get_json_data()
    if not data:
        raise BadRequestError("请求体不能为空")

    allowed_fields = {
        "title",
        "description",
        "priority",
        "status",
        "parent_id",
        "due_date",
        "estimated_minutes",
        "scheduled_start",
        "scheduled_end",
    }
    unknown_fields = [key for key in data if key not in allowed_fields]
    if unknown_fields:
        raise BadRequestError(f"不支持更新的字段: {', '.join(unknown_fields)}")

    updates: Dict[str, Any] = {}

    if "title" in data:
        title = str(data.get("title") or "").strip()
        if not title:
            raise BadRequestError("title 不能为空")
        updates["title"] = title
    if "description" in data:
        updates["description"] = str(data.get("description") or "").strip()
    if "priority" in data:
        updates["priority"] = parse_priority(data.get("priority"))
    if "status" in data:
        updates["status"] = parse_status(data.get("status"), required=True)
    if "parent_id" in data:
        parent_id = parse_optional_int(data.get("parent_id"), "parent_id")
        if parent_id == task_id:
            raise BadRequestError("parent_id 不能等于当前任务 id")
        updates["parent_id"] = parent_id
    if "due_date" in data:
        updates["due_date"] = parse_optional_datetime(data.get("due_date"), "due_date")
    if "estimated_minutes" in data:
        updates["estimated_minutes"] = parse_estimated_minutes(data.get("estimated_minutes"))
    if "scheduled_start" in data:
        updates["scheduled_start"] = parse_optional_datetime(data.get("scheduled_start"), "scheduled_start")
    if "scheduled_end" in data:
        updates["scheduled_end"] = parse_optional_datetime(data.get("scheduled_end"), "scheduled_end")

    if not updates:
        raise BadRequestError("没有可更新的字段")

    with get_db_connection() as conn:
        fetch_task_by_id(conn, task_id)
        ensure_parent_exists(conn, updates.get("parent_id"))

        set_clauses: List[str] = []
        params: List[Any] = []
        for field_name, value in updates.items():
            set_clauses.append(f"{field_name} = %s")
            params.append(value)
        set_clauses.append("updated_at = NOW()")
        params.append(task_id)

        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE tasks
                SET {", ".join(set_clauses)}
                WHERE id = %s
                RETURNING id
                """,
                params,
            )
            updated = cur.fetchone()

        if updated is None:
            raise NotFoundError(f"任务不存在: {task_id}")

        task = fetch_task_by_id(conn, task_id)

    return jsonify(task)


@app.delete("/api/tasks/<int:task_id>")
def delete_task(task_id: int):
    """删除任务。"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            if cur.rowcount == 0:
                raise NotFoundError(f"任务不存在: {task_id}")

    return jsonify({"message": "deleted"})


@app.post("/api/ai/decompose")
def ai_decompose():
    """AI 拆解任务并写入子任务。"""
    data = get_json_data()
    task_id = parse_optional_int(data.get("task_id"), "task_id")
    title = str(data.get("title") or "").strip()
    description = str(data.get("description") or "").strip()

    if task_id is not None:
        with get_db_connection() as conn:
            parent_task = fetch_task_by_id(conn, task_id)
        source_title = parent_task["title"]
        source_description = parent_task.get("description") or ""
        parent_task_id: Optional[int] = task_id
    else:
        if not title:
            raise BadRequestError("未提供 task_id 时，title 为必填项")
        source_title = title
        source_description = description
        parent_task_id = None

    subtasks = decompose_task(source_title, source_description)
    if not subtasks:
        raise ServiceUnavailableError("AI 未返回可用的子任务")

    created_subtasks: List[Dict[str, Any]] = []

    with get_db_connection() as conn:
        if parent_task_id is None:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO tasks (title, description, priority, status)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (source_title, source_description, 3, "todo"),
                )
                parent_task_id = int(cur.fetchone()["id"])

        for item in subtasks:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO tasks (
                        title,
                        description,
                        priority,
                        status,
                        parent_id,
                        estimated_minutes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        item["title"],
                        item.get("description") or "",
                        3,
                        "todo",
                        parent_task_id,
                        item.get("estimated_minutes"),
                    ),
                )
                new_id = int(cur.fetchone()["id"])
            created_subtasks.append(fetch_task_by_id(conn, new_id))

    return jsonify({"subtasks": created_subtasks}), 201


@app.post("/api/ai/prioritize")
def ai_prioritize():
    """AI 分析任务优先级并回写数据库。"""
    data = get_json_data()
    task_ids = parse_task_ids(data.get("task_ids"))

    with get_db_connection() as conn:
        tasks = fetch_tasks_for_ai(conn, task_ids, allow_all_undone=True)
        if not tasks:
            return jsonify({"priorities": []})

    priorities = ai_prioritize_tasks(tasks)
    if not priorities:
        raise ServiceUnavailableError("AI 未返回优先级结果")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for item in priorities:
                cur.execute(
                    """
                    UPDATE tasks
                    SET priority = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (item["priority"], item["id"]),
                )

    return jsonify({"priorities": priorities})


@app.post("/api/ai/schedule")
def ai_schedule():
    """AI 规划日程并写入 scheduled_start / scheduled_end。"""
    data = get_json_data()
    task_ids = parse_task_ids(data.get("task_ids"))
    available_slots = data.get("available_slots")

    if not task_ids:
        raise BadRequestError("task_ids 为必填项")
    if not isinstance(available_slots, list) or not available_slots:
        raise BadRequestError("available_slots 为必填项，且必须是非空数组")

    with get_db_connection() as conn:
        tasks = fetch_tasks_for_ai(conn, task_ids, allow_all_undone=False)
        if not tasks:
            raise NotFoundError("未找到可规划的任务")

    schedule = ai_schedule_tasks(tasks, available_slots)
    if not schedule:
        raise ServiceUnavailableError("AI 未返回日程规划结果")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for item in schedule:
                scheduled_start = parse_optional_datetime(item.get("scheduled_start"), "scheduled_start")
                scheduled_end = parse_optional_datetime(item.get("scheduled_end"), "scheduled_end")
                cur.execute(
                    """
                    UPDATE tasks
                    SET scheduled_start = %s,
                        scheduled_end = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (scheduled_start, scheduled_end, item["task_id"]),
                )

    return jsonify({"schedule": schedule})


@app.get("/api/timeline")
def get_timeline():
    """查询时间轴数据。"""
    query = (
        TASK_SELECT_SQL
        + """
        WHERE t.status <> 'done'
          AND (t.due_date IS NOT NULL OR t.scheduled_start IS NOT NULL)
        ORDER BY COALESCE(t.scheduled_start, t.due_date) ASC, t.created_at ASC
        """
    )

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(query)
            rows = cur.fetchall()

    return jsonify({"timeline": [build_task_response(row) for row in rows]})


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("APP_ENV", "development").lower() == "development",
    )
