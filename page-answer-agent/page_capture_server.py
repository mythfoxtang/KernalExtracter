import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from agent import solve_page_tasks


ROOT = Path(__file__).resolve().parent
CAPTURE_DIR = ROOT / "captured_pages"
AGENT_LOG_DIR = ROOT / "agent_logs"
LOCAL_ENV_PATH = ROOT / ".env.local"


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
DEFAULT_AGENT_MODE = os.getenv("PAGE_TASK_AGENT_MODE", "reference")
DEFAULT_AGENT_NOTE = os.getenv("PAGE_TASK_AGENT_NOTE", "")
DEFAULT_MOBILE_TITLE = os.getenv("PAGE_MOBILE_TITLE", "Page Answer Result")
DEFAULT_MOBILE_PUBLIC_URL = os.getenv("PAGE_MOBILE_PUBLIC_URL", "").rstrip("/")
DEFAULT_NTFY_ENABLED = os.getenv("NTFY_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
DEFAULT_NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
DEFAULT_NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
DEFAULT_NTFY_TOKEN = os.getenv("NTFY_TOKEN", "").strip()
DEFAULT_NTFY_PRIORITY_SUCCESS = os.getenv("NTFY_PRIORITY_SUCCESS", "3").strip() or "3"
DEFAULT_NTFY_PRIORITY_ERROR = os.getenv("NTFY_PRIORITY_ERROR", "4").strip() or "4"
DEFAULT_NTFY_TAGS_SUCCESS = os.getenv("NTFY_TAGS_SUCCESS", "white_check_mark,robot_face").strip()
DEFAULT_NTFY_TAGS_ERROR = os.getenv("NTFY_TAGS_ERROR", "warning,robot_face").strip()


def build_agent_input(record: dict) -> dict:
    return {
        "page_text": record.get("selection") or record.get("content") or "",
        "page_title": record.get("title", ""),
        "page_url": record.get("url", ""),
    }


def run_agent(record: dict, answer_mode: str, user_note: str) -> dict:
    agent_input = build_agent_input(record)
    return solve_page_tasks(
        page_text=agent_input["page_text"],
        page_title=agent_input["page_title"],
        page_url=agent_input["page_url"],
        user_note=user_note,
        answer_mode=answer_mode,
    )


def compact_text(value: str, max_len: int = 160) -> str:
    text = " ".join((value or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def save_agent_log(record: dict, answer_mode: str, user_note: str, result: dict | None = None, error: str = "") -> Path:
    AGENT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_payload = {
        "capturedPage": {
            "title": record.get("title", ""),
            "url": record.get("url", ""),
            "source": record.get("source", ""),
            "receivedAt": record.get("receivedAt", ""),
            "contentLength": record.get("contentLength", 0),
            "selectionLength": record.get("selectionLength", 0),
        },
        "agentConfig": {
            "answerMode": answer_mode,
            "userNote": user_note,
        },
        "ok": not error,
        "result": result or {},
        "error": error,
        "loggedAt": datetime.now(timezone.utc).isoformat(),
    }
    latest_path = AGENT_LOG_DIR / "latest-agent-run.json"
    archive_path = AGENT_LOG_DIR / f"agent-run-{timestamp}.json"
    serialized = json.dumps(log_payload, ensure_ascii=False, indent=2)
    latest_path.write_text(serialized, encoding="utf-8")
    archive_path.write_text(serialized, encoding="utf-8")
    return archive_path


def load_latest_agent_log() -> dict:
    latest_path = AGENT_LOG_DIR / "latest-agent-run.json"
    if not latest_path.exists():
        return {}
    try:
        return json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def build_mobile_latest_url() -> str:
    if not DEFAULT_MOBILE_PUBLIC_URL:
        return ""
    return f"{DEFAULT_MOBILE_PUBLIC_URL}/mobile/latest"


def send_ntfy_notification(*, title: str, message: str, priority: str, tags: str, click_url: str = "") -> None:
    if not DEFAULT_NTFY_ENABLED or not DEFAULT_NTFY_TOPIC:
        return

    request = urllib.request.Request(
        f"{DEFAULT_NTFY_SERVER}/{DEFAULT_NTFY_TOPIC}",
        data=message.encode("utf-8"),
        method="POST",
        headers={
            "Title": title,
            "Priority": priority,
            "Tags": tags,
        },
    )
    if DEFAULT_NTFY_TOKEN:
        request.add_header("Authorization", f"Bearer {DEFAULT_NTFY_TOKEN}")
    if click_url:
        request.add_header("Click", click_url)

    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


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
        "\\times": "×",
        "\\cdot": "·",
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


def render_paragraph(text: str) -> str:
    return f"<p>{render_inline_markdown(text)}</p>"


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
            html_parts.append(render_paragraph(combined))
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
        code = "\n".join(code_lines)
        html_parts.append(f"<pre><code>{escape(code)}</code></pre>")
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

    return "".join(html_parts) if html_parts else "<p>No answer yet.</p>"


def extract_direct_answer(content: str) -> str:
    normalized = normalize_math_text(content)
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line or line == "---" or line.startswith("```"):
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        if line.lower().startswith("answer:"):
            return line
        if line.startswith("答案：") or line.startswith("答案:"):
            return line
        return compact_text(line, 220)
    return "No direct answer extracted."


def notify_agent_success(*, record: dict, answer_mode: str, result: dict) -> None:
    selected_task = result.get("selected_task", {})
    task_id = selected_task.get("selected_task_id") or selected_task.get("task_id") or "task"
    page_title = record.get("title", "").strip() or "Page solved"
    direct_answer = extract_direct_answer(result.get("content", ""))
    message_lines = [
        f"Mode: {answer_mode}",
        f"Task: {task_id}",
        f"Page: {compact_text(page_title, 60)}",
        "",
        compact_text(direct_answer, 220),
    ]
    send_ntfy_notification(
        title="Answer Ready",
        message="\n".join(message_lines),
        priority=DEFAULT_NTFY_PRIORITY_SUCCESS,
        tags=DEFAULT_NTFY_TAGS_SUCCESS,
        click_url=build_mobile_latest_url(),
    )


def notify_agent_failure(*, record: dict, answer_mode: str, error_message: str) -> None:
    page_title = record.get("title", "").strip() or "Page failed"
    message_lines = [
        f"Mode: {answer_mode}",
        f"Page: {compact_text(page_title, 60)}",
        "",
        compact_text(error_message, 220) or "Agent run failed.",
    ]
    send_ntfy_notification(
        title="Answer Failed",
        message="\n".join(message_lines),
        priority=DEFAULT_NTFY_PRIORITY_ERROR,
        tags=DEFAULT_NTFY_TAGS_ERROR,
        click_url=build_mobile_latest_url(),
    )


def render_mobile_latest_html(log_payload: dict) -> str:
    captured_page = log_payload.get("capturedPage", {})
    result = log_payload.get("result", {})
    selected_task = result.get("selected_task", {})
    answer = result.get("content", "")
    error = log_payload.get("error", "")
    ok = bool(log_payload.get("ok"))
    page_title = captured_page.get("title", "") or "Untitled page"
    page_url = captured_page.get("url", "")
    task_id = selected_task.get("selected_task_id") or selected_task.get("task_id") or "n/a"
    answer_mode = log_payload.get("agentConfig", {}).get("answerMode", "")
    logged_at = log_payload.get("loggedAt", "")
    display_content = answer or error or "No answer yet."
    lead_answer = extract_direct_answer(display_content)
    answer_html = render_markdown_html(display_content)
    page_url_html = (
        f'<a href="{escape(page_url)}" target="_blank" rel="noreferrer">{escape(page_url)}</a>' if page_url else "N/A"
    )
    status_text = "Success" if ok else "Failed"
    status_class = "ok" if ok else "error"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="format-detection" content="telephone=no">
  <meta http-equiv="refresh" content="10">
  <title>{escape(DEFAULT_MOBILE_TITLE)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4ecdf;
      --panel: rgba(255, 255, 255, 0.94);
      --text: #17212b;
      --muted: #61707f;
      --accent: #0f6c8f;
      --accent-soft: rgba(15, 108, 143, 0.12);
      --ok: #1f7a49;
      --error: #a33b20;
      --border: rgba(15, 108, 143, 0.14);
      --shadow: 0 18px 40px rgba(52, 78, 91, 0.14);
      --code-bg: #10212b;
      --code-text: #eef6fa;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(255,255,255,0.78), transparent 30%),
        linear-gradient(180deg, #f0e5d3 0%, var(--bg) 42%, #efe5d8 100%);
      min-height: 100vh;
    }}
    .wrap {{
      max-width: 920px;
      margin: 0 auto;
      padding: 20px 14px 36px;
    }}
    .hero {{
      padding: 18px 4px 12px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
      line-height: 1.15;
    }}
    .sub {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 16px;
      box-shadow: var(--shadow);
      margin-top: 14px;
    }}
    .status {{
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 12px;
    }}
    .status.ok {{
      background: rgba(31, 122, 73, 0.12);
      color: var(--ok);
    }}
    .status.error {{
      background: rgba(163, 59, 32, 0.12);
      color: var(--error);
    }}
    .meta {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
    }}
    .meta-item {{
      padding: 12px;
      border-radius: 14px;
      background: #fcfbf7;
      border: 1px solid rgba(31, 41, 55, 0.06);
    }}
    .label {{
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .value {{
      font-size: 15px;
      line-height: 1.55;
      word-break: break-word;
    }}
    .answer-lead {{
      margin-top: 14px;
      padding: 14px 16px;
      border-radius: 16px;
      background: linear-gradient(180deg, rgba(220, 239, 247, 0.9), rgba(255, 255, 255, 0.98));
      border: 1px solid rgba(15, 108, 143, 0.18);
    }}
    .answer-lead-label {{
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
      color: var(--accent);
      text-transform: uppercase;
      margin-bottom: 8px;
    }}
    .answer-lead-value {{
      font-size: 17px;
      line-height: 1.6;
      font-weight: 700;
      word-break: break-word;
    }}
    .answer {{
      margin-top: 14px;
      padding: 16px;
      border-radius: 16px;
      background: linear-gradient(180deg, rgba(214, 235, 246, 0.45), rgba(255, 255, 255, 0.94));
      border: 1px solid rgba(15, 108, 143, 0.14);
      font-size: 15px;
      line-height: 1.78;
      word-break: break-word;
    }}
    .answer h1, .answer h2, .answer h3 {{
      margin: 20px 0 10px;
      line-height: 1.3;
    }}
    .answer h1 {{ font-size: 24px; }}
    .answer h2 {{ font-size: 20px; }}
    .answer h3 {{ font-size: 17px; }}
    .answer p {{
      margin: 0 0 12px;
    }}
    .answer ul {{
      margin: 0 0 14px 18px;
      padding: 0;
    }}
    .answer li {{
      margin: 0 0 8px;
    }}
    .answer code {{
      font-family: "Cascadia Code", "Consolas", "SFMono-Regular", monospace;
      background: rgba(16, 33, 43, 0.08);
      padding: 1px 5px;
      border-radius: 6px;
      font-size: 0.95em;
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
    .answer pre code {{
      background: transparent;
      padding: 0;
      border-radius: 0;
      color: inherit;
      font-size: 13px;
    }}
    .actions {{
      display: flex;
      gap: 10px;
      margin-top: 14px;
      flex-wrap: wrap;
    }}
    button, .link-btn {{
      border: 0;
      border-radius: 999px;
      background: var(--accent);
      color: #fff;
      padding: 10px 14px;
      font-size: 14px;
      text-decoration: none;
    }}
    .hint {{
      margin-top: 10px;
      font-size: 12px;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>{escape(DEFAULT_MOBILE_TITLE)}</h1>
      <div class="sub">结果页每 10 秒自动刷新一次。最上面先给直接答案，下面再给完整内容。</div>
    </div>
    <div class="panel">
      <div class="status {status_class}">Status: {status_text}</div>
      <div class="meta">
        <div class="meta-item">
          <div class="label">页面标题</div>
          <div class="value">{escape(page_title)}</div>
        </div>
        <div class="meta-item">
          <div class="label">页面地址</div>
          <div class="value">{page_url_html}</div>
        </div>
        <div class="meta-item">
          <div class="label">答题模式 / 任务</div>
          <div class="value">{escape(answer_mode or "reference")} / {escape(task_id)}</div>
        </div>
        <div class="meta-item">
          <div class="label">最近更新时间</div>
          <div class="value">{escape(logged_at or "N/A")}</div>
        </div>
      </div>
      <div class="answer-lead">
        <div class="answer-lead-label">Direct Answer</div>
        <div class="answer-lead-value" id="answerLead">{escape(lead_answer)}</div>
      </div>
      <div class="answer" id="answerText">{answer_html}</div>
      <div class="actions">
        <button type="button" id="copyBtn">复制完整答案</button>
        <a class="link-btn" href="/mobile/latest" target="_self">立即刷新</a>
      </div>
      <div class="hint">代码块、行内代码和常见数学写法已做可读化处理。复制按钮复制的是完整答案文本。</div>
    </div>
  </div>
  <script>
    const copyBtn = document.getElementById("copyBtn");
    copyBtn?.addEventListener("click", async () => {{
      const text = document.getElementById("answerText")?.innerText || "";
      try {{
        await navigator.clipboard.writeText(text);
        copyBtn.innerText = "已复制";
      }} catch (error) {{
        copyBtn.innerText = "复制失败";
      }}
    }});
  </script>
</body>
</html>"""


class PageCaptureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/mobile/latest":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        html = render_mobile_latest_html(load_latest_agent_log())
        response = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

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
        answer_mode = str(payload.get("answerMode", DEFAULT_AGENT_MODE)).strip() or DEFAULT_AGENT_MODE
        user_note = str(payload.get("agentNote", DEFAULT_AGENT_NOTE)).strip()

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
            "receivedAt": datetime.now(timezone.utc).isoformat(),
            "contentLength": len(page_text),
            "selectionLength": len(selection),
        }

        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        latest_path = CAPTURE_DIR / "latest-page-capture.json"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archive_path = CAPTURE_DIR / f"page-capture-{timestamp}.json"
        serialized = json.dumps(record, ensure_ascii=False, indent=2)
        latest_path.write_text(serialized, encoding="utf-8")
        archive_path.write_text(serialized, encoding="utf-8")

        try:
            agent_result = run_agent(record=record, answer_mode=answer_mode, user_note=user_note)
            agent_log_path = save_agent_log(record=record, answer_mode=answer_mode, user_note=user_note, result=agent_result)
            try:
                notify_agent_success(record=record, answer_mode=answer_mode, result=agent_result)
            except Exception as notify_exc:
                print(f"ntfy success notification failed: {notify_exc}")
        except Exception as exc:
            error_message = str(exc)
            agent_log_path = save_agent_log(record=record, answer_mode=answer_mode, user_note=user_note, error=error_message)
            try:
                notify_agent_failure(record=record, answer_mode=answer_mode, error_message=error_message)
            except Exception as notify_exc:
                print(f"ntfy failure notification failed: {notify_exc}")
            self.send_json(
                {
                    "ok": False,
                    "message": "Page captured, but agent execution failed.",
                    "savedTo": str(latest_path.relative_to(ROOT)),
                    "archiveFile": str(archive_path.relative_to(ROOT)),
                    "contentLength": len(page_text),
                    "selectionLength": len(selection),
                    "agent": {
                        "ok": False,
                        "error": error_message,
                        "answerMode": answer_mode,
                        "logFile": str(agent_log_path.relative_to(ROOT)),
                    },
                }
            )
            return

        self.send_json(
            {
                "ok": True,
                "message": "Page captured and agent answer generated.",
                "savedTo": str(latest_path.relative_to(ROOT)),
                "archiveFile": str(archive_path.relative_to(ROOT)),
                "contentLength": len(page_text),
                "selectionLength": len(selection),
                "agent": {
                    "ok": True,
                    "answerMode": answer_mode,
                    "model": agent_result.get("model", ""),
                    "selectedTask": agent_result.get("selected_task", {}),
                    "answer": agent_result.get("content", ""),
                    "logFile": str(agent_log_path.relative_to(ROOT)),
                },
            }
        )

    def log_message(self, format, *args):
        return

    def send_json(self, data, status=HTTPStatus.OK):
        response = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def run():
    server = ThreadingHTTPServer((HOST, PORT), PageCaptureHandler)
    print(f"Page Capture Server is running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
