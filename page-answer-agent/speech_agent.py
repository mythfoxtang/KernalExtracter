import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path

from agent import get_api_key, get_base_url, get_http_timeout_seconds, get_text_model, request_json


DEFAULT_QWEN_ASR_MODEL = "qwen3-asr-flash"


def get_asr_model() -> str:
    return os.getenv("QWEN_ASR_MODEL", DEFAULT_QWEN_ASR_MODEL).strip() or DEFAULT_QWEN_ASR_MODEL


def encode_audio_as_data_url(audio_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(audio_path.name)
    payload = base64.b64encode(audio_path.read_bytes()).decode("ascii")
    return f"data:{mime_type or 'audio/wav'};base64,{payload}"


def detect_audio_format(audio_path: Path) -> str:
    suffix = audio_path.suffix.lower().lstrip(".")
    return suffix or "wav"


def transcribe_audio_file(audio_path: str | Path) -> dict:
    path = Path(audio_path)
    if not path.exists():
        raise RuntimeError(f"Audio file does not exist: {path}")

    payload = {
        "model": get_asr_model(),
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": encode_audio_as_data_url(path),
                            "format": detect_audio_format(path),
                        },
                    }
                ],
            }
        ],
        "temperature": 0,
        "extra_body": {
            "asr_options": {
                "language": "zh",
                "enable_itn": True,
            }
        },
    }
    request = urllib.request.Request(
        f"{get_base_url()}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {get_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=get_http_timeout_seconds()) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Qwen ASR API error: HTTP {exc.code}. {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to connect to Qwen ASR API: {exc.reason}") from exc

    try:
        parsed = json.loads(raw)
        transcript = str(parsed["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("Unexpected Qwen ASR response format.") from exc

    if not transcript:
        raise RuntimeError("Qwen ASR returned empty transcript.")

    return {"model": get_asr_model(), "transcript": transcript}


def extract_question_from_transcript(transcript: str) -> dict:
    cleaned_transcript = str(transcript or "").strip()
    if not cleaned_transcript:
        raise RuntimeError("Transcript is empty.")

    data = request_json(
        api_key=get_api_key(),
        model=get_text_model(),
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a spoken question extraction agent. "
                    "Return strict JSON only. "
                    "Extract the user's real answerable question from spoken Chinese text. "
                    "Remove filler words, repetitions, false starts, and conversational noise."
                ),
            },
            {
                "role": "user",
                "content": f"""
Extract the final answerable question from this speech transcript.
Keep the original meaning. Do not expand beyond the transcript.
If the transcript contains multiple subquestions under one main request, merge them into one answerable prompt.

Return exactly one JSON object:
{{
  "has_question": true,
  "question_text": "",
  "spoken_summary": "",
  "missing_context": [],
  "confidence": 0.0
}}

Transcript:
{cleaned_transcript}
""".strip(),
            },
        ],
        temperature=0.1,
    )

    question_text = str(data.get("question_text", "")).strip() or cleaned_transcript
    spoken_summary = str(data.get("spoken_summary", "")).strip()
    return {
        "model": get_text_model(),
        "questionText": question_text,
        "spokenSummary": spoken_summary,
        "hasQuestion": bool(data.get("has_question", True)),
        "missingContext": data.get("missing_context", []),
        "confidence": float(data.get("confidence", 0.0) or 0.0),
        "transcript": cleaned_transcript,
    }
