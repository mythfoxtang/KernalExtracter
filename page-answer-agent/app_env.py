import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
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


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    mobile_title: str
    mobile_public_url: str
    ntfy_enabled: bool
    ntfy_server: str
    ntfy_topic: str
    ntfy_token: str
    ntfy_priority_info: str
    ntfy_priority_success: str
    ntfy_priority_error: str
    ntfy_tags_info: str
    ntfy_tags_success: str
    ntfy_tags_error: str


def get_app_config() -> AppConfig:
    return AppConfig(
        host=os.getenv("PAGE_CAPTURE_HOST", "0.0.0.0"),
        port=int(os.getenv("PAGE_CAPTURE_PORT", "8010")),
        mobile_title=os.getenv("PAGE_MOBILE_TITLE", "Page Answer Result"),
        mobile_public_url=os.getenv("PAGE_MOBILE_PUBLIC_URL", "").rstrip("/"),
        ntfy_enabled=os.getenv("NTFY_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"},
        ntfy_server=os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/"),
        ntfy_topic=os.getenv("NTFY_TOPIC", "").strip(),
        ntfy_token=os.getenv("NTFY_TOKEN", "").strip(),
        ntfy_priority_info=os.getenv("NTFY_PRIORITY_INFO", "2").strip() or "2",
        ntfy_priority_success=os.getenv("NTFY_PRIORITY_SUCCESS", "3").strip() or "3",
        ntfy_priority_error=os.getenv("NTFY_PRIORITY_ERROR", "4").strip() or "4",
        ntfy_tags_info=os.getenv("NTFY_TAGS_INFO", "hourglass_flowing_sand,robot_face").strip(),
        ntfy_tags_success=os.getenv("NTFY_TAGS_SUCCESS", "white_check_mark,robot_face").strip(),
        ntfy_tags_error=os.getenv("NTFY_TAGS_ERROR", "warning,robot_face").strip(),
    )
