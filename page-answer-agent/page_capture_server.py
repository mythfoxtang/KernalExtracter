import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from app_env import ROOT, get_app_config, load_local_env
from mobile_ui import build_html_page, render_not_found_html
from page_service import PageAnswerService


load_local_env()
CONFIG = get_app_config()
SERVICE = PageAnswerService(config=CONFIG, root=ROOT)


class PageCaptureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path == "/mobile/latest":
            latest = SERVICE.load_latest_session_state()
            if not latest:
                self.send_html(render_not_found_html(CONFIG.mobile_title, "还没有可查看的任务。"), status=HTTPStatus.NOT_FOUND)
                return
            self.redirect(SERVICE.build_mobile_view_path(latest["sessionId"], "direct"))
            return

        if path.startswith("/mobile/session/"):
            suffix = path.removeprefix("/mobile/session/")
            parts = [part for part in suffix.split("/") if part]
            if len(parts) != 2:
                self.send_html(render_not_found_html(CONFIG.mobile_title, "页面地址无效。"), status=HTTPStatus.NOT_FOUND)
                return
            session_id, view_name = parts
            if view_name not in {"direct", "detail"}:
                self.send_html(render_not_found_html(CONFIG.mobile_title, "页面视图无效。"), status=HTTPStatus.NOT_FOUND)
                return
            session = SERVICE.load_session_state(session_id)
            if not session:
                self.send_html(render_not_found_html(CONFIG.mobile_title, "未找到对应的任务。"), status=HTTPStatus.NOT_FOUND)
                return
            self.send_html(
                build_html_page(
                    mobile_title=CONFIG.mobile_title,
                    session_id=session_id,
                    current_view=view_name,
                    build_mobile_view_path=SERVICE.build_mobile_view_path,
                )
            )
            return

        if path.startswith("/api/runs/"):
            run_id = path.removeprefix("/api/runs/").strip()
            state = SERVICE.load_run_state(run_id)
            if not state:
                self.send_json({"error": f"Run not found: {run_id}"}, status=HTTPStatus.NOT_FOUND)
                return
            self.send_json(state)
            return

        if path.startswith("/api/sessions/"):
            session_id = path.removeprefix("/api/sessions/").strip()
            snapshot = SERVICE.load_session_snapshot(session_id)
            if not snapshot:
                self.send_json({"error": f"Session not found: {session_id}"}, status=HTTPStatus.NOT_FOUND)
                return
            self.send_json(snapshot)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/page-capture":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_json({"error": "Request body is not valid JSON."}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            response = SERVICE.create_capture_session(payload=payload)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self.send_json(response)

    def log_message(self, format, *args):
        return

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.end_headers()

    def send_json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        response = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        response = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def run() -> None:
    server = ThreadingHTTPServer((CONFIG.host, CONFIG.port), PageCaptureHandler)
    print(f"Page Capture Server is running at http://{CONFIG.host}:{CONFIG.port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
