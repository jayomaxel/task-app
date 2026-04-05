import json
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from openai import OpenAI

__all__ = ["get_client", "decompose_task", "prioritize_tasks", "schedule_tasks"]


def get_client(use_smart: bool = False) -> Tuple[OpenAI, str]:
    """
    AI provider 工厂函数。
    根据环境变量 AI_PROVIDER 返回 (client, model_name)。
    use_smart=True 时用智能模型（优先级分析/日程规划），False 用快速模型（任务拆解）。
    支持：siliconflow / openai / claude / github
    """
    provider = os.getenv("AI_PROVIDER", "siliconflow").lower()

    if provider == "siliconflow":
        api_key = os.getenv("SILICONFLOW_API_KEY")
        base_url = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
        model = os.getenv(
            "SF_MODEL_SMART" if use_smart else "SF_MODEL_FAST",
            "deepseek-ai/DeepSeek-V3" if use_smart else "Qwen/Qwen3-8B",
        )
    elif provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv(
            "OAI_MODEL_SMART" if use_smart else "OAI_MODEL_FAST",
            "gpt-4o" if use_smart else "gpt-4o-mini",
        )
    elif provider == "claude":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        base_url = os.getenv("CLAUDE_BASE_URL", "https://api.anthropic.com/v1")
        model = os.getenv(
            "CLAUDE_MODEL_SMART" if use_smart else "CLAUDE_MODEL_FAST",
            "claude-sonnet-4-6" if use_smart else "claude-haiku-4-5-20251001",
        )
    elif provider == "github":
        api_key = os.getenv("GITHUB_TOKEN")
        base_url = os.getenv("GITHUB_BASE_URL", "https://models.github.ai/inference")
        model = os.getenv(
            "GITHUB_MODEL_SMART" if use_smart else "GITHUB_MODEL_FAST",
            "openai/gpt-4o" if use_smart else "openai/gpt-4o-mini",
        )
    else:
        raise ValueError(
            f"未知 AI_PROVIDER: {provider}，可选：siliconflow / openai / claude / github"
        )

    if not api_key:
        raise ValueError(f"{provider} 的 API Key 未配置，请检查 .env")

    client = OpenAI(api_key=api_key, base_url=base_url)
    print(f"[AI] provider={provider} model={model} smart={use_smart}")
    return client, model


def decompose_task(title: str, description: str = "") -> List[Dict[str, Any]]:
    # 当前 provider 由 AI_PROVIDER 决定；这里使用快速模型做任务拆解，优先省 token。
    title = (title or "").strip()
    description = (description or "").strip()
    if not title:
        return []

    system_prompt = (
        "你是一个中文任务拆解助手。"
        "你需要把一个较大的任务拆成 3 到 6 个可执行子任务。"
        "每个子任务的预计耗时必须在 30 到 120 分钟之间。"
        "你只能返回 JSON，不要输出解释、Markdown 或代码块。"
    )
    user_prompt = f"""
请将下面的任务拆解为 3-6 个子任务。

任务标题：
{title}

任务描述：
{description or "无"}

严格返回以下 JSON：
{{
  "subtasks": [
    {{
      "title": "子任务标题",
      "description": "子任务说明",
      "estimated_minutes": 60
    }}
  ]
}}

要求：
1. 只返回 JSON。
2. 子任务必须可执行、具体。
3. 每个 estimated_minutes 必须是整数。
4. 每个子任务耗时必须在 30 到 120 分钟之间。
""".strip()

    try:
        payload = _call_llm_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            use_smart=False,
            max_tokens=1200,
            expected_key="subtasks",
        )
        subtasks = _normalize_subtasks(payload)
        if subtasks:
            return subtasks
    except Exception as exc:
        print(f"[AI] decompose_task 调用失败: {exc}")

    return []


