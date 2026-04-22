import ctypes
import ctypes.wintypes
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
LOCAL_ENV_PATH = ROOT / ".env.local"

HOTKEY_ID = 2
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
WM_HOTKEY = 0x0312
MAX_CONTENT_CHARS = 20000
MAX_SELECTION_CHARS = 4000

DEFAULT_CDP_ENDPOINT = os.getenv("BROWSER_CDP_ENDPOINT", "http://127.0.0.1:9222")
DEFAULT_BACKEND_ENDPOINT = os.getenv("PAGE_CAPTURE_BACKEND_URL", "http://127.0.0.1:8010/api/page-capture")
DEFAULT_HOTKEY = os.getenv("PAGE_CAPTURE_HOTKEY", "CTRL+SHIFT+Y")

EXTRACT_PAGE_SCRIPT = """
({ maxContentChars, maxSelectionChars }) => {
  const normalizeText = (value) => (value || "").replace(/\\s+/g, " ").trim();
  const preferredRoot =
    document.querySelector("article") ||
    document.querySelector("main") ||
    document.querySelector("[role='main']") ||
    document.body;

  const content = normalizeText(preferredRoot?.innerText || document.body?.innerText || "")
    .slice(0, maxContentChars);
  const selection = normalizeText(window.getSelection?.().toString() || "")
    .slice(0, maxSelectionChars);

  return {
    title: document.title || "",
    url: location.href,
    content,
    selection,
    metadata: {
      description:
        document.querySelector("meta[name='description']")?.content ||
        document.querySelector("meta[property='og:description']")?.content ||
        "",
      headings: Array.from(document.querySelectorAll("h1, h2, h3"))
        .map((node) => normalizeText(node.textContent || ""))
        .filter(Boolean)
        .slice(0, 20),
    },
  };
}
"""


def load_local_env():
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


@dataclass
class HotkeyConfig:
    modifiers: int
    virtual_key: int
    label: str


def parse_hotkey(hotkey: str) -> HotkeyConfig:
    tokens = [token.strip().upper() for token in hotkey.split("+") if token.strip()]
    modifiers = 0
    key_name = None

    for token in tokens:
        if token in {"CTRL", "CONTROL"}:
            modifiers |= MOD_CONTROL
        elif token == "SHIFT":
            modifiers |= MOD_SHIFT
        elif token == "ALT":
            modifiers |= MOD_ALT
        else:
            key_name = token

    if key_name is None:
        raise ValueError(f"Invalid hotkey: {hotkey}")

    vk_map = {
        **{chr(code): code for code in range(ord("A"), ord("Z") + 1)},
        **{str(num): ord(str(num)) for num in range(0, 10)},
        "F1": 0x70,
        "F2": 0x71,
        "F3": 0x72,
        "F4": 0x73,
        "F5": 0x74,
        "F6": 0x75,
        "F7": 0x76,
        "F8": 0x77,
        "F9": 0x78,
        "F10": 0x79,
        "F11": 0x7A,
        "F12": 0x7B,
    }
    if key_name not in vk_map:
        raise ValueError(f"Unsupported hotkey key: {key_name}")

    return HotkeyConfig(modifiers=modifiers, virtual_key=vk_map[key_name], label=hotkey.upper())


def get_foreground_window_title() -> str:
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""

    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value.strip()


def fetch_current_page_payload(cdp_endpoint: str) -> dict:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp_endpoint)
        try:
            candidates = []
            foreground_title = get_foreground_window_title().lower()

            for context in browser.contexts:
                for page in context.pages:
                    try:
                        if page.is_closed():
                            continue
                        title = page.title()
                        url = page.url
                    except PlaywrightError:
                        continue

                    if not url.startswith("http://") and not url.startswith("https://"):
                        continue

                    score = 0
                    lowered_title = title.lower()
                    if foreground_title:
                        if lowered_title and lowered_title in foreground_title:
                            score += 5
                        if foreground_title in lowered_title:
                            score += 3
                    if page == context.pages[-1]:
                        score += 1
                    candidates.append((score, page))

            if not candidates:
                raise RuntimeError("No capturable HTTP page found in the browser session.")

            candidates.sort(key=lambda item: item[0], reverse=True)
            page = candidates[0][1]
            payload = page.evaluate(
                EXTRACT_PAGE_SCRIPT,
                {
                    "maxContentChars": MAX_CONTENT_CHARS,
                    "maxSelectionChars": MAX_SELECTION_CHARS,
                },
            )
            if not payload.get("content") and not payload.get("selection"):
                raise RuntimeError("The current page did not yield readable text content.")
            return payload
        finally:
            browser.close()


def post_payload(backend_endpoint: str, payload: dict) -> dict:
    request = urllib.request.Request(
        backend_endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Backend returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach backend: {exc.reason}") from exc


def flash_console_status(message: str):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def build_answer_preview(answer: str, max_len: int = 180) -> str:
    compact = " ".join((answer or "").split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


class PageCaptureHotkeyApp:
    def __init__(self):
        self.hotkey = parse_hotkey(DEFAULT_HOTKEY)
        self.cdp_endpoint = DEFAULT_CDP_ENDPOINT
        self.backend_endpoint = DEFAULT_BACKEND_ENDPOINT
        self.is_running = False
        self.hotkey_registered = False

    def run_capture_once(self):
        if self.is_running:
            flash_console_status("Capture already running. Ignoring duplicate hotkey.")
            return

        self.is_running = True

        def worker():
            try:
                flash_console_status(f"Connecting to browser CDP: {self.cdp_endpoint}")
                payload = fetch_current_page_payload(self.cdp_endpoint)
                payload["source"] = "playwright-hotkey"
                result = post_payload(self.backend_endpoint, payload)
                session_id = result.get("sessionId", "n/a")
                direct_url = result.get("directMobileUrl", result.get("mobileUrl", ""))
                detail_url = result.get("detailMobileUrl", "")
                flash_console_status(f"Captured '{payload.get('title') or 'Untitled'}' -> session {session_id}")
                flash_console_status(f"Run status: {result.get('status', 'queued')}")
                if direct_url:
                    flash_console_status(f"Direct page: {direct_url}")
                if detail_url:
                    flash_console_status(f"Detail page: {detail_url}")
                if result.get("message"):
                    flash_console_status(result["message"])
            except Exception as exc:
                flash_console_status(f"Capture failed: {exc}")
            finally:
                self.is_running = False

        threading.Thread(target=worker, daemon=True).start()

    def register_global_hotkey(self):
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, HOTKEY_ID, self.hotkey.modifiers, self.hotkey.virtual_key):
            raise RuntimeError(f"Failed to register hotkey {self.hotkey.label}. It may already be in use.")
        self.hotkey_registered = True
        flash_console_status(f"Hotkey registered: {self.hotkey.label}")

    def unregister_global_hotkey(self):
        if self.hotkey_registered:
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
            self.hotkey_registered = False

    def hotkey_loop(self):
        user32 = ctypes.windll.user32
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.run_capture_once()
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def start(self):
        if os.name != "nt":
            raise RuntimeError("This hotkey daemon currently supports Windows only.")

        flash_console_status("Page capture hotkey daemon is starting.")
        flash_console_status(f"Browser CDP endpoint: {self.cdp_endpoint}")
        flash_console_status(f"Backend endpoint: {self.backend_endpoint}")
        flash_console_status("Make sure the dedicated Chrome debug window is running on --remote-debugging-port=9222.")
        self.register_global_hotkey()
        try:
            self.hotkey_loop()
        finally:
            self.unregister_global_hotkey()


if __name__ == "__main__":
    PageCaptureHotkeyApp().start()
