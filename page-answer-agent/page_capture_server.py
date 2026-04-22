import json
import os
import re
import secrets
import threading
import urllib.request
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from agent import solve_page_tasks_with_progress


ROOT = Path(__file__).resolve().parent
CAPTURE_DIR = ROOT / "captured_pages"
AGENT_LOG_DIR = ROOT / "agent_logs"
RUN_DIR = ROOT / "agent_runs"
SESSION_DIR = RUN_DIR / "sessions"
LOCAL_ENV_PATH = ROOT / ".env.local"
FILE_LOCK = threading.Lock()


def load_local_env() -> None:
    if not LOCAL_ENV_PATH.exists():
        return

    for raw_line in LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()

HOST = os.getenv("PAGE_CAPTURE_HOST", "0.0.0.0")
PORT = int(os.getenv("PAGE_CAPTURE_PORT", "8010"))
DEFAULT_MOBILE_TITLE = os.getenv("PAGE_MOBILE_TITLE", "Page Answer Result")
DEFAULT_MOBILE_PUBLIC_URL = os.getenv("PAGE_MOBILE_PUBLIC_URL", "").rstrip("/")
DEFAULT_NTFY_ENABLED = os.getenv("NTFY_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
DEFAULT_NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
DEFAULT_NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
DEFAULT_NTFY_TOKEN = os.getenv("NTFY_TOKEN", "").strip()
DEFAULT_NTFY_PRIORITY_INFO = os.getenv("NTFY_PRIORITY_INFO", "2").strip() or "2"
DEFAULT_NTFY_PRIORITY_SUCCESS = os.getenv("NTFY_PRIORITY_SUCCESS", "3").strip() or "3"
DEFAULT_NTFY_PRIORITY_ERROR = os.getenv("NTFY_PRIORITY_ERROR", "4").strip() or "4"
DEFAULT_NTFY_TAGS_INFO = os.getenv("NTFY_TAGS_INFO", "hourglass_flowing_sand,robot_face").strip()
DEFAULT_NTFY_TAGS_SUCCESS = os.getenv("NTFY_TAGS_SUCCESS", "white_check_mark,robot_face").strip()
DEFAULT_NTFY_TAGS_ERROR = os.getenv("NTFY_TAGS_ERROR", "warning,robot_face").strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact_text(value: str, max_len: int = 160) -> str:
    text = " ".join((value or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def normalize_math_text(text: str) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\$\$(.*?)\$\$", r"\1", normalized, flags=re.S)
    normalized = re.sub(r"\$(.*?)\$", r"\1", normalized, flags=re.S)
    normalized = normalized.replace("\\[", "").replace("\\]", "")
    normalized = normalized.replace("\\(", "").replace("\\)", "")
    replacements = {
        "\\neq": "!=",
        "\\leq": "<=",
        "\\geq": ">=",
        "\\le": "<=",
        "\\ge": ">=",
        "\\times": "x",
        "\\cdot": "*",
        "\\in": "in",
        "\\notin": "not in",
        "\\to": "->",
        "\\Rightarrow": "=>",
        "\\Leftarrow": "<=",
        "\\iff": "<=>",
        "\\sum": "sum",
        "\\prod": "prod",
        "\\alpha": "alpha",
        "\\beta": "beta",
        "\\gamma": "gamma",
        "\\theta": "theta",
        "\\lambda": "lambda",
        "\\mu": "mu",
        "\\sigma": "sigma",
        "\\pi": "pi",
        "\\phi": "phi",
        "\\sqrt": "sqrt",
        "\\left": "",
        "\\right": "",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def render_inline_markdown(text: str) -> str:
    rendered = escape(text)
    rendered = re.sub(r"`([^`]+)`", lambda m: f"<code>{escape(m.group(1))}</code>", rendered)
    rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
    return rendered


def render_markdown_html(text: str) -> str:
    normalized = normalize_math_text(text)
    lines = normalized.split("\n")
    html_parts: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    in_code_block = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        combined = " ".join(line.strip() for line in paragraph_lines if line.strip())
        if combined:
            html_parts.append(f"<p>{render_inline_markdown(combined)}</p>")
        paragraph_lines.clear()

    def flush_list() -> None:
        if not list_items:
            return
        html_parts.append("<ul>" + "".join(list_items) + "</ul>")
        list_items.clear()

    def flush_code() -> None:
        nonlocal code_lines
        if not code_lines:
            return
        html_parts.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
        code_lines = []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            flush_list()
            if in_code_block:
                flush_code()
                in_code_block = False
            else:
                in_code_block = True
            continue
        if in_code_block:
            code_lines.append(line)
            continue
        if not stripped:
            flush_paragraph()
            flush_list()
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            flush_paragraph()
            list_items.append(f"<li>{render_inline_markdown(stripped[2:].strip())}</li>")
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            flush_list()
            html_parts.append(f"<h3>{render_inline_markdown(stripped[4:].strip())}</h3>")
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            flush_list()
            html_parts.append(f"<h2>{render_inline_markdown(stripped[3:].strip())}</h2>")
            continue
        if stripped.startswith("# "):
            flush_paragraph()
            flush_list()
            html_parts.append(f"<h1>{render_inline_markdown(stripped[2:].strip())}</h1>")
            continue
        paragraph_lines.append(stripped)

    flush_paragraph()
    flush_list()
    if in_code_block:
        flush_code()
    return "".join(html_parts) if html_parts else "<p>暂无内容。</p>"


def extract_direct_answer(content: str) -> str:
    normalized = normalize_math_text(content)
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line or line == "---" or line.startswith("```"):
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        if line.lower().startswith("answer:") or line.startswith("答案：") or line.startswith("答案:"):
            return compact_text(line, 220)
        return compact_text(line, 220)
    return "等待答案..."


def send_ntfy_notification(*, title: str, message: str, priority: str, tags: str, click_url: str = "") -> None:
    if not DEFAULT_NTFY_ENABLED or not DEFAULT_NTFY_TOPIC:
        return

    request = urllib.request.Request(
        f"{DEFAULT_NTFY_SERVER}/{DEFAULT_NTFY_TOPIC}",
        data=message.encode("utf-8"),
        method="POST",
        headers={"Title": title, "Priority": priority, "Tags": tags},
    )
    if DEFAULT_NTFY_TOKEN:
        request.add_header("Authorization", f"Bearer {DEFAULT_NTFY_TOKEN}")
    if click_url:
        request.add_header("Click", click_url)
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


def new_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{secrets.token_hex(2)}"


def build_agent_input(record: dict) -> dict:
    return {
        "page_text": record.get("selection") or record.get("content") or "",
        "page_title": record.get("title", ""),
        "page_url": record.get("url", ""),
    }


def build_run_file_path(run_id: str) -> Path:
    return RUN_DIR / f"{run_id}.json"


def build_session_file_path(session_id: str) -> Path:
    return SESSION_DIR / f"{session_id}.json"


def build_mobile_view_path(session_id: str, view_name: str) -> str:
    return f"/mobile/session/{session_id}/{view_name}"


def build_mobile_view_url(session_id: str, view_name: str) -> str:
    path = build_mobile_view_path(session_id, view_name)
    if not DEFAULT_MOBILE_PUBLIC_URL:
        return path
    return f"{DEFAULT_MOBILE_PUBLIC_URL}{path}"


def save_capture_files(record: dict) -> tuple[Path, Path]:
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    latest_path = CAPTURE_DIR / "latest-page-capture.json"
    archive_path = CAPTURE_DIR / f"page-capture-{timestamp}.json"
    serialized = json.dumps(record, ensure_ascii=False, indent=2)
    with FILE_LOCK:
        latest_path.write_text(serialized, encoding="utf-8")
        archive_path.write_text(serialized, encoding="utf-8")
    return latest_path, archive_path


def save_agent_log(
    *,
    record: dict,
    session_id: str,
    run_id: str,
    view_name: str,
    answer_mode: str,
    user_note: str,
    result: dict | None = None,
    error: str = "",
) -> Path:
    AGENT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = {
        "sessionId": session_id,
        "runId": run_id,
        "view": view_name,
        "capturedPage": {
            "title": record.get("title", ""),
            "url": record.get("url", ""),
            "source": record.get("source", ""),
            "receivedAt": record.get("receivedAt", ""),
            "contentLength": record.get("contentLength", 0),
            "selectionLength": record.get("selectionLength", 0),
        },
        "agentConfig": {"answerMode": answer_mode, "userNote": user_note},
        "ok": not error,
        "result": result or {},
        "error": error,
        "loggedAt": now_iso(),
    }
    latest_path = AGENT_LOG_DIR / f"latest-{view_name}.json"
    archive_path = AGENT_LOG_DIR / f"agent-run-{view_name}-{timestamp}.json"
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    with FILE_LOCK:
        latest_path.write_text(serialized, encoding="utf-8")
        archive_path.write_text(serialized, encoding="utf-8")
    return archive_path


def create_run_state(*, session_id: str, run_id: str, view_name: str, answer_mode: str, user_note: str, record: dict) -> dict:
    created_at = now_iso()
    return {
        "sessionId": session_id,
        "runId": run_id,
        "view": view_name,
        "status": "queued",
        "progressStage": "queued",
        "progressMessage": "任务已创建，等待后台处理",
        "createdAt": created_at,
        "updatedAt": created_at,
        "finishedAt": "",
        "answerMode": answer_mode,
        "userNote": user_note,
        "page": {
            "title": record.get("title", ""),
            "url": record.get("url", ""),
            "source": record.get("source", ""),
            "receivedAt": record.get("receivedAt", ""),
        },
        "capture": {"latestPath": "", "archivePath": ""},
        "agent": {"model": "", "selectedTask": {}, "trace": {}, "logFile": ""},
        "directAnswer": "",
        "streamEvents": ["[queued] 任务已创建"],
        "streamText": "",
        "finalAnswer": "",
        "error": "",
    }


def create_session_state(*, session_id: str, record: dict, direct_run_id: str, detail_run_id: str) -> dict:
    created_at = now_iso()
    return {
        "sessionId": session_id,
        "createdAt": created_at,
        "updatedAt": created_at,
        "page": {
            "title": record.get("title", ""),
            "url": record.get("url", ""),
            "source": record.get("source", ""),
        },
        "views": {
            "direct": {"runId": direct_run_id, "mobileUrl": build_mobile_view_path(session_id, "direct")},
            "detail": {"runId": detail_run_id, "mobileUrl": build_mobile_view_path(session_id, "detail")},
        },
    }


def write_run_state(state: dict) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = build_run_file_path(state["runId"])
    serialized = json.dumps(state, ensure_ascii=False, indent=2)
    with FILE_LOCK:
        path.write_text(serialized, encoding="utf-8")


def write_session_state(state: dict) -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    latest_path = SESSION_DIR / "latest.json"
    path = build_session_file_path(state["sessionId"])
    serialized = json.dumps(state, ensure_ascii=False, indent=2)
    with FILE_LOCK:
        path.write_text(serialized, encoding="utf-8")
        latest_path.write_text(serialized, encoding="utf-8")


def load_run_state(run_id: str) -> dict:
    path = build_run_file_path(run_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_session_state(session_id: str) -> dict:
    path = build_session_file_path(session_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_latest_session_state() -> dict:
    path = SESSION_DIR / "latest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_session_snapshot(session_id: str) -> dict:
    session = load_session_state(session_id)
    if not session:
        return {}
    direct_run_id = session.get("views", {}).get("direct", {}).get("runId", "")
    detail_run_id = session.get("views", {}).get("detail", {}).get("runId", "")
    return {
        **session,
        "runs": {
            "direct": load_run_state(direct_run_id) if direct_run_id else {},
            "detail": load_run_state(detail_run_id) if detail_run_id else {},
        },
    }


def append_stream_event(state: dict, stage: str, message: str) -> None:
    events = list(state.get("streamEvents", []))
    events.append(f"[{stage}] {message}")
    state["streamEvents"] = events
    state["progressStage"] = stage
    state["progressMessage"] = message
    state["updatedAt"] = now_iso()


def append_answer_chunk(state: dict, chunk: str) -> None:
    if not chunk:
        return
    state["streamText"] = f"{state.get('streamText', '')}{chunk}"
    state["finalAnswer"] = f"{state.get('finalAnswer', '')}{chunk}"
    state["directAnswer"] = extract_direct_answer(state["finalAnswer"])
    state["updatedAt"] = now_iso()


def update_run_state(
    state: dict,
    *,
    status: str | None = None,
    stage: str | None = None,
    message: str | None = None,
    answer_chunk: str = "",
) -> None:
    if status:
        state["status"] = status
    if stage and message:
        append_stream_event(state, stage, message)
    else:
        state["updatedAt"] = now_iso()
    if answer_chunk:
        append_answer_chunk(state, answer_chunk)
    if status in {"succeeded", "failed"}:
        state["finishedAt"] = now_iso()


def notify_session_started(session_id: str, page_title: str) -> None:
    send_ntfy_notification(
        title="Answer Started",
        message="\n".join(
            [
                f"Session: {session_id}",
                f"Page: {compact_text(page_title, 60)}",
                "",
                "任务已开始，点击查看简答页。",
            ]
        ),
        priority=DEFAULT_NTFY_PRIORITY_INFO,
        tags=DEFAULT_NTFY_TAGS_INFO,
        click_url=build_mobile_view_url(session_id, "direct"),
    )


def notify_direct_success(state: dict) -> None:
    page_title = state.get("page", {}).get("title", "").strip() or "Page solved"
    send_ntfy_notification(
        title="Answer Ready",
        message="\n".join(
            [
                f"Session: {state.get('sessionId', '')}",
                f"Page: {compact_text(page_title, 60)}",
                "",
                compact_text(state.get("directAnswer", ""), 220),
            ]
        ),
        priority=DEFAULT_NTFY_PRIORITY_SUCCESS,
        tags=DEFAULT_NTFY_TAGS_SUCCESS,
        click_url=build_mobile_view_url(state["sessionId"], "direct"),
    )


def notify_direct_failure(state: dict) -> None:
    page_title = state.get("page", {}).get("title", "").strip() or "Page failed"
    send_ntfy_notification(
        title="Answer Failed",
        message="\n".join(
            [
                f"Session: {state.get('sessionId', '')}",
                f"Page: {compact_text(page_title, 60)}",
                "",
                compact_text(state.get("error", ""), 220) or "Agent run failed.",
            ]
        ),
        priority=DEFAULT_NTFY_PRIORITY_ERROR,
        tags=DEFAULT_NTFY_TAGS_ERROR,
        click_url=build_mobile_view_url(state["sessionId"], "direct"),
    )


def process_run_in_background(state: dict, record: dict, *, notify_result: bool) -> None:
    try:
        update_run_state(state, status="running", stage="capture_saved", message="页面内容已保存")
        write_run_state(state)

        def handle_progress(payload: dict) -> None:
            stage = str(payload.get("stage", "running")).strip() or "running"
            message = str(payload.get("message", "处理中")).strip() or "处理中"
            answer_chunk = str(payload.get("answer_chunk", ""))
            if payload.get("selected_task"):
                state["agent"]["selectedTask"] = payload["selected_task"]
            if payload.get("task_detection"):
                state["agent"]["trace"]["task_detection"] = payload["task_detection"]
            update_run_state(
                state,
                status="running",
                stage=stage,
                message=message,
                answer_chunk=answer_chunk,
            )
            write_run_state(state)

        result = solve_page_tasks_with_progress(
            page_text=build_agent_input(record)["page_text"],
            page_title=record.get("title", ""),
            page_url=record.get("url", ""),
            user_note=state.get("userNote", ""),
            answer_mode=state.get("answerMode", "detail"),
            progress_callback=handle_progress,
        )
        state["agent"]["model"] = result.get("model", "")
        state["agent"]["selectedTask"] = result.get("selected_task", {})
        state["agent"]["trace"] = result.get("trace", {})
        state["finalAnswer"] = result.get("content", "")
        state["streamText"] = result.get("content", "")
        state["directAnswer"] = extract_direct_answer(state["finalAnswer"])
        state["agent"]["logFile"] = str(
            save_agent_log(
                record=record,
                session_id=state["sessionId"],
                run_id=state["runId"],
                view_name=state["view"],
                answer_mode=state["answerMode"],
                user_note=state["userNote"],
                result=result,
            ).relative_to(ROOT)
        )
        update_run_state(state, status="succeeded", stage="done", message="答案已生成完成")
        write_run_state(state)
        if notify_result:
            try:
                notify_direct_success(state)
            except Exception as exc:
                print(f"ntfy success notification failed: {exc}")
    except Exception as exc:
        state["error"] = str(exc)
        state["agent"]["logFile"] = str(
            save_agent_log(
                record=record,
                session_id=state["sessionId"],
                run_id=state["runId"],
                view_name=state["view"],
                answer_mode=state["answerMode"],
                user_note=state["userNote"],
                error=state["error"],
            ).relative_to(ROOT)
        )
        update_run_state(state, status="failed", stage="failed", message="后台任务执行失败")
        write_run_state(state)
        if notify_result:
            try:
                notify_direct_failure(state)
            except Exception as notify_exc:
                print(f"ntfy failure notification failed: {notify_exc}")


def build_html_page(*, session_id: str, current_view: str, direct_run_id: str, detail_run_id: str) -> str:
    title = escape(DEFAULT_MOBILE_TITLE)
    is_direct = current_view == "direct"
    heading = "最简答案" if is_direct else "过程与答案"
    helper = "适合手机快速看结论" if is_direct else "流式刷新详细过程和最终答案"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="format-detection" content="telephone=no">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f1e8;
      --paper: rgba(255,255,255,0.96);
      --ink: #18222b;
      --muted: #677785;
      --accent: #0f6c8f;
      --accent-soft: rgba(15, 108, 143, 0.10);
      --border: rgba(15, 108, 143, 0.14);
      --ok: #1f7a49;
      --warn: #a56b12;
      --error: #a33b20;
      --shadow: 0 20px 48px rgba(46, 68, 78, 0.12);
      --code-bg: #10212b;
      --code-text: #eef6fa;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(255,255,255,0.72), transparent 28%),
        linear-gradient(180deg, #efe4d1 0%, var(--bg) 45%, #f4ece2 100%);
    }}
    .wrap {{
      max-width: 720px;
      margin: 0 auto;
      padding: 18px 14px 34px;
    }}
    .hero {{
      padding: 8px 2px 10px;
    }}
    .eyebrow {{
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 8px 0 4px;
      font-size: 26px;
      line-height: 1.15;
    }}
    .sub {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
    }}
    .nav {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 14px;
    }}
    .nav-link {{
      display: block;
      text-align: center;
      text-decoration: none;
      color: var(--ink);
      padding: 12px 10px;
      border-radius: 16px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.72);
      font-weight: 700;
    }}
    .nav-link.active {{
      color: white;
      background: linear-gradient(180deg, #17779a, #0f6c8f);
      box-shadow: var(--shadow);
    }}
    .panel {{
      margin-top: 14px;
      padding: 16px;
      border-radius: 20px;
      background: var(--paper);
      border: 1px solid var(--border);
      box-shadow: var(--shadow);
    }}
    .status {{
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 12px;
    }}
    .status.queued, .status.running {{ background: rgba(165,107,18,0.12); color: var(--warn); }}
    .status.succeeded {{ background: rgba(31,122,73,0.12); color: var(--ok); }}
    .status.failed {{ background: rgba(163,59,32,0.12); color: var(--error); }}
    .meta {{
      display: grid;
      gap: 10px;
    }}
    .meta-item {{
      padding: 12px;
      border-radius: 14px;
      background: #fcfbf8;
      border: 1px solid rgba(20, 40, 50, 0.06);
    }}
    .label {{ font-size: 12px; color: var(--muted); margin-bottom: 6px; }}
    .value {{ font-size: 14px; line-height: 1.6; word-break: break-word; }}
    .answer-hero {{
      margin-top: 14px;
      padding: 18px 16px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(215,236,245,0.95), rgba(255,255,255,0.98));
      border: 1px solid rgba(15,108,143,0.16);
    }}
    .answer-title {{
      font-size: 12px;
      color: var(--accent);
      letter-spacing: .08em;
      text-transform: uppercase;
      font-weight: 700;
      margin-bottom: 8px;
    }}
    .answer-value {{
      font-size: 18px;
      font-weight: 800;
      line-height: 1.6;
      word-break: break-word;
    }}
    .stream {{
      margin-top: 14px;
      white-space: pre-wrap;
      font-size: 14px;
      line-height: 1.75;
      word-break: break-word;
      padding: 14px;
      border-radius: 16px;
      background: #fffdfa;
      border: 1px solid rgba(31,41,55,0.08);
      max-height: 44vh;
      overflow-y: auto;
    }}
    .answer {{
      margin-top: 14px;
      padding: 16px;
      border-radius: 16px;
      background: linear-gradient(180deg, rgba(214,235,246,0.45), rgba(255,255,255,0.94));
      border: 1px solid rgba(15,108,143,0.14);
      font-size: 15px;
      line-height: 1.78;
      word-break: break-word;
    }}
    .answer h1, .answer h2, .answer h3 {{ margin: 18px 0 10px; line-height: 1.3; }}
    .answer h1 {{ font-size: 22px; }}
    .answer h2 {{ font-size: 19px; }}
    .answer h3 {{ font-size: 17px; }}
    .answer p {{ margin: 0 0 12px; }}
    .answer ul {{ margin: 0 0 14px 18px; padding: 0; }}
    .answer li {{ margin: 0 0 8px; }}
    .answer code {{
      font-family: "Cascadia Code", "Consolas", monospace;
      background: rgba(16, 33, 43, 0.08);
      padding: 1px 5px;
      border-radius: 6px;
      font-size: .95em;
    }}
    .answer pre {{
      margin: 14px 0;
      padding: 14px;
      overflow-x: auto;
      border-radius: 14px;
      background: var(--code-bg);
      color: var(--code-text);
      line-height: 1.6;
    }}
    .answer pre code {{ background: transparent; padding: 0; border-radius: 0; color: inherit; }}
    .actions {{
      display: flex;
      gap: 10px;
      margin-top: 14px;
      flex-wrap: wrap;
    }}
    button, .btn {{
      border: 0;
      border-radius: 999px;
      background: var(--accent);
      color: white;
      text-decoration: none;
      padding: 10px 14px;
      font-size: 14px;
      cursor: pointer;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="eyebrow">{escape(heading)}</div>
      <h1>{title}</h1>
      <div class="sub">Session ID: <span id="sessionId">{escape(session_id)}</span>。{escape(helper)}</div>
      <div class="nav">
        <a class="nav-link {'active' if is_direct else ''}" href="{escape(build_mobile_view_path(session_id, 'direct'))}">最简答案</a>
        <a class="nav-link {'' if is_direct else 'active'}" href="{escape(build_mobile_view_path(session_id, 'detail'))}">过程与答案</a>
      </div>
    </div>
    <div class="panel">
      <div class="status queued" id="statusBadge">queued</div>
      <div class="meta">
        <div class="meta-item">
          <div class="label">页面标题</div>
          <div class="value" id="pageTitle">加载中...</div>
        </div>
        <div class="meta-item">
          <div class="label">当前状态</div>
          <div class="value" id="progressMessage">等待状态...</div>
        </div>
        <div class="meta-item">
          <div class="label">最近更新时间</div>
          <div class="value" id="updatedAt">-</div>
        </div>
      </div>
      <div class="answer-hero">
        <div class="answer-title">{'Direct Answer' if is_direct else 'Current Answer'}</div>
        <div class="answer-value" id="answerLead">等待答案...</div>
      </div>
      <div class="stream" id="streamPanel" style="display:{'none' if is_direct else 'block'};">等待流式内容...</div>
      <div class="answer" id="answerText" style="display:{'none' if is_direct else 'block'};"><p>等待完整答案...</p></div>
      <div class="actions">
        <button type="button" id="copyBtn">复制当前内容</button>
        <a class="btn" href="/mobile/latest">打开最新任务</a>
      </div>
    </div>
  </div>
  <script>
    const sessionId = {json.dumps(session_id)};
    const currentView = {json.dumps(current_view)};
    const runMap = {{
      direct: {json.dumps(direct_run_id)},
      detail: {json.dumps(detail_run_id)}
    }};
    const statusBadge = document.getElementById("statusBadge");
    const pageTitle = document.getElementById("pageTitle");
    const progressMessage = document.getElementById("progressMessage");
    const updatedAt = document.getElementById("updatedAt");
    const answerLead = document.getElementById("answerLead");
    const streamPanel = document.getElementById("streamPanel");
    const answerText = document.getElementById("answerText");
    const copyBtn = document.getElementById("copyBtn");

    const renderMarkdown = (text) => {{
      const escaped = (text || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      return escaped
        .replace(/```([\\s\\S]*?)```/g, (_, code) => `<pre><code>${{code.trim()}}</code></pre>`)
        .replace(/^### (.+)$/gm, "<h3>$1</h3>")
        .replace(/^## (.+)$/gm, "<h2>$1</h2>")
        .replace(/^# (.+)$/gm, "<h1>$1</h1>")
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>")
        .split(/\\n\\n+/)
        .map(block => {{
          if (/^<h[1-3]>/.test(block) || /^<pre>/.test(block)) return block;
          if (/^(\\- |\\* )/m.test(block)) {{
            const items = block.split(/\\n/).filter(Boolean).map(line => `<li>${{line.slice(2)}}</li>`).join("");
            return `<ul>${{items}}</ul>`;
          }}
          return `<p>${{block.replace(/\\n/g, "<br>")}}</p>`;
        }})
        .join("");
    }};

    const pickRun = (snapshot) => {{
      const runs = snapshot.runs || {{}};
      return runs[currentView] || {{}};
    }};

    const renderSnapshot = (snapshot) => {{
      const run = pickRun(snapshot);
      const page = snapshot.page || run.page || {{}};
      const status = run.status || "queued";
      statusBadge.className = `status ${{status}}`;
      statusBadge.textContent = status;
      pageTitle.textContent = page.title || "Untitled page";
      progressMessage.textContent = run.progressMessage || "处理中";
      updatedAt.textContent = run.updatedAt || "-";
      answerLead.textContent = run.directAnswer || "等待答案...";
      if (currentView === "detail") {{
        streamPanel.textContent = run.streamText || "等待流式内容...";
        answerText.innerHTML = renderMarkdown(run.finalAnswer || run.error || "等待完整答案...");
      }}
      return status;
    }};

    const refresh = async () => {{
      try {{
        const response = await fetch(`/api/sessions/${{encodeURIComponent(sessionId)}}`, {{
          cache: "no-store",
          headers: {{ "Accept": "application/json" }},
        }});
        if (!response.ok) {{
          throw new Error(`HTTP ${{response.status}}`);
        }}
        const snapshot = await response.json();
        const status = renderSnapshot(snapshot);
        if (!["succeeded", "failed"].includes(status)) {{
          window.setTimeout(refresh, 1500);
        }}
      }} catch (error) {{
        progressMessage.textContent = `状态刷新失败: ${{error.message}}`;
        window.setTimeout(refresh, 3000);
      }}
    }};

    copyBtn?.addEventListener("click", async () => {{
      const text = currentView === "direct"
        ? (answerLead?.innerText || "")
        : ((answerText?.innerText || "") || (streamPanel?.innerText || ""));
      try {{
        await navigator.clipboard.writeText(text);
        copyBtn.innerText = "已复制";
      }} catch (error) {{
        copyBtn.innerText = "复制失败";
      }}
    }});

    refresh();
  </script>
</body>
</html>"""


def render_not_found_html(message: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(DEFAULT_MOBILE_TITLE)}</title>
</head>
<body style="font-family:Segoe UI,PingFang SC,Microsoft YaHei,sans-serif;padding:24px;">
  <h1>{escape(DEFAULT_MOBILE_TITLE)}</h1>
  <p>{escape(message)}</p>
</body>
</html>"""


class PageCaptureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/mobile/latest":
            latest = load_latest_session_state()
            if not latest:
                self.send_html(render_not_found_html("还没有可查看的任务。"), status=HTTPStatus.NOT_FOUND)
                return
            self.redirect(build_mobile_view_path(latest["sessionId"], "direct"))
            return

        if path.startswith("/mobile/session/"):
            suffix = path.removeprefix("/mobile/session/")
            parts = [part for part in suffix.split("/") if part]
            if len(parts) != 2:
                self.send_html(render_not_found_html("页面地址无效。"), status=HTTPStatus.NOT_FOUND)
                return
            session_id, view_name = parts
            if view_name not in {"direct", "detail"}:
                self.send_html(render_not_found_html("页面视图无效。"), status=HTTPStatus.NOT_FOUND)
                return
            session = load_session_state(session_id)
            if not session:
                self.send_html(render_not_found_html("未找到对应的任务。"), status=HTTPStatus.NOT_FOUND)
                return
            direct_run_id = session.get("views", {}).get("direct", {}).get("runId", "")
            detail_run_id = session.get("views", {}).get("detail", {}).get("runId", "")
            self.send_html(
                build_html_page(
                    session_id=session_id,
                    current_view=view_name,
                    direct_run_id=direct_run_id,
                    detail_run_id=detail_run_id,
                )
            )
            return

        if path.startswith("/api/runs/"):
            run_id = path.removeprefix("/api/runs/").strip()
            state = load_run_state(run_id)
            if not state:
                self.send_json({"error": f"Run not found: {run_id}"}, status=HTTPStatus.NOT_FOUND)
                return
            self.send_json(state)
            return

        if path.startswith("/api/sessions/"):
            session_id = path.removeprefix("/api/sessions/").strip()
            snapshot = load_session_snapshot(session_id)
            if not snapshot:
                self.send_json({"error": f"Session not found: {session_id}"}, status=HTTPStatus.NOT_FOUND)
                return
            self.send_json(snapshot)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/page-capture":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_json({"error": "Request body is not valid JSON."}, status=HTTPStatus.BAD_REQUEST)
            return

        title = str(payload.get("title", "")).strip()
        url = str(payload.get("url", "")).strip()
        page_text = str(payload.get("content", "")).strip()
        selection = str(payload.get("selection", "")).strip()
        source = str(payload.get("source", "playwright-hotkey")).strip() or "playwright-hotkey"
        metadata = payload.get("metadata", {})
        user_note = str(payload.get("agentNote", "")).strip()

        if not url:
            self.send_json({"error": "Missing url."}, status=HTTPStatus.BAD_REQUEST)
            return
        if not page_text and not selection:
            self.send_json({"error": "Page content is empty."}, status=HTTPStatus.BAD_REQUEST)
            return

        record = {
            "title": title,
            "url": url,
            "content": page_text,
            "selection": selection,
            "source": source,
            "metadata": metadata if isinstance(metadata, dict) else {},
            "receivedAt": now_iso(),
            "contentLength": len(page_text),
            "selectionLength": len(selection),
        }
        latest_capture_path, archive_capture_path = save_capture_files(record)

        session_id = new_id()
        direct_run_id = new_id()
        detail_run_id = new_id()

        session = create_session_state(
            session_id=session_id,
            record=record,
            direct_run_id=direct_run_id,
            detail_run_id=detail_run_id,
        )
        direct_state = create_run_state(
            session_id=session_id,
            run_id=direct_run_id,
            view_name="direct",
            answer_mode="direct",
            user_note=user_note,
            record=record,
        )
        detail_state = create_run_state(
            session_id=session_id,
            run_id=detail_run_id,
            view_name="detail",
            answer_mode="detail",
            user_note=user_note,
            record=record,
        )
        for state in (direct_state, detail_state):
            state["capture"]["latestPath"] = str(latest_capture_path.relative_to(ROOT))
            state["capture"]["archivePath"] = str(archive_capture_path.relative_to(ROOT))
            write_run_state(state)
        write_session_state(session)

        try:
            notify_session_started(session_id, title or "Untitled page")
        except Exception as exc:
            print(f"ntfy start notification failed: {exc}")

        threading.Thread(
            target=process_run_in_background,
            args=(direct_state, record),
            kwargs={"notify_result": True},
            daemon=True,
        ).start()
        threading.Thread(
            target=process_run_in_background,
            args=(detail_state, record),
            kwargs={"notify_result": False},
            daemon=True,
        ).start()

        self.send_json(
            {
                "ok": True,
                "sessionId": session_id,
                "directRunId": direct_run_id,
                "detailRunId": detail_run_id,
                "status": "queued",
                "mobileUrl": build_mobile_view_path(session_id, "direct"),
                "directMobileUrl": build_mobile_view_path(session_id, "direct"),
                "detailMobileUrl": build_mobile_view_path(session_id, "detail"),
                "apiUrl": f"/api/sessions/{session_id}",
                "message": "Page captured. Direct answer and detailed answer are running in background.",
            }
        )

    def log_message(self, format, *args):
        return

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.end_headers()

    def send_json(self, data, status=HTTPStatus.OK):
        response = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def send_html(self, html: str, status=HTTPStatus.OK):
        response = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def run() -> None:
    server = ThreadingHTTPServer((HOST, PORT), PageCaptureHandler)
    print(f"Page Capture Server is running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
