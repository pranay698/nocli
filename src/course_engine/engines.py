from __future__ import annotations

from pathlib import Path

from google.cloud import speech

from .transcriber import format_timestamp


WHISPER_MODELS = {
    "whisper_tiny": "tiny",
    "whisper_small": "small",
    "whisper_large_turbo": "large-v3-turbo",
}


def transcribe_with_google(audio_uri: str, language_code: str) -> dict:
    client = speech.SpeechClient()
    audio = speech.RecognitionAudio(uri=audio_uri)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.MP3,
        language_code=language_code,
        enable_automatic_punctuation=True,
        enable_word_time_offsets=True,
        audio_channel_count=1,
    )
    operation = client.long_running_recognize(config=config, audio=audio)
    response = operation.result(timeout=7200)
    segments = []
    transcript_parts = []
    for result in response.results:
        if not result.alternatives:
            continue
        alternative = result.alternatives[0]
        text = alternative.transcript.strip()
        if not text:
            continue
        transcript_parts.append(text)
        start_seconds = None
        end_seconds = None
        if alternative.words:
            start_seconds = alternative.words[0].start_time.total_seconds()
            end_seconds = alternative.words[-1].end_time.total_seconds()
        segments.append(
            {
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "start": format_timestamp(start_seconds),
                "end": format_timestamp(end_seconds),
                "text": text,
                "confidence": alternative.confidence,
            }
        )
    return {"transcript": " ".join(transcript_parts), "segments": segments}


def offset_transcript_result(result: dict, offset_seconds: int) -> dict:
    adjusted_segments = []
    for segment in result.get("segments", []):
        adjusted = dict(segment)
        if adjusted.get("start_seconds") is not None:
            adjusted["start_seconds"] = adjusted["start_seconds"] + offset_seconds
            adjusted["start"] = format_timestamp(adjusted["start_seconds"])
        if adjusted.get("end_seconds") is not None:
            adjusted["end_seconds"] = adjusted["end_seconds"] + offset_seconds
            adjusted["end"] = format_timestamp(adjusted["end_seconds"])
        adjusted_segments.append(adjusted)
    return {
        **result,
        "segments": adjusted_segments,
    }


def combine_transcript_results(results: list[dict]) -> dict:
    transcript_parts = []
    segments = []
    detected_languages = []
    for result in results:
        if result.get("transcript"):
            transcript_parts.append(result["transcript"])
        segments.extend(result.get("segments", []))
        if result.get("detected_language"):
            detected_languages.append(result["detected_language"])
    combined = {
        "transcript": " ".join(transcript_parts),
        "segments": segments,
    }
    if detected_languages:
        combined["detected_language"] = detected_languages[0]
    return combined


def transcribe_with_whisper(audio_path: Path, engine: str, language_code: str) -> dict:
    from faster_whisper import WhisperModel

    model_name = WHISPER_MODELS[engine]
    device = "cuda" if _cuda_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    language = language_code.split("-")[0] if language_code else None
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
        beam_size=5,
    )
    output_segments = []
    transcript_parts = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        transcript_parts.append(text)
        output_segments.append(
            {
                "start_seconds": segment.start,
                "end_seconds": segment.end,
                "start": format_timestamp(segment.start),
                "end": format_timestamp(segment.end),
                "text": text,
                "confidence": None,
            }
        )
    return {
        "transcript": " ".join(transcript_parts),
        "segments": output_segments,
        "detected_language": getattr(info, "language", None),
    }


def _cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False
