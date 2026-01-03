from __future__ import annotations

import subprocess
from pathlib import Path

from app.ingestion.asr import ASR


def ensure_dir(p: Path) -> None:  # 确保路径存在
    p.mkdir(parents=True, exist_ok=True)


def ffprobe_duration_ms(src: Path) -> int:  # 这段音频的时长，以毫秒为单位计数
    cmd = [
        "/home/ldm/下载/ffmpeg-master-latest-linux64-gpl/bin/ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(src),
    ]
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode("utf-8").strip()
    if not out:
        return 0
    sec = float(out)
    return int(sec * 1000)  # 这段音频的时长，以毫秒为单位计数


def transcode_to_wav_16k_mono(src: Path, dst: Path) -> None:
    ensure_dir(dst.parent)
    cmd = [
        "/home/ldm/下载/ffmpeg-master-latest-linux64-gpl/bin/ffmpeg",
        "-y",
        "-i", str(src),
        "-ac", "1",
        "-ar", "16000",
        "-vn",
        str(dst),
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__=='__main__':
    print(ffprobe_duration_ms(Path('/home/ldm/下载/123.mp3')))
    transcode_to_wav_16k_mono(Path('/home/ldm/下载/123.mp3'), Path('/home/ldm/下载/123.wav'))
if __name__ == "__main__":
    segs, lang = ASR().transcribe("/home/ldm/下载/123.wav")
    for s in segs:
        print(s)
    print(lang)