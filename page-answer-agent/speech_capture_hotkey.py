import ctypes
import ctypes.wintypes
import os
import threading
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd

from app_env import load_local_env
from desktop_hotkey_utils import flash_console_status, parse_hotkey, post_json
from speech_agent import extract_question_from_transcript, transcribe_audio_file


ROOT = Path(__file__).resolve().parent
AUDIO_CAPTURE_DIR = ROOT / "audio_captures"

HOTKEY_ID = 3
WM_HOTKEY = 0x0312


load_local_env()


class SpeechCaptureHotkeyApp:
    def __init__(self) -> None:
        self.hotkey = parse_hotkey(os.getenv("PAGE_SPEECH_CAPTURE_HOTKEY", "CTRL+SHIFT+U"))
        self.backend_endpoint = os.getenv("PAGE_CAPTURE_BACKEND_URL", "http://127.0.0.1:8010/api/page-capture")
        self.sample_rate = int(os.getenv("PAGE_AUDIO_SAMPLE_RATE", "16000"))
        self.channels = int(os.getenv("PAGE_AUDIO_CHANNELS", "1"))
        self.dtype = os.getenv("PAGE_AUDIO_DTYPE", "int16").strip() or "int16"

        self.hotkey_registered = False
        self.recording = False
        self.processing = False
        self.stream = None
        self.audio_chunks: list[np.ndarray] = []
        self.recording_started_at = ""
        self.state_lock = threading.Lock()

    def handle_audio_chunk(self, indata, frames, time_info, status) -> None:
        del frames, time_info
        if status:
            flash_console_status(f"Audio input status: {status}")
        with self.state_lock:
            if self.recording:
                self.audio_chunks.append(indata.copy())

    def save_audio_capture(self, audio_data: np.ndarray) -> tuple[Path, Path]:
        AUDIO_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        latest_path = AUDIO_CAPTURE_DIR / "latest-speech.wav"
        archive_path = AUDIO_CAPTURE_DIR / f"speech-{timestamp}.wav"
        for target in (latest_path, archive_path):
            with wave.open(str(target), "wb") as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(np.dtype(self.dtype).itemsize)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(audio_data.tobytes())
        return latest_path, archive_path

    def start_recording(self) -> None:
        with self.state_lock:
            if self.processing:
                flash_console_status("Voice processing is still running. Please wait.")
                return
            if self.recording:
                flash_console_status("Recording is already in progress.")
                return

            self.audio_chunks = []
            self.recording_started_at = datetime.now().strftime("%H:%M:%S")
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                callback=self.handle_audio_chunk,
            )
            self.stream.start()
            self.recording = True
        flash_console_status(f"Voice recording started at {self.recording_started_at}. Press {self.hotkey.label} again to stop.")

    def stop_recording(self) -> None:
        with self.state_lock:
            if not self.recording:
                flash_console_status("Recording has not started yet.")
                return
            self.recording = False
            stream = self.stream
            self.stream = None
            audio_chunks = list(self.audio_chunks)
            self.audio_chunks = []
            self.processing = True

        try:
            if stream is not None:
                stream.stop()
                stream.close()
        except Exception as exc:
            flash_console_status(f"Stopping audio stream failed: {exc}")

        if not audio_chunks:
            with self.state_lock:
                self.processing = False
            flash_console_status("No audio captured. Please try again.")
            return

        threading.Thread(target=self.process_audio_capture, args=(audio_chunks,), daemon=True).start()
        flash_console_status("Voice recording stopped. Starting transcription.")

    def process_audio_capture(self, audio_chunks: list[np.ndarray]) -> None:
        try:
            audio_data = np.concatenate(audio_chunks, axis=0)
            latest_audio_path, archive_audio_path = self.save_audio_capture(audio_data)
            duration_seconds = round(len(audio_data) / max(self.sample_rate, 1), 2)
            flash_console_status(f"Audio saved: {archive_audio_path.name} ({duration_seconds}s)")

            transcription = transcribe_audio_file(archive_audio_path)
            transcript = transcription["transcript"]
            flash_console_status(f"Transcript: {transcript}")

            extraction = extract_question_from_transcript(transcript)
            question_text = extraction["questionText"]
            flash_console_status(f"Question: {question_text}")

            payload = {
                "title": "语音提问",
                "url": "local://speech-hotkey",
                "content": transcript,
                "selection": question_text,
                "source": "speech-hotkey",
                "metadata": {
                    "transcript": transcript,
                    "spokenSummary": extraction.get("spokenSummary", ""),
                    "audioPath": str(archive_audio_path.relative_to(ROOT)),
                    "latestAudioPath": str(latest_audio_path.relative_to(ROOT)),
                    "asrModel": transcription.get("model", ""),
                    "questionExtractorModel": extraction.get("model", ""),
                    "questionConfidence": extraction.get("confidence", 0.0),
                    "missingContext": extraction.get("missingContext", []),
                },
            }

            result = post_json(self.backend_endpoint, payload)
            session_id = result.get("sessionId", "n/a")
            direct_url = result.get("directMobileUrl", result.get("mobileUrl", ""))
            detail_url = result.get("detailMobileUrl", "")
            flash_console_status(f"Voice question submitted -> session {session_id}")
            if direct_url:
                flash_console_status(f"Direct page: {direct_url}")
            if detail_url:
                flash_console_status(f"Detail page: {detail_url}")
            if result.get("message"):
                flash_console_status(result["message"])
        except Exception as exc:
            flash_console_status(f"Voice capture failed: {exc}")
        finally:
            with self.state_lock:
                self.processing = False

    def toggle_recording(self) -> None:
        if self.recording:
            self.stop_recording()
        else:
            try:
                self.start_recording()
            except Exception as exc:
                with self.state_lock:
                    self.processing = False
                flash_console_status(f"Unable to start recording: {exc}")

    def register_global_hotkey(self) -> None:
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, HOTKEY_ID, self.hotkey.modifiers, self.hotkey.virtual_key):
            raise RuntimeError(f"Failed to register hotkey {self.hotkey.label}. It may already be in use.")
        self.hotkey_registered = True
        flash_console_status(f"Voice hotkey registered: {self.hotkey.label}")

    def unregister_global_hotkey(self) -> None:
        if self.hotkey_registered:
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
            self.hotkey_registered = False

    def hotkey_loop(self) -> None:
        user32 = ctypes.windll.user32
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.toggle_recording()
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def start(self) -> None:
        if os.name != "nt":
            raise RuntimeError("This hotkey daemon currently supports Windows only.")

        flash_console_status("Speech capture hotkey daemon is starting.")
        flash_console_status(f"Backend endpoint: {self.backend_endpoint}")
        flash_console_status(f"Audio sample rate: {self.sample_rate}")
        flash_console_status(f"Audio channels: {self.channels}")
        self.register_global_hotkey()
        try:
            self.hotkey_loop()
        finally:
            self.unregister_global_hotkey()


if __name__ == "__main__":
    SpeechCaptureHotkeyApp().start()