def prioritize_tasks(tasks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # 当前 provider 由 AI_PROVIDER 决定；这里使用智能模型做优先级分析，提高判断质量。
    normalized_tasks = _normalize_priority_input(tasks)
    if not normalized_tasks:
        return []

    system_prompt = (
        "你是一个中文时间管理助理。"
        "你需要根据截止日期紧迫性、任务关键词、预计耗时综合判断优先级。"
        "priority 必须是 1 到 5 的整数，5 表示最高优先级。"
        "你只能返回 JSON。"
    )
    user_prompt = f"""
请分析下面任务的优先级。

任务列表：
{json.dumps(normalized_tasks, ensure_ascii=False, indent=2)}

严格返回以下 JSON：
{{
  "priorities": [
    {{
      "id": 1,
      "priority": 5,
      "reason": "今天截止"
    }}
  ]
}}

要求：
1. priority 只能是 1-5 的整数。
2. 综合考虑 due_date、关键词、estimated_minutes。
3. 保留所有任务，不要漏掉。
4. 只返回 JSON。
""".strip()

    try:
        payload = _call_llm_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            use_smart=True,
            max_tokens=1400,
            expected_key="priorities",
        )
        priorities = _normalize_priorities(payload, normalized_tasks)
        if priorities:
            return priorities
    except Exception as exc:
        print(f"[AI] prioritize_tasks 调用失败，改用本地兜底: {exc}")

    return _local_prioritize_tasks(normalized_tasks)


def schedule_tasks(
    tasks: Sequence[Dict[str, Any]],
    available_slots: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    # 当前 provider 由 AI_PROVIDER 决定；这里使用智能模型做日程规划，兼顾优先级和截止日期。
    normalized_tasks = _normalize_schedule_tasks(tasks)
    normalized_slots = _normalize_available_slots(available_slots)
    if not normalized_tasks:
        return []
    if not normalized_slots:
        return _local_schedule_tasks(normalized_tasks, [])

    system_prompt = (
        "你是一个中文日程规划助理。"
        "你需要根据任务优先级、截止日期和可用时间段安排任务。"
        "时间不够时优先安排高优先级任务，低优先级任务标注未能安排。"
        "你只能返回 JSON。"
    )
    user_prompt = f"""
请根据任务列表和可用时间段生成日程。

任务列表：
{json.dumps(normalized_tasks, ensure_ascii=False, indent=2)}

可用时间段：
{json.dumps(normalized_slots, ensure_ascii=False, indent=2)}

严格返回以下 JSON：
{{
  "schedule": [
    {{
      "task_id": 1,
      "scheduled_start": "2026-04-05T09:00:00+08:00",
      "scheduled_end": "2026-04-05T10:00:00+08:00"
    }}
  ],
  "unscheduled": [
    {{
      "task_id": 2,
      "reason": "未能安排"
    }}
  ]
}}

要求：
1. 优先安排高优先级、截止更近的任务。
2. 不能超出 available_slots 的 start/end 范围。
3. estimated_minutes 与实际安排时长尽量一致。
4. 如果安排不下，放到 unscheduled 中并说明原因。
5. 只返回 JSON。
""".strip()

    try:
        payload = _call_llm_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            use_smart=True,
            max_tokens=1800,
            expected_key="schedule",
        )
        schedule = _normalize_schedule(payload, normalized_tasks)
        if schedule:
            return schedule
    except Exception as exc:
        print(f"[AI] schedule_tasks 调用失败，改用本地兜底: {exc}")

    return _local_schedule_tasks(normalized_tasks, normalized_slots)


def _call_llm_json(
    system_prompt: str,
    user_prompt: str,
    use_smart: bool,
    max_tokens: int,
    expected_key: Optional[str] = None,
) -> Dict[str, Any]:
    last_error: Optional[Exception] = None

    for attempt in range(2):
        try:
            client, model = get_client(use_smart=use_smart)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=max_tokens,
                timeout=30,
            )
            content = _extract_message_content(response)
            parsed = _parse_json_content(content, expected_key=expected_key)
            if not isinstance(parsed, dict):
                raise ValueError(f"AI 返回的不是 JSON 对象: {content}")
            return parsed
        except Exception as exc:
            last_error = exc
            if _is_rate_limit_error(exc) and attempt == 0:
                print("[AI] 遇到 429 限流，等待 5 秒后重试一次")
                time.sleep(5)
                continue
            raise

    raise last_error or RuntimeError("AI 调用失败")


def _is_rate_limit_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True

    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if response_status == 429:
        return True

    return "429" in str(exc)


def _extract_message_content(response: Any) -> str:
    if not getattr(response, "choices", None):
        raise ValueError("AI 响应为空")

    message = response.choices[0].message
    content = getattr(message, "content", "")

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts).strip()

    return str(content).strip()


