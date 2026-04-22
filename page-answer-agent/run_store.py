import json
import threading
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CAPTURE_DIR = ROOT / "captured_pages"
AGENT_LOG_DIR = ROOT / "agent_logs"
RUN_DIR = ROOT / "agent_runs"
SESSION_DIR = RUN_DIR / "sessions"
FILE_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_run_file_path(run_id: str) -> Path:
    return RUN_DIR / f"{run_id}.json"


def build_session_file_path(session_id: str) -> Path:
    return SESSION_DIR / f"{session_id}.json"


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


def create_session_state(*, session_id: str, record: dict, direct_run_id: str, detail_run_id: str, build_mobile_view_path) -> dict:
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


def append_answer_chunk(state: dict, chunk: str, extract_direct_answer) -> None:
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
    extract_direct_answer=None,
) -> None:
    if status:
        state["status"] = status
    if stage and message:
        append_stream_event(state, stage, message)
    else:
        state["updatedAt"] = now_iso()
    if answer_chunk and extract_direct_answer is not None:
        append_answer_chunk(state, answer_chunk, extract_direct_answer)
    if status in {"succeeded", "failed"}:
        state["finishedAt"] = now_iso()
