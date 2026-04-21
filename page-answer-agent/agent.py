import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOCAL_ENV_PATH = ROOT / ".env.local"
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_VISION_MODEL = "qwen2.5-vl-3b-instruct"
DEFAULT_QWEN_TEXT_MODEL = "qwen-plus"


def get_http_timeout_seconds() -> int:
    return int(os.getenv("PAGE_TASK_AGENT_TIMEOUT_SECONDS", "180"))


def iter_env_paths() -> list[Path]:
    candidates = [LOCAL_ENV_PATH]
    relative_candidates = [
        Path("quant-training-app") / ".env.local",
        Path("page-answer-agent") / ".env.local",
    ]
    for base in (ROOT.parent, *ROOT.parents):
        for relative_path in relative_candidates:
            candidate = base / relative_path
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def load_local_env() -> None:
    for env_path in iter_env_paths():
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_local_env()


def ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def get_api_key() -> str:
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing Qwen API key. Set DASHSCOPE_API_KEY or QWEN_API_KEY in page-answer-agent/.env.local."
        )
    return api_key


def get_base_url() -> str:
    return os.getenv("QWEN_BASE_URL", DEFAULT_QWEN_BASE_URL).rstrip("/")


def get_vision_model() -> str:
    return os.getenv("QWEN_VISION_MODEL", DEFAULT_QWEN_VISION_MODEL)


def get_text_model() -> str:
    return os.getenv("QWEN_TEXT_MODEL", DEFAULT_QWEN_TEXT_MODEL)


def solve_page_tasks(
    *,
    page_text: str = "",
    page_title: str = "",
    page_url: str = "",
    image_data_url: str = "",
    user_note: str = "",
    answer_mode: str = "reference",
) -> dict:
    cleaned_page_text = (page_text or "").strip()
    cleaned_title = (page_title or "").strip()
    cleaned_url = (page_url or "").strip()
    cleaned_image = (image_data_url or "").strip()
    cleaned_note = (user_note or "").strip()

    if not cleaned_page_text and not cleaned_image:
        raise RuntimeError("At least one of page_text or image_data_url is required.")

    api_key = get_api_key()
    task_detection = detect_tasks(
        api_key=api_key,
        page_text=cleaned_page_text,
        page_title=cleaned_title,
        page_url=cleaned_url,
        image_data_url=cleaned_image,
        user_note=cleaned_note,
    )
    selected_task = select_primary_task(
        api_key=api_key,
        task_detection=task_detection["data"],
        user_note=cleaned_note,
    )
    solution = solve_selected_task(
        api_key=api_key,
        task_detection=task_detection["data"],
        selected_task=selected_task["data"],
        user_note=cleaned_note,
        answer_mode=answer_mode,
    )

    models = [task_detection["model"], selected_task["model"], solution["model"]]
    return {
        "model": " -> ".join(models),
        "answer_mode": answer_mode,
        "selected_task": selected_task["data"],
        "content": solution["content"],
        "trace": {
            "task_detection": task_detection["data"],
            "selected_task": selected_task["data"],
        },
    }


