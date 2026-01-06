from __future__ import annotations

import json, math, os, subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf

import webrtcvad
from faster_whisper import WhisperModel
from langchain_core.documents import Document

from app.db import audio_db
from app.workflows.deps import get_audio_vs

ProgressFn = Callable[[int, str], None]

TARGET_SR = int(os.getenv("AUDIO_SR", "16000"))
TARGET_CH = int(os.getenv("AUDIO_CH", "1"))

VAD_MODE = int(os.getenv("VAD_MODE", "2"))
VAD_FRAME_MS = int(os.getenv("VAD_FRAME_MS", "30"))
VAD_PADDING_MS = int(os.getenv("VAD_PADDING_MS", "300"))
VAD_MIN_SPEECH_MS = int(os.getenv("VAD_MIN_SPEECH_MS", "500"))
VAD_MERGE_GAP_MS = int(os.getenv("VAD_MERGE_GAP_MS", "250"))

ASR_MODEL = os.getenv("ASR_MODEL", "base")
ASR_DEVICE = os.getenv("ASR_DEVICE", "cpu")
ASR_COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "int8")

MAX_CHUNK_MS = int(os.getenv("AUDIO_MAX_CHUNK_MS", "25000"))
MIN_CHUNK_MS = int(os.getenv("AUDIO_MIN_CHUNK_MS", "6000"))
MAX_CHARS_PER_CHUNK = int(os.getenv("AUDIO_MAX_CHARS_PER_CHUNK", "900"))

PUNCT_END = set("。.!?！？；;")

MAX_SPEECH_SEGMENTS = int(os.getenv("AUDIO_MAX_SPEECH_SEGMENTS", "2000"))


@dataclass
class SpeechSeg:
    start_ms: int
    end_ms: int


@dataclass
class AsrSeg:
    start_ms: int
    end_ms: int
    text: str


def _prog(cb: Optional[ProgressFn], p: int, m: str) -> None:
    if cb:
        cb(int(p), str(m))


