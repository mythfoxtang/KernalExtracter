import secrets
import threading
from datetime import datetime

from agent import solve_page_tasks_with_progress
from notifications import notify_direct_failure, notify_direct_success, notify_session_started
from run_store import (
    create_run_state,
    create_session_state,
    load_latest_session_state,
    load_run_state,
    load_session_snapshot,
    load_session_state,
    save_agent_log,
    save_capture_files,
    update_run_state,
    write_run_state,
    write_session_state,
)
from text_utils import extract_direct_answer


def new_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{secrets.token_hex(2)}"


def build_agent_input(record: dict) -> dict:
    return {
        "page_text": record.get("selection") or record.get("content") or "",
        "page_title": record.get("title", ""),
        "page_url": record.get("url", ""),
    }


class PageAnswerService:
    def __init__(self, *, config, root):
        self.config = config
        self.root = root

    @staticmethod
    def build_mobile_view_path(session_id: str, view_name: str) -> str:
        return f"/mobile/session/{session_id}/{view_name}"

    def build_mobile_view_url(self, session_id: str, view_name: str) -> str:
        path = self.build_mobile_view_path(session_id, view_name)
        if not self.config.mobile_public_url:
            return path
        return f"{self.config.mobile_public_url}{path}"

    def load_latest_session_state(self) -> dict:
        return load_latest_session_state()

    def load_session_state(self, session_id: str) -> dict:
        return load_session_state(session_id)

    def load_session_snapshot(self, session_id: str) -> dict:
        return load_session_snapshot(session_id)

    def load_run_state(self, run_id: str) -> dict:
        return load_run_state(run_id)

    def create_capture_session(self, *, payload: dict) -> dict:
        title = str(payload.get("title", "")).strip()
        url = str(payload.get("url", "")).strip()
        page_text = str(payload.get("content", "")).strip()
        selection = str(payload.get("selection", "")).strip()
        source = str(payload.get("source", "playwright-hotkey")).strip() or "playwright-hotkey"
        metadata = payload.get("metadata", {})
        user_note = str(payload.get("agentNote", "")).strip()

        if not url:
            raise ValueError("Missing url.")
        if not page_text and not selection:
            raise ValueError("Page content is empty.")

        record = {
            "title": title,
            "url": url,
            "content": page_text,
            "selection": selection,
            "source": source,
            "metadata": metadata if isinstance(metadata, dict) else {},
            "receivedAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
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
            build_mobile_view_path=self.build_mobile_view_path,
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
            state["capture"]["latestPath"] = str(latest_capture_path.relative_to(self.root))
            state["capture"]["archivePath"] = str(archive_capture_path.relative_to(self.root))
            write_run_state(state)
        write_session_state(session)

        try:
            notify_session_started(
                config=self.config,
                session_id=session_id,
                page_title=title or "Untitled page",
                click_url=self.build_mobile_view_url(session_id, "direct"),
            )
        except Exception as exc:
            print(f"ntfy start notification failed: {exc}")

        threading.Thread(
            target=self.process_run_in_background,
            args=(direct_state, record),
            kwargs={"notify_result": True},
            daemon=True,
        ).start()
        threading.Thread(
            target=self.process_run_in_background,
            args=(detail_state, record),
            kwargs={"notify_result": False},
            daemon=True,
        ).start()

        return {
            "ok": True,
            "sessionId": session_id,
            "directRunId": direct_run_id,
            "detailRunId": detail_run_id,
            "status": "queued",
            "mobileUrl": self.build_mobile_view_path(session_id, "direct"),
            "directMobileUrl": self.build_mobile_view_path(session_id, "direct"),
            "detailMobileUrl": self.build_mobile_view_path(session_id, "detail"),
            "apiUrl": f"/api/sessions/{session_id}",
            "message": "Input captured. Direct answer and detailed answer are running in background.",
        }

    def process_run_in_background(self, state: dict, record: dict, *, notify_result: bool) -> None:
        try:
            update_run_state(
                state,
                status="running",
                stage="capture_saved",
                message="页面内容已保存",
            )
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
                    extract_direct_answer=extract_direct_answer,
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
                ).relative_to(self.root)
            )
            update_run_state(state, status="succeeded", stage="done", message="答案已生成完成")
            write_run_state(state)
            if notify_result:
                try:
                    notify_direct_success(
                        config=self.config,
                        state=state,
                        click_url=self.build_mobile_view_url(state["sessionId"], "direct"),
                    )
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
                ).relative_to(self.root)
            )
            update_run_state(state, status="failed", stage="failed", message="后台任务执行失败")
            write_run_state(state)
            if notify_result:
                try:
                    notify_direct_failure(
                        config=self.config,
                        state=state,
                        click_url=self.build_mobile_view_url(state["sessionId"], "direct"),
                    )
                except Exception as notify_exc:
                    print(f"ntfy failure notification failed: {notify_exc}")
