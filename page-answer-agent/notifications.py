import urllib.request

from app_env import AppConfig
from text_utils import compact_text


def send_ntfy_notification(*, config: AppConfig, title: str, message: str, priority: str, tags: str, click_url: str = "") -> None:
    if not config.ntfy_enabled or not config.ntfy_topic:
        return

    request = urllib.request.Request(
        f"{config.ntfy_server}/{config.ntfy_topic}",
        data=message.encode("utf-8"),
        method="POST",
        headers={"Title": title, "Priority": priority, "Tags": tags},
    )
    if config.ntfy_token:
        request.add_header("Authorization", f"Bearer {config.ntfy_token}")
    if click_url:
        request.add_header("Click", click_url)
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


def notify_session_started(*, config: AppConfig, session_id: str, page_title: str, click_url: str) -> None:
    send_ntfy_notification(
        config=config,
        title="Answer Started",
        message="\n".join(
            [
                f"Session: {session_id}",
                f"Page: {compact_text(page_title, 60)}",
                "",
                "任务已开始，点击查看简答页。",
            ]
        ),
        priority=config.ntfy_priority_info,
        tags=config.ntfy_tags_info,
        click_url=click_url,
    )


def notify_direct_success(*, config: AppConfig, state: dict, click_url: str) -> None:
    page_title = state.get("page", {}).get("title", "").strip() or "Page solved"
    send_ntfy_notification(
        config=config,
        title="Answer Ready",
        message="\n".join(
            [
                f"Session: {state.get('sessionId', '')}",
                f"Page: {compact_text(page_title, 60)}",
                "",
                compact_text(state.get("directAnswer", ""), 220),
            ]
        ),
        priority=config.ntfy_priority_success,
        tags=config.ntfy_tags_success,
        click_url=click_url,
    )


def notify_direct_failure(*, config: AppConfig, state: dict, click_url: str) -> None:
    page_title = state.get("page", {}).get("title", "").strip() or "Page failed"
    send_ntfy_notification(
        config=config,
        title="Answer Failed",
        message="\n".join(
            [
                f"Session: {state.get('sessionId', '')}",
                f"Page: {compact_text(page_title, 60)}",
                "",
                compact_text(state.get("error", ""), 220) or "Agent run failed.",
            ]
        ),
        priority=config.ntfy_priority_error,
        tags=config.ntfy_tags_error,
        click_url=click_url,
    )