def _parse_json_content(content: str, expected_key: Optional[str] = None) -> Any:
    cleaned = (content or "").strip()
    if not cleaned:
        raise ValueError("AI 返回内容为空")

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    fenced_match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        fenced_content = fenced_match.group(1).strip()
        try:
            return json.loads(fenced_content)
        except json.JSONDecodeError:
            cleaned = fenced_content

    match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    regex_fallback = _regex_payload_fallback(cleaned, expected_key)
    if regex_fallback is not None:
        return regex_fallback

    raise ValueError(f"JSON 解析失败: {content}")


def _regex_payload_fallback(content: str, expected_key: Optional[str]) -> Optional[Dict[str, Any]]:
    if expected_key == "subtasks":
        subtasks = _fallback_subtasks_by_regex(content)
        return {"subtasks": subtasks} if subtasks else None

    if expected_key == "priorities":
        priorities = _fallback_priorities_by_regex(content, [])
        return {"priorities": priorities} if priorities else None

    if expected_key == "schedule":
        schedule = _fallback_schedule_entries_by_regex(content)
        return {"schedule": schedule} if schedule else None

    return None


def _normalize_subtasks(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    subtasks = payload.get("subtasks")
    if not isinstance(subtasks, list):
        return _fallback_subtasks_by_regex(json.dumps(payload, ensure_ascii=False))

    normalized: List[Dict[str, Any]] = []
    for item in subtasks:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        if not title:
            continue
        normalized.append(
            {
                "title": title,
                "description": description,
                "estimated_minutes": _clamp_minutes(item.get("estimated_minutes"), 60),
            }
        )

    return normalized[:6]


def _fallback_subtasks_by_regex(content: str) -> List[Dict[str, Any]]:
    pattern = re.compile(
        r'"title"\s*:\s*"(?P<title>[^"]+)"'
        r'.*?"description"\s*:\s*"(?P<description>[^"]*)"'
        r'.*?"estimated_minutes"\s*:\s*(?P<estimated_minutes>\d+)',
        re.DOTALL,
    )
    matches = pattern.finditer(content or "")
    results: List[Dict[str, Any]] = []

    for match in matches:
        results.append(
            {
                "title": match.group("title").strip(),
                "description": match.group("description").strip(),
                "estimated_minutes": _clamp_minutes(match.group("estimated_minutes"), 60),
            }
        )

    return results[:6]


def _normalize_priority_input(tasks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []

    for item in tasks:
        if not isinstance(item, dict):
            continue

        task_id = item.get("id")
        title = str(item.get("title") or "").strip()
        if task_id is None or not title:
            continue

        normalized.append(
            {
                "id": task_id,
                "title": title,
                "description": str(item.get("description") or "").strip(),
                "due_date": str(item.get("due_date") or "").strip(),
                "estimated_minutes": _safe_int(item.get("estimated_minutes"), 60),
            }
        )

    return normalized


def _normalize_priorities(
    payload: Dict[str, Any],
    original_tasks: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    priorities = payload.get("priorities")
    if not isinstance(priorities, list):
        return _fallback_priorities_by_regex(json.dumps(payload, ensure_ascii=False), original_tasks)

    original_map = {str(task["id"]): task for task in original_tasks}
    normalized: List[Dict[str, Any]] = []

    for item in priorities:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("id"))
        if task_id not in original_map:
            continue
        normalized.append(
            {
                "id": original_map[task_id]["id"],
                "priority": _clamp_priority(item.get("priority")),
                "reason": str(item.get("reason") or "").strip() or "模型未说明原因。",
            }
        )

    if len(normalized) < len(original_tasks):
        returned_ids = {str(item["id"]) for item in normalized}
        fallback_map = {str(item["id"]): item for item in _local_prioritize_tasks(original_tasks)}
        for task in original_tasks:
            task_id = str(task["id"])
            if task_id in returned_ids:
                continue
            fallback_item = fallback_map.get(task_id)
            if fallback_item:
                normalized.append(fallback_item)

    normalized.sort(key=lambda item: (-item["priority"], str(item["id"])))
    return normalized


def _fallback_priorities_by_regex(
    content: str,
    original_tasks: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    pattern = re.compile(
        r'"id"\s*:\s*"?(?P<id>[^",}\s]+)"?'
        r'.*?"priority"\s*:\s*(?P<priority>\d+)'
        r'.*?"reason"\s*:\s*"(?P<reason>[^"]*)"',
        re.DOTALL,
    )
    results: List[Dict[str, Any]] = []
    original_map = {str(task["id"]): task for task in original_tasks}

    for match in pattern.finditer(content or ""):
        task_id = match.group("id").strip()
        if task_id not in original_map:
            continue
        results.append(
            {
                "id": original_map[task_id]["id"],
                "priority": _clamp_priority(match.group("priority")),
                "reason": match.group("reason").strip() or "正则回退解析结果。",
            }
        )

    if results:
        return results
    if original_tasks:
        return _local_prioritize_tasks(original_tasks)
    return []


def _local_prioritize_tasks(tasks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    for task in tasks:
        priority = 2
        reasons: List[str] = []

        due_date = _parse_iso_datetime(task.get("due_date"))
        if due_date:
            delta_hours = (due_date - datetime.now(due_date.tzinfo)).total_seconds() / 3600
            if delta_hours <= 24:
                priority += 2
                reasons.append("截止时间很近")
            elif delta_hours <= 72:
                priority += 1
                reasons.append("近三天内截止")

        text = f"{task.get('title', '')} {task.get('description', '')}".lower()
        if any(word in text for word in ["紧急", "马上", "立即", "今天", "截止", "客户", "汇报", "考试", "面试"]):
            priority += 1
            reasons.append("任务关键词显示紧迫")

        estimated_minutes = _safe_int(task.get("estimated_minutes"), 60)
        if estimated_minutes <= 30:
            reasons.append("耗时较短，适合优先清理")
        elif estimated_minutes >= 180:
            priority -= 1
            reasons.append("耗时较长，执行成本较高")

        results.append(
            {
                "id": task["id"],
                "priority": _clamp_priority(priority),
                "reason": "，".join(reasons) if reasons else "根据截止日期和任务信息综合判断。",
            }
        )

    results.sort(key=lambda item: (-item["priority"], str(item["id"])))
    return results


def _normalize_schedule_tasks(tasks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    priority_map = {str(item["id"]): item for item in _local_prioritize_tasks(_normalize_priority_input(tasks))}
    normalized: List[Dict[str, Any]] = []

    for item in tasks:
        if not isinstance(item, dict):
            continue

        task_id = item.get("id")
        title = str(item.get("title") or "").strip()
        if task_id is None or not title:
            continue

        priority_value = item.get("priority")
        if priority_value is None:
            priority_value = priority_map.get(str(task_id), {}).get("priority", 3)

        normalized.append(
            {
                "id": task_id,
                "title": title,
                "description": str(item.get("description") or "").strip(),
                "due_date": str(item.get("due_date") or "").strip(),
                "estimated_minutes": max(1, _safe_int(item.get("estimated_minutes"), 60)),
                "priority": _clamp_priority(priority_value),
            }
        )

    return normalized


def _normalize_available_slots(available_slots: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []

    for item in available_slots:
        if not isinstance(item, dict):
            continue

        start = str(item.get("start") or "").strip()
        end = str(item.get("end") or "").strip()
        start_dt = _parse_iso_datetime(start)
        end_dt = _parse_iso_datetime(end)
        if not start_dt or not end_dt or end_dt <= start_dt:
            continue

        normalized.append(
            {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
            }
        )

    normalized.sort(key=lambda item: item["start"])
    return normalized


def _normalize_schedule(
    payload: Dict[str, Any],
    original_tasks: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    schedule = payload.get("schedule")
    if not isinstance(schedule, list):
        return _fallback_schedule_by_regex(json.dumps(payload, ensure_ascii=False), original_tasks)

    task_map = {str(task["id"]): task for task in original_tasks}
    normalized: List[Dict[str, Any]] = []

    for item in schedule:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id"))
        if task_id not in task_map:
            continue

        start = str(item.get("scheduled_start") or "").strip()
        end = str(item.get("scheduled_end") or "").strip()
        if not _parse_iso_datetime(start) or not _parse_iso_datetime(end):
            continue

        normalized.append(
            {
                "task_id": task_map[task_id]["id"],
                "scheduled_start": start,
                "scheduled_end": end,
                "status": "已安排",
            }
        )

    unscheduled = payload.get("unscheduled") or []
    if isinstance(unscheduled, list):
        for item in unscheduled:
            if not isinstance(item, dict):
                continue
            task_id = str(item.get("task_id"))
            if task_id not in task_map:
                continue
            normalized.append(
                {
                    "task_id": task_map[task_id]["id"],
                    "scheduled_start": "",
                    "scheduled_end": "",
                    "status": "未能安排",
                    "reason": str(item.get("reason") or "未能安排").strip(),
                }
            )

    scheduled_ids = {str(item["task_id"]) for item in normalized}
    if len(scheduled_ids) < len(original_tasks):
        fallback_map = {str(item["task_id"]): item for item in _local_schedule_tasks(original_tasks, [])}
        for task in original_tasks:
            task_id = str(task["id"])
            if task_id in scheduled_ids:
                continue
            fallback_item = fallback_map.get(task_id)
            if fallback_item:
                normalized.append(fallback_item)

    return normalized


def _fallback_schedule_by_regex(
    content: str,
    original_tasks: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    raw_entries = _fallback_schedule_entries_by_regex(content)
    task_map = {str(task["id"]): task for task in original_tasks}
    results: List[Dict[str, Any]] = []

    for item in raw_entries:
        task_id = str(item.get("task_id")).strip()
        start = str(item.get("scheduled_start") or "").strip()
        end = str(item.get("scheduled_end") or "").strip()
        if task_id not in task_map:
            continue
        if not _parse_iso_datetime(start) or not _parse_iso_datetime(end):
            continue
        results.append(
            {
                "task_id": task_map[task_id]["id"],
                "scheduled_start": start,
                "scheduled_end": end,
                "status": "已安排",
            }
        )

    return results


def _fallback_schedule_entries_by_regex(content: str) -> List[Dict[str, Any]]:
    pattern = re.compile(
        r'"task_id"\s*:\s*"?(?P<task_id>[^",}\s]+)"?'
        r'.*?"scheduled_start"\s*:\s*"(?P<scheduled_start>[^"]*)"'
        r'.*?"scheduled_end"\s*:\s*"(?P<scheduled_end>[^"]*)"',
        re.DOTALL,
    )
    results: List[Dict[str, Any]] = []

    for match in pattern.finditer(content or ""):
        results.append(
            {
                "task_id": match.group("task_id").strip(),
                "scheduled_start": match.group("scheduled_start").strip(),
                "scheduled_end": match.group("scheduled_end").strip(),
            }
        )

    return results


def _local_schedule_tasks(
    tasks: Sequence[Dict[str, Any]],
    available_slots: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    slots = []
    for slot in available_slots:
        start_dt = _parse_iso_datetime(slot.get("start", "") if isinstance(slot, dict) else "")
        end_dt = _parse_iso_datetime(slot.get("end", "") if isinstance(slot, dict) else "")
        if start_dt and end_dt and end_dt > start_dt:
            slots.append({"start": start_dt, "end": end_dt})

    sorted_tasks = sorted(
        tasks,
        key=lambda item: (
            -_clamp_priority(item.get("priority")),
            _due_date_sort_key(item.get("due_date")),
            _safe_int(item.get("estimated_minutes"), 60),
        ),
    )

    results: List[Dict[str, Any]] = []

    for task in sorted_tasks:
        duration = max(1, _safe_int(task.get("estimated_minutes"), 60))
        assigned = False

        for slot in slots:
            remaining_minutes = int((slot["end"] - slot["start"]).total_seconds() // 60)
            if remaining_minutes < duration:
                continue

            scheduled_start = slot["start"]
            scheduled_end = scheduled_start.timestamp() + duration * 60
            scheduled_end_dt = datetime.fromtimestamp(scheduled_end, tz=scheduled_start.tzinfo)

            results.append(
                {
                    "task_id": task["id"],
                    "scheduled_start": scheduled_start.isoformat(),
                    "scheduled_end": scheduled_end_dt.isoformat(),
                    "status": "已安排",
                }
            )
            slot["start"] = scheduled_end_dt
            assigned = True
            break

        if not assigned:
            results.append(
                {
                    "task_id": task["id"],
                    "scheduled_start": "",
                    "scheduled_end": "",
                    "status": "未能安排",
                    "reason": "可用时间不足，已优先安排更高优先级任务。",
                }
            )

    return results


def _due_date_sort_key(due_date: Any) -> float:
    dt = _parse_iso_datetime(str(due_date or "").strip())
    if not dt:
        return float("inf")
    return dt.timestamp()


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    text = (value or "").strip()
    if not text:
        return None

    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _clamp_minutes(value: Any, default: int) -> int:
    minutes = _safe_int(value, default)
    return max(30, min(120, minutes))


def _clamp_priority(value: Any) -> int:
    priority = _safe_int(value, 3)
    return max(1, min(5, priority))


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
