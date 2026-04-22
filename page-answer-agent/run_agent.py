import argparse
import json
from pathlib import Path

from agent import ensure_utf8_stdout, solve_page_tasks


ROOT = Path(__file__).resolve().parent
DEFAULT_CAPTURE_PATH = ROOT / "captured_pages" / "latest-page-capture.json"


def main() -> None:
    ensure_utf8_stdout()

    parser = argparse.ArgumentParser(description="Run the standalone page answer agent against a captured page JSON file.")
    parser.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE_PATH, help="Path to captured page JSON.")
    parser.add_argument("--mode", choices=["direct", "detail", "hint", "framework", "reference"], default="detail")
    parser.add_argument("--note", default="", help="Optional user note.")
    args = parser.parse_args()

    payload = json.loads(args.capture.resolve().read_text(encoding="utf-8"))
    result = solve_page_tasks(
        page_text=payload.get("selection") or payload.get("content") or "",
        page_title=payload.get("title", ""),
        page_url=payload.get("url", ""),
        user_note=args.note,
        answer_mode=args.mode,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
