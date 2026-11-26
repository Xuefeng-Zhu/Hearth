import base64
import re

from .connectors import ConnectorError
from .gateway_tools import redact_text
from .storage import HearthError

MAX_AUDIO = 8 * 1024 * 1024
WHISPER_PATH = "hf-inference/models/openai/whisper-large-v3-turbo"


def is_mp3_frame(data):
    return len(data) > 3 and not data.startswith(b"\xff\xfe") and data[0] == 0xff and data[1] & 0xe0 == 0xe0 and (
        data[1] & 0x18 != 0x08 and data[1] & 0x06 and data[2] & 0xf0 not in (0, 0xf0) and data[2] & 0x0c != 0x0c
    )


AUDIO_TYPES = {
    "audio/webm": lambda data: data.startswith(b"\x1a\x45\xdf\xa3"),
    "audio/ogg": lambda data: data.startswith(b"OggS"),
    "audio/mp4": lambda data: data[4:8] == b"ftyp",
    "audio/wav": lambda data: data.startswith(b"RIFF") and data[8:12] == b"WAVE",
    "audio/x-wav": lambda data: data.startswith(b"RIFF") and data[8:12] == b"WAVE",
}
ATTACHMENT_AUDIO_TYPES = {
    **AUDIO_TYPES, "audio/mpeg": lambda data: data.startswith(b"ID3") or is_mp3_frame(data),
    "audio/flac": lambda data: data.startswith(b"fLaC"),
}


class VoiceError(HearthError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def clean_transcript(text):
    if not isinstance(text, str):
        raise VoiceError("The transcription service returned an unreadable reply.", 502)
    cleaned = redact_text(text.strip())[:4000]
    if not cleaned:
        raise VoiceError("No speech was detected. Try speaking closer to the microphone.", 422)
    return cleaned


def transcribe(gateway, connection, data, content_type, language):
    if not connection:
        raise VoiceError("Connect Hugging Face in Settings → Connections or choose Browser in Settings → Voice.", 409)
    if not ATTACHMENT_AUDIO_TYPES[content_type](data):
        raise VoiceError("The recording does not match its audio format.", 415)
    if language != "auto" and not re.fullmatch(r"[a-z]{2,3}", language):
        raise VoiceError("Choose a supported transcription language.")
    try:
        if language == "auto":
            if content_type == "audio/x-wav":
                content_type = "audio/wav"
            result = gateway.json(connection, WHISPER_PATH, data, {"Content-Type": content_type}, timeout=50)
        else:
            # HF's parameterized ASR request encodes audio in JSON. Auto can send native bytes.
            body = {"inputs": base64.b64encode(data).decode("ascii"),
                    "parameters": {"generation_parameters": {"language": language}}}
            result = gateway.json(connection, WHISPER_PATH, body, timeout=50)
    except ConnectorError as error:
        if error.status in (401, 403):
            raise VoiceError("Hugging Face denied transcription. Check the connector’s access in Fly.", 502) from None
        if error.status in (400, 413, 415, 422):
            raise VoiceError("Whisper could not decode the recording or use the selected language.", 422) from None
        if error.status == 429:
            raise VoiceError("Hugging Face is rate-limiting transcription. Try again shortly.", 429) from None
        if error.status in (408, 503, 504):
            raise VoiceError("Whisper is temporarily unavailable. Try again shortly.", 503) from None
        raise VoiceError("Hearth could not reach Whisper through the Hugging Face connection.", 502) from None
    return clean_transcript(result.get("text"))
