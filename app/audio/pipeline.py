from __future__ import annotations
#todo音频处理流水线核心模块
import json, math, os, subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf

import webrtcvad
from faster_whisper import WhisperModel
from langchain_core.documents import Document

from app.audio import audio_db
from app.es.es_audio_admin import upsert_audio_segments
from app.workflows.deps import get_audio_vs

ProgressFn = Callable[[int, str], None]

TARGET_SR = int(os.getenv("AUDIO_SR", "16000"))# 目标采样率：默认16000Hz
TARGET_CH = int(os.getenv("AUDIO_CH", "1"))# 目标声道数：默认1（单声道）

VAD_MODE = int(os.getenv("VAD_MODE", "2"))# VAD敏感度：0~3，越大越严格
VAD_FRAME_MS = int(os.getenv("VAD_FRAME_MS", "30"))# VAD帧长：默认30ms（webrtcvad常用10/20/30）
VAD_PADDING_MS = int(os.getenv("VAD_PADDING_MS", "300"))# 语音段前后扩展：默认300ms，防止切太死
VAD_MIN_SPEECH_MS = int(os.getenv("VAD_MIN_SPEECH_MS", "500")) # 最短语音段：默认>=500ms才保留
VAD_MERGE_GAP_MS = int(os.getenv("VAD_MERGE_GAP_MS", "250"))# 合并间隔：相邻段间隔<=250ms则合并

ASR_MODEL = os.getenv("ASR_MODEL", "base") # Whisper模型名/路径：默认base
ASR_DEVICE = os.getenv("ASR_DEVICE", "cpu") # 推理设备：默认cpu（也可能是cuda）
ASR_COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "int8")# 计算精度：cpu常用int8省资源

MAX_CHUNK_MS = int(os.getenv("AUDIO_MAX_CHUNK_MS", "25000"))# 单chunk最大时长：默认25s，超过强制切
MIN_CHUNK_MS = int(os.getenv("AUDIO_MIN_CHUNK_MS", "6000"))# 单chunk最小时长阈值：默认6s，满足且遇标点可切
MAX_CHARS_PER_CHUNK = int(os.getenv("AUDIO_MAX_CHARS_PER_CHUNK", "900")) # 单chunk最大字数：默认900，超过截断

PUNCT_END = set("。.!?！？；;")# 认为“句子结束”的标点集合：用于断句切chunk

MAX_SPEECH_SEGMENTS = int(os.getenv("AUDIO_MAX_SPEECH_SEGMENTS", "2000"))# VAD段上限：防止噪声导致段数爆炸

#「防御式编程的第一层」——（类型层防御）
@dataclass# 生成init/repr等，方便存取字段
class SpeechSeg:# 表示“语音活动段”的起止时间
    start_ms: int
    end_ms: int


@dataclass
class AsrSeg:# 表示“带文本”的识别片段（或合并chunk）
    start_ms: int
    end_ms: int
    text: str# 该段识别文本

#这是一个“边界收敛函数”：在调用外部回调前，统一收敛类型和状态(回调防御）
def _prog(cb: Optional[ProgressFn], p: int, m: str) -> None:
    """统一进度汇报：若传入回调则调用。"""  # 把进度与消息交给外部（如更新DB）
    if cb:
        cb(int(p), str(m))# 调用回调：强制转int/str，避免外部类型不一致

#（外部命令防御）
def _run(cmd: List[str]) -> None:
    """运行外部命令（ffmpeg等），失败则抛异常并带stderr。"""
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)# 执行命令，捕获stdout/stderr为文本
    if p.returncode != 0: # 如果退出码非0表示命令失败
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\nSTDERR:\n{p.stderr[:4000]}")# 抛异常并截断stderr避免太长

#这个函数就是把音频转成 16kHz 单声道 WAV，是 ASR 的标准预处理流程。
def transcode_to_wav_16k_mono(src: Path, dst: Path) -> None:
    """把任意音频转为16kHz单声道WAV，写到dst。"""  # 统一格式给VAD/ASR
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "/home/ldm/下载/ffmpeg-master-latest-linux64-gpl/bin/ffmpeg", "-y", # -y覆盖输出文件
        "-i", str(src), # 输入文件路径
        "-ac", str(TARGET_CH),# 设定声道数（1）
        "-ar", str(TARGET_SR),# 设定采样率（16000）
        "-f", "wav",# 输出格式强制为wav
        str(dst),# 输出文件路径
    ])

