import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004


@dataclass(frozen=True)
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


def post_json(endpoint: str, payload: dict, *, timeout_seconds: int = 30) -> dict:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Backend returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach backend: {exc.reason}") from exc


def flash_console_status(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)