def _run(cmd: List[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\nSTDERR:\n{p.stderr[:4000]}")


def transcode_to_wav_16k_mono(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "/Users/peter/Downloads/ffmpeg", "-y",
        "-i", str(src),
        "-ac", str(TARGET_CH),
        "-ar", str(TARGET_SR),
        "-f", "wav",
        str(dst),
    ])


def ffprobe_duration_ms(path: Path) -> int:
    p = subprocess.run(
        ["/Users/peter/Downloads/ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr[:2000]}")
    data = json.loads(p.stdout or "{}")
    dur = float((data.get("format") or {}).get("duration") or 0.0)
    return int(dur * 1000)

def _read_wav_mono_16k(path: Path) -> np.ndarray:
    x, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if sr != TARGET_SR:
        raise RuntimeError(f"wav sample rate not {TARGET_SR}: {sr}")
    if isinstance(x, np.ndarray) and x.ndim == 2:
        x = x.mean(axis=1)
    return np.asarray(x, dtype=np.float32)


def _float_to_pcm16_bytes(x: np.ndarray) -> bytes:
    x = np.clip(x, -1.0, 1.0)
    pcm = (x * 32767.0).astype(np.int16)
    return pcm.tobytes()


def detect_speech_segments(wav_path: Path) -> List[SpeechSeg]:
    x = _read_wav_mono_16k(wav_path)
    pcm_bytes = _float_to_pcm16_bytes(x)

    vad = webrtcvad.Vad(VAD_MODE)

    frame_len = int(TARGET_SR * (VAD_FRAME_MS / 1000.0))  # samples
    frame_bytes = frame_len * 2  # int16
    total_frames = len(pcm_bytes) // frame_bytes

    def is_speech(i: int) -> bool:
        start = i * frame_bytes
        chunk = pcm_bytes[start:start + frame_bytes]
        if len(chunk) < frame_bytes:
            return False
        return vad.is_speech(chunk, sample_rate=TARGET_SR)

    speech_frames: List[Tuple[int, int]] = []
    in_speech = False
    seg_start = 0

    for i in range(total_frames):
        sp = is_speech(i)
        if sp and not in_speech:
            in_speech = True
            seg_start = i
        elif (not sp) and in_speech:
            in_speech = False
            speech_frames.append((seg_start, i))

    if in_speech:
        speech_frames.append((seg_start, total_frames))

    pad_frames = int(math.ceil(VAD_PADDING_MS / VAD_FRAME_MS))
    out: List[SpeechSeg] = []
    for a, b in speech_frames:
        a2 = max(0, a - pad_frames)
        b2 = min(total_frames, b + pad_frames)
        start_ms = int(a2 * VAD_FRAME_MS)
        end_ms = int(b2 * VAD_FRAME_MS)
        if (end_ms - start_ms) >= VAD_MIN_SPEECH_MS:
            out.append(SpeechSeg(start_ms=start_ms, end_ms=end_ms))

    if not out:
        return []

    merged: List[SpeechSeg] = [out[0]]
    for s in out[1:]:
        prev = merged[-1]
        if s.start_ms - prev.end_ms <= VAD_MERGE_GAP_MS:
            prev.end_ms = max(prev.end_ms, s.end_ms)
        else:
            merged.append(s)

    if len(merged) > MAX_SPEECH_SEGMENTS:
        merged = merged[:MAX_SPEECH_SEGMENTS]

    return merged


def _load_asr_model() -> WhisperModel:
    return WhisperModel(
        ASR_MODEL,
        device=ASR_DEVICE,
        compute_type=ASR_COMPUTE_TYPE,
    )


def transcribe_segments(
    wav_path: Path,
    speech: List[SpeechSeg],
    *,
    language: Optional[str],
    on_progress: Optional[ProgressFn],
) -> List[AsrSeg]:
    if not speech:
        return []

    x = _read_wav_mono_16k(wav_path)
    model = _load_asr_model()

    out: List[AsrSeg] = []
    for idx, seg in enumerate(speech):
        # slice by samples
        s0 = int(seg.start_ms * TARGET_SR / 1000)
        s1 = int(seg.end_ms * TARGET_SR / 1000)
        s0 = max(0, min(len(x), s0))
        s1 = max(0, min(len(x), s1))
        if s1 <= s0:
            continue

        clip = x[s0:s1]
        segments, info = model.transcribe(
            clip,
            language=language,
            vad_filter=False,
            beam_size=1,
            condition_on_previous_text=False,
        )

        pct = 20 + int(60 * (idx + 1) / max(1, len(speech)))
        _prog(on_progress, pct, f"asr {idx+1}/{len(speech)}")

        for s in segments:
            start_ms = seg.start_ms + int(float(s.start) * 1000)
            end_ms = seg.start_ms + int(float(s.end) * 1000)
            text = (s.text or "").strip()
            if not text:
                continue
            out.append(AsrSeg(start_ms=start_ms, end_ms=max(end_ms, start_ms + 1), text=text))

    out.sort(key=lambda t: (t.start_ms, t.end_ms))
    return out

def _ends_with_punct(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    return t[-1] in PUNCT_END


def merge_asr_to_chunks(asr: List[AsrSeg]) -> List[AsrSeg]:
    if not asr:
        return []

    chunks: List[AsrSeg] = []
    cur_start = asr[0].start_ms
    cur_end = asr[0].end_ms
    buf: List[str] = [asr[0].text]

    def flush(force: bool = False) -> None:
        nonlocal cur_start, cur_end, buf
        txt = " ".join([b.strip() for b in buf if b.strip()]).strip()
        if not txt:
            buf = []
            return
        if len(txt) > MAX_CHARS_PER_CHUNK:
            txt = txt[:MAX_CHARS_PER_CHUNK]
        chunks.append(AsrSeg(start_ms=cur_start, end_ms=cur_end, text=txt))
        buf = []

    for s in asr[1:]:
        next_end = max(cur_end, s.end_ms)
        next_txt = (buf[-1] if buf else "")
        span = next_end - cur_start

        buf.append(s.text)
        cur_end = next_end

        span = cur_end - cur_start
        if span >= MAX_CHUNK_MS:
            flush(force=True)
            cur_start = s.start_ms
            cur_end = s.end_ms
            buf = [s.text]
            continue

        if span >= MIN_CHUNK_MS and _ends_with_punct(s.text):
            flush()
            cur_start = s.start_ms
            cur_end = s.end_ms
            buf = [s.text]

    if buf:
        flush(force=True)

    chunks.sort(key=lambda t: (t.start_ms, t.end_ms))
    return chunks

def _vs_add(vs: Any, docs: List[Document], ids: List[str]) -> None:
    if hasattr(vs, "add_documents"):
        vs.add_documents(docs, ids=ids)
        return
    texts = [d.page_content for d in docs]
    metas = [d.metadata for d in docs]
    if hasattr(vs, "add_texts"):
        vs.add_texts(texts, metadatas=metas, ids=ids)
        return
    raise RuntimeError("Vectorstore does not support add_documents/add_texts")


def _db_replace_segments(audio_id: str, rows: List[Dict[str, Any]]) -> None:
    if hasattr(audio_db, "replace_audio_segments"):
        audio_db.replace_audio_segments(audio_id, rows)
        return

    if hasattr(audio_db, "delete_audio_segments") and hasattr(audio_db, "insert_audio_segments_bulk"):
        audio_db.delete_audio_segments(audio_id)
        audio_db.insert_audio_segments_bulk(rows)
        return

    raise AttributeError("audio_db.replace_audio_segments not found (and no fallback delete/insert found)")

def run_audio_ingest_pipeline(
    *,
    audio_id: str,
    raw_path: Path,
    original_filename: str,
    visibility: str,
    language: Optional[str],
    wav_dir: Path,
    on_progress: Optional[ProgressFn] = None,
) -> Dict[str, Any]:
    if not raw_path.exists():
        raise FileNotFoundError(str(raw_path))

    _prog(on_progress, 1, "start")

    wav_dir.mkdir(parents=True, exist_ok=True)
    wav_path = wav_dir / f"{audio_id}.wav"

    _prog(on_progress, 5, "transcoding")
    transcode_to_wav_16k_mono(raw_path, wav_path)

    duration_ms = ffprobe_duration_ms(wav_path)

    _prog(on_progress, 10, "vad")
    speech = detect_speech_segments(wav_path)

    _prog(on_progress, 15, f"vad segments={len(speech)}")
    asr = transcribe_segments(wav_path, speech, language=language, on_progress=on_progress)

    _prog(on_progress, 85, f"asr segments={len(asr)}")
    chunks = merge_asr_to_chunks(asr)

    _prog(on_progress, 88, f"chunks={len(chunks)}")

    rows: List[Dict[str, Any]] = []
    docs: List[Document] = []
    ids: List[str] = []

    for i, c in enumerate(chunks):
        seg_id = f"{audio_id}:{i}"
        start_ms = int(c.start_ms)
        end_ms = int(c.end_ms)
        text = (c.text or "").strip()

        rows.append({
            "audio_id": audio_id,
            "segment_idx": i,
            "segment_id": seg_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": text,
            "visibility": visibility,
        })

        meta = {
            "audio_id": audio_id,
            "segment_id": seg_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "visibility": visibility,
            "original_filename": original_filename,
        }
        docs.append(Document(page_content=text, metadata=meta))
        ids.append(seg_id)

    _prog(on_progress, 90, "write db segments")
    _db_replace_segments(audio_id, rows)

    _prog(on_progress, 93, "write vectors")
    vs = get_audio_vs()
    _vs_add(vs, docs, ids)

    _prog(on_progress, 100, "done")

    return {
        "audio_id": audio_id,
        "duration_ms": int(duration_ms),
        "segments": int(len(chunks)),
        "language": language,
        "wav_path": str(wav_path),
    }