#这个函数可以安全地返回音频文件的时长（毫秒），并处理了 ffprobe 出错或 JSON 缺失的情况。
def ffprobe_duration_ms(path: Path) -> int:
    """用ffprobe读取音频时长（毫秒）。"""
    p = subprocess.run(# 执行ffprobe获取duration
        ["/home/ldm/下载/ffmpeg-master-latest-linux64-gpl/bin/ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], # 输出json，包含duration
        stdout=subprocess.PIPE,# 捕获标准输出
        stderr=subprocess.PIPE,# 捕获错误输出
        text=True,# 用文本模式读取
    )
    if p.returncode != 0:# 若ffprobe失败
        raise RuntimeError(f"ffprobe failed: {p.stderr[:2000]}")# 抛异常并截断stderr
    data = json.loads(p.stdout or "{}")# 解析stdout为json；若为空则用空对象
    dur = float((data.get("format") or {}).get("duration") or 0.0)# 读取format.duration（秒），缺失则0
    return int(dur * 1000) # 秒转毫秒并返回整数

#你这个函数 _read_wav_mono_16k 是用来读取 wav 音频文件，并保证它是 单声道 (mono) 且采样率为 16kHz（假设 TARGET_SR = 16000），返回一个 np.ndarray 的浮点数组
def _read_wav_mono_16k(path: Path) -> np.ndarray:
    """读取16kHz wav并确保单声道，返回float32样本数组。"""  #给VAD/ASR提供统一numpy数组
    x, sr = sf.read(str(path), dtype="float32", always_2d=False) # 读取音频：x为样本，sr为采样率；输出float32
    if sr != TARGET_SR:# 若采样率不是目标16k
        raise RuntimeError(f"wav sample rate not {TARGET_SR}: {sr}")
    if isinstance(x, np.ndarray) and x.ndim == 2:# 若是二维数组（多声道）
        x = x.mean(axis=1) # 对声道取平均，混成单声道
    return np.asarray(x, dtype=np.float32)# 强制转为float32的一维数组返回

#你这段代码 _float_to_pcm16_bytes 的作用很直接：把 浮点型音频数组 转成 16-bit PCM 字节流
def _float_to_pcm16_bytes(x: np.ndarray) -> bytes:
    """把[-1,1]浮点样本转为PCM16字节流（webrtcvad需要）。"""  # webrtcvad输入必须是16-bit PCM bytes
    x = np.clip(x, -1.0, 1.0)
    pcm = (x * 32767.0).astype(np.int16)
    return pcm.tobytes()

#是一个 基于 WebRTC VAD 的语音活动检测 (Voice Activity Detection, VAD) 实现，它能把音频分割成若干说话片段。
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

#它的作用是 加载一个 Whisper ASR 模型实例，用于语音识别。
def _load_asr_model() -> WhisperModel:
    return WhisperModel(
        ASR_MODEL,
        device=ASR_DEVICE,
        compute_type=ASR_COMPUTE_TYPE,
    )

# transcribe_segments 是一个 基于 Whisper ASR 模型的语音片段转文字函数，它的功能是把 VAD 得到的语音片段逐段转成文字
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

# _ends_with_punct 是用来判断一个字符串 是否以标点符号结尾 的
def _ends_with_punct(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    return t[-1] in PUNCT_END

# merge_asr_to_chunks 是用来 把连续的 ASR 片段 (AsrSeg) 合并成更合理的文本块，既控制时间跨度，也控制字符长度，同时尽量在句末标点处分割。
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

# _vs_add 是一个 向向量数据库（Vector Store）添加文档的兼容封装函数，可以处理不同类型的向量存储接口
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

#_db_replace_segments 是一个 向音频数据库更新语音片段的兼容封装，可以根据不同的数据库接口调用不同方法，保证统一操作。
def _db_replace_segments(audio_id: str, rows: List[Dict[str, Any]]) -> None:
    if hasattr(audio_db, "replace_audio_segments"):
        audio_db.replace_audio_segments(audio_id, rows)
        return

    if hasattr(audio_db, "delete_audio_segments") and hasattr(audio_db, "insert_audio_segments_bulk"):
        audio_db.delete_audio_segments(audio_id)
        audio_db.insert_audio_segments_bulk(rows)
        return

    raise AttributeError("audio_db.replace_audio_segments not found (and no fallback delete/insert found)")

rows: List[Dict[str, Any]] = []
docs: List[Document] = []
ids: List[str] = []
#run_audio_ingest_pipeline 是一个 完整的音频入库/处理流水线，它把一个原始音频文件经过 转码 → VAD → ASR → 文本合并 → 数据库写入 → 向量化 一条龙处理，最后返回处理信息。
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

    _prog(on_progress, 96, "write es index")
    try:
        upsert_audio_segments(audio_id=audio_id, rows=rows)
    except Exception as e:
        # ES失败不应阻塞向量入库
        print(f"[warn] es upsert failed: {e}")

    _prog(on_progress, 100, "done")

    return {
        "audio_id": audio_id,
        "duration_ms": int(duration_ms),
        "segments": int(len(chunks)),
        "language": language,
        "wav_path": str(wav_path),
    }
