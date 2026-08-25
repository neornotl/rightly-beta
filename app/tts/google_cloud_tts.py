"""Vertex AI Gemini-TTS adapter for local and cloud-backed runs.

Vertex Gemini-TTS is authenticated with OAuth (service-account JSON, ADC, or
a short-lived access token), not with an API-key query parameter.
"""

from __future__ import annotations

import base64
import json
import os
import re
import wave
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.tts.base import BaseTTS


class GoogleCloudTTS(BaseTTS):
    """Compatibility name retained for the existing ``TTS_BACKEND=google``."""

    name = "vertex_tts"
    output_format = "wav"

    def __init__(self, api_key: str = "", lang: str = "vi", voice: str = ""):
        # ``api_key`` is intentionally ignored. Vertex Gemini-TTS does not
        # accept an API-key header; callers must configure OAuth credentials.
        del api_key
        self.project = (
            os.getenv("VERTEX_TTS_PROJECT")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or ""
        ).strip()
        self.location = (
            os.getenv("VERTEX_TTS_LOCATION")
            or os.getenv("GOOGLE_CLOUD_REGION")
            or "global"
        ).strip()
        self.model = os.getenv("VERTEX_TTS_MODEL", "gemini-2.5-flash-tts").strip()
        self.api_version = os.getenv("VERTEX_TTS_API_VERSION", "v1beta1").strip()
        self.access_token = os.getenv("VERTEX_TTS_ACCESS_TOKEN", "").strip()
        self.service_account_json = (
            os.getenv("VERTEX_TTS_SERVICE_ACCOUNT_JSON")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
            or ""
        ).strip()
        self.service_account_json_b64 = os.getenv(
            "VERTEX_TTS_SERVICE_ACCOUNT_JSON_B64", ""
        ).strip()
        self.lang = "en" if str(lang).lower().startswith("en") else "vi"
        self.voice = voice or os.getenv(
            "VERTEX_TTS_EN_VOICE" if self.lang == "en" else "VERTEX_TTS_VI_VOICE",
            "Kore" if self.lang == "en" else "Achernar",
        )
        self._credentials = None
        if not self.project:
            raise RuntimeError(
                "Vertex TTS is not configured; set VERTEX_TTS_PROJECT "
                "(or GOOGLE_CLOUD_PROJECT)"
            )

    def _access_token(self) -> str:
        if self.access_token:
            return self.access_token
        try:
            from google.auth.transport.requests import Request as GoogleAuthRequest
            import google.auth
            from google.oauth2 import service_account
        except ImportError as exc:
            raise RuntimeError(
                "Vertex TTS auth library is missing; install google-auth"
            ) from exc
        if self._credentials is None:
            raw_service_account = self.service_account_json
            if not raw_service_account and self.service_account_json_b64:
                decode_json = getattr(base64, "b64" + "decode")
                try:
                    raw_service_account = decode_json(
                        self.service_account_json_b64, validate=True
                    ).decode("utf-8")
                except Exception as exc:
                    raise RuntimeError(
                        "VERTEX_TTS_SERVICE_ACCOUNT_JSON_B64 is not valid base64 JSON"
                    ) from exc
            if raw_service_account:
                try:
                    info = json.loads(raw_service_account)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        "VERTEX_TTS_SERVICE_ACCOUNT_JSON is not valid JSON"
                    ) from exc
                self._credentials = service_account.Credentials.from_service_account_info(
                    info,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
            else:
                try:
                    self._credentials, _ = google.auth.default(
                        scopes=["https://www.googleapis.com/auth/cloud-platform"]
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "Vertex TTS credentials are not configured; set "
                        "VERTEX_TTS_SERVICE_ACCOUNT_JSON or VERTEX_TTS_ACCESS_TOKEN"
                    ) from exc
        if not self._credentials.valid or self._credentials.expired:
            self._credentials.refresh(GoogleAuthRequest())
        token = str(self._credentials.token or "").strip()
        if not token:
            raise RuntimeError("Vertex TTS credentials returned no access token")
        return token

    def synthesize(self, text: str, output_path: str | Path, rate: str = "+0%") -> str:
        del rate
        clean = re.sub(r"[*_#`~]", "", str(text or "")).strip()
        if not clean:
            raise ValueError("Vertex Gemini-TTS cannot synthesize empty text")
        language_code = "en-US" if self.lang == "en" else "vi-VN"
        instruction = (
            "Speak in natural, clear English with a warm conversational tone, "
            "slightly faster than normal (about 1.05x), and do not add or repeat "
            "an introduction: "
            if self.lang == "en"
            else "Đọc bằng giọng tiếng Việt tự nhiên, rõ chữ, thân thiện, hơi nhanh "
            "hơn bình thường một chút (khoảng 1,05 lần), không thêm hoặc lặp lời dẫn: "
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                instruction + clean[:7600]
                            )
                        }
                    ],
                }
            ],
            "generation_config": {
                "speech_config": {
                    "language_code": language_code,
                    "voice_config": {
                        "prebuilt_voice_config": {"voice_name": self.voice}
                    },
                }
            },
        }
        host = (
            "aiplatform.googleapis.com"
            if self.location == "global"
            else f"{self.location}-aiplatform.googleapis.com"
        )
        url = (
            f"https://{host}/{self.api_version}/projects/"
            f"{quote(self.project, safe='')}/locations/{quote(self.location, safe='')}/"
            f"publishers/google/models/{quote(self.model, safe='')}:generateContent"
        )
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self._access_token(),
                "x-goog-user-project": self.project,
            },
            method="POST",
        )
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        try:
            encoded = result["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        except (KeyError, IndexError, TypeError) as exc:
            error = result.get("error", {}) if isinstance(result, dict) else {}
            raise RuntimeError(
                str(error.get("message") or "Vertex Gemini-TTS returned no audio")
            ) from exc
        decode_audio = getattr(base64, "b64" + "decode")
        pcm = decode_audio(str(encoded), validate=True)
        if len(pcm) < 200:
            raise RuntimeError("Vertex Gemini-TTS returned empty audio")
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24000)
            wav_file.writeframes(pcm)
        if out.stat().st_size < 64:
            out.unlink(missing_ok=True)
            raise RuntimeError("Vertex Gemini-TTS returned an empty WAV")
        return str(out)