def detect_tasks(
    *,
    api_key: str,
    page_text: str,
    page_title: str,
    page_url: str,
    image_data_url: str,
    user_note: str,
) -> dict:
    content = [
        {
            "type": "text",
            "text": build_detection_prompt(
                page_text=page_text,
                page_title=page_title,
                page_url=page_url,
                user_note=user_note,
            ),
        }
    ]
    model = get_vision_model() if image_data_url else get_text_model()
    if image_data_url:
        content.append({"type": "image_url", "image_url": {"url": image_data_url}})

    data = request_json(
        api_key=api_key,
        model=model,
        messages=[
            {"role": "system", "content": TASK_DETECTION_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        temperature=0.1,
    )
    return {"model": model, "data": data}


def select_primary_task(*, api_key: str, task_detection: dict, user_note: str) -> dict:
    data = request_json(
        api_key=api_key,
        model=get_text_model(),
        messages=[
            {"role": "system", "content": TASK_SELECTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_selection_prompt(task_detection=task_detection, user_note=user_note),
            },
        ],
        temperature=0.1,
    )
    return {"model": get_text_model(), "data": data}


def solve_selected_task(
    *,
    api_key: str,
    task_detection: dict,
    selected_task: dict,
    user_note: str,
    answer_mode: str,
) -> dict:
    content = request_text(
        api_key=api_key,
        model=get_text_model(),
        messages=[
            {"role": "system", "content": SOLVER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_solver_prompt(
                    task_detection=task_detection,
                    selected_task=selected_task,
                    user_note=user_note,
                    answer_mode=answer_mode,
                ),
            },
        ],
        temperature=0.2,
    )
    return {"model": get_text_model(), "content": content}


def request_json(*, api_key: str, model: str, messages: list[dict], temperature: float) -> dict:
    raw = request_chat_completion(
        api_key=api_key,
        model=model,
        messages=messages,
        temperature=temperature,
    )
    return parse_json_payload(raw)


def request_text(*, api_key: str, model: str, messages: list[dict], temperature: float) -> str:
    return request_chat_completion(
        api_key=api_key,
        model=model,
        messages=messages,
        temperature=temperature,
    )


def request_chat_completion(*, api_key: str, model: str, messages: list[dict], temperature: float) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    request = urllib.request.Request(
        f"{get_base_url()}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=get_http_timeout_seconds()) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Qwen API error: HTTP {exc.code}. {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to connect to Qwen API: {exc.reason}") from exc

    try:
        parsed = json.loads(raw)
        return parsed["choices"][0]["message"]["content"]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("Unexpected Qwen response format.") from exc


def parse_json_payload(content: str) -> dict:
    text = (content or "").strip()
    if not text:
        raise RuntimeError("Model returned empty content.")

    candidates = [text]
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            candidates.append("\n".join(lines[1:-1]).strip())

    balanced = extract_balanced_json(text)
    if balanced:
        candidates.append(balanced)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise RuntimeError("Model did not return a valid JSON object.")


def extract_balanced_json(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""

    depth = 0
    in_string = False
    escaping = False
    for index in range(start, len(text)):
        char = text[index]
        if escaping:
            escaping = False
            continue
        if char == "\\":
            escaping = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def build_detection_prompt(*, page_text: str, page_title: str, page_url: str, user_note: str) -> str:
    source_chunks = []
    if page_title:
        source_chunks.append(f"Page title: {page_title}")
    if page_url:
        source_chunks.append(f"Page URL: {page_url}")
    if page_text:
        source_chunks.append("Page text:\n" + page_text[:16000])
    if user_note:
        source_chunks.append(f"User note: {user_note}")

    source_text = "\n\n".join(source_chunks) if source_chunks else "No text provided."
    return f"""
Find the real actionable task or tasks in the page content.
Ignore greetings, navigation, ads, examples, product chrome, and casual conversation.
Only treat something as a task if the user is actually being asked to answer, solve, choose, code, or analyze something.

Return exactly one JSON object and nothing else.

JSON Schema:
{{
  "page_has_actionable_task": true,
  "page_summary": "",
  "tasks": [
    {{
      "task_id": "task-1",
      "is_actionable": true,
      "task_type": "coding",
      "title": "",
      "normalized_task": "",
      "subtasks": [],
      "evidence": [],
      "input_requirements": [],
      "output_requirements": [],
      "constraints": [],
      "options": [],
      "priority_score": 0,
      "confidence": 0.0
    }}
  ],
  "discarded_content": [],
  "missing_information": []
}}

Requirements:
1. If there are multiple candidate tasks, list them all.
2. If there is no actionable task, return an empty tasks list and explain why.
3. Do not misclassify greetings or page chrome as the task.
4. If a large problem contains multiple subquestions under one main prompt, keep them as one task and put the parts under `subtasks`.

Page input:
{source_text}
""".strip()


def build_selection_prompt(*, task_detection: dict, user_note: str) -> str:
    return f"""
Select the single primary task that should be solved now.
If there is no actionable task, return `no_actionable_task`.
If one task is a compound multi-part question, keep the compound task instead of selecting only one subpart.

Return exactly one JSON object and nothing else.

JSON Schema:
{{
  "selection_status": "selected",
  "selected_task_id": "task-1",
  "selection_reason": "",
  "fallback_action": "",
  "confidence": 0.0
}}

User note: {user_note or "none"}

Task detection result:
{json.dumps(task_detection, ensure_ascii=False, indent=2)}
""".strip()


def build_answer_first_instruction(answer_mode: str) -> str:
    if answer_mode == "hint":
        return (
            "Output format:\n"
            "1. The first visible line must start with `Answer:` and contain the shortest useful hint.\n"
            "2. Put brief explanation after that.\n"
            "3. Do not expand into a full solution unless necessary."
        )
    if answer_mode == "framework":
        return (
            "Output format:\n"
            "1. The first visible line must start with `Answer:` and summarize the final framework.\n"
            "2. If this is a coding task, the first fenced code block should appear before long explanation.\n"
            "3. Put details after the direct framework."
        )
    return (
        "Output format:\n"
        "1. The first visible line must start with `Answer:` and give the direct final answer.\n"
        "2. If this is a coding task, put the final runnable code in the first fenced code block near the top.\n"
        "3. If this is a math or quant task, put the final result and the key formula in plain readable text near the top.\n"
        "4. Put explanation, derivation, checks, and edge cases after the direct answer."
    )


def build_solver_prompt(*, task_detection: dict, selected_task: dict, user_note: str, answer_mode: str) -> str:
    mode_instruction = {
        "hint": "Give only the key hint needed to move forward, not a long full solution.",
        "framework": "Give a complete solving framework, decision order, and necessary formulas or pseudocode, but keep it compact.",
        "reference": "Give a complete reference solution, but keep the answer tight and useful.",
    }.get(answer_mode, "Give a complete reference solution and keep it concise.")
    answer_first_instruction = build_answer_first_instruction(answer_mode)
    return f"""
You are a page task solver. Answer only the selected primary task. Output in Chinese Markdown.

Hard requirements:
1. No greetings, no filler, no theatrical summary.
2. Put the direct answer first. Do not hide the answer after a long explanation.
3. Prefer plain readable math notation. Avoid LaTeX delimiters such as `$...$`, `\\(...\\)`, `\\[...\\]`.
4. If you need math symbols, prefer plain text like `!=`, `<=`, `>=`, `in`, `->`, `x^2`.
5. If this is a coding task, provide the final code block near the top, then explain.
6. If information is incomplete, state the missing point briefly and continue with the minimum necessary assumption.
7. If the task has multiple subquestions, answer all of them.
8. {mode_instruction}

{answer_first_instruction}

User note: {user_note or "none"}

Task detection result:
{json.dumps(task_detection, ensure_ascii=False, indent=2)}

Selected primary task:
{json.dumps(selected_task, ensure_ascii=False, indent=2)}
""".strip()


TASK_DETECTION_SYSTEM_PROMPT = """
You are Page Task Detection Agent.
Your job is to identify the real actionable task from noisy page content.
Return strict JSON only.
""".strip()


TASK_SELECTION_SYSTEM_PROMPT = """
You are Primary Task Selector Agent.
Choose the single primary task that should be solved now.
Return strict JSON only.
""".strip()


SOLVER_SYSTEM_PROMPT = """
You are Page Task Solver Agent.
Return concise, complete, checkable answers.
Answer first, explanation second.
Use readable Markdown.
Avoid filler.
Avoid LaTeX-style math delimiters unless absolutely necessary.
""".strip()


if __name__ == "__main__":
    ensure_utf8_stdout()
