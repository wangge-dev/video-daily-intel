#!/usr/bin/env python3
"""抖音全能极速提取工具 - 1~2秒级提取视频元数据、页面简介与完整口播逐字稿

工作原理：
1. 极速音频流下钻 (yt-dlp -f ba/b)：不下载大视频，仅提取纯音频流 (几百KB)。
2. 本地神经网络加速 (mlx_whisper)：直接调用 Apple Silicon 统一内存/GPU，2秒内完成高精度语音转文字。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

VIDEO_AUDIO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".mp3", ".m4a", ".wav", ".aac", ".opus"}


def resolve_short_link(short_url: str) -> str:
    """把 v.douyin.com 短链解析成 www.douyin.com/video/<id>（yt-dlp 只认这个形式）。"""
    req = urllib.request.Request(
        short_url,
        headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            final = resp.geturl()
    except Exception:
        final = ""
    m = re.search(r"(?:/share/video/|/video/|modal_id=)(\d{6,})", final or short_url)
    if m:
        return f"https://www.douyin.com/video/{m.group(1)}"
    return short_url


def clean_url(text: str) -> str:
    match = re.search(r"https?://v\.douyin\.com/[a-zA-Z0-9\-_]+/?", text)
    if match:
        return resolve_short_link(match.group(0))
    match = re.search(r"https?://[a-zA-Z0-9\.\-_/]+(?:\?[a-zA-Z0-9_=&%-]*)?", text)
    return match.group(0) if match else text.strip()


def run_mlx_whisper(audio_path: Path) -> str:
    mlx_bin = shutil.which("mlx_whisper") or "/opt/homebrew/bin/mlx_whisper"
    if os.path.exists(mlx_bin):
        try:
            out_dir = audio_path.parent / "trans_out"
            out_dir.mkdir(exist_ok=True)
            cmd = [
                mlx_bin,
                str(audio_path),
                "--model", "mlx-community/whisper-large-v3-turbo",
                "--language", "zh",
                "--output-format", "txt",
                "--output-dir", str(out_dir),
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            txt_candidates = list(out_dir.glob("*.txt"))
            if txt_candidates:
                return txt_candidates[0].read_text(encoding="utf-8").strip()
        except Exception:
            pass

    try:
        import mlx_whisper
        res = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="zh")
        return res.get("text", "").strip()
    except Exception:
        pass

    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(audio_path), vad_filter=True, task="transcribe")
        text = "\n".join(s.text.strip() for s in segments if s.text.strip()).strip()
        if text:
            return text
    except Exception:
        pass

    try:
        import whisper
        model = whisper.load_model("base")
        res = model.transcribe(str(audio_path), language="zh")
        return res.get("text", "").strip()
    except Exception:
        pass

    return ""


def extract_douyin_fast(raw_url: str) -> dict:
    url = clean_url(raw_url)

    yt_dlp = shutil.which("yt-dlp")
    if not yt_dlp:
        return {"status": "error", "error": "未检测到 yt-dlp，请通过 brew install yt-dlp 安装。"}

    tmp_dir = Path(tempfile.mkdtemp(prefix="dy_fast_extract_"))
    try:
        audio_path = tmp_dir / "audio.wav"
        output_tmpl = str(tmp_dir / "media.%(ext)s")

        # Download audio & info
        cookie_args = ["--cookies-from-browser", "chrome"]
        dl_cmd = [
            yt_dlp,
            "-f", "ba/b",
            "--write-info-json",
            "-o", output_tmpl,
            "--no-playlist",
            "--ignore-errors",
            *cookie_args,
            "--", url
        ]
        res = subprocess.run(dl_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode != 0:
            dl_cmd_no_cookie = [
                yt_dlp,
                "-f", "ba/b",
                "--write-info-json",
                "-o", output_tmpl,
                "--no-playlist",
                "--ignore-errors",
                "--", url
            ]
            subprocess.run(dl_cmd_no_cookie, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        info_files = list(tmp_dir.glob("media*.info.json"))
        title = "未知标题"
        duration = 0
        desc = ""
        uploader = ""
        tags = []
        if info_files:
            try:
                info = json.loads(info_files[0].read_text(encoding="utf-8"))
                title = info.get("title") or info.get("fulltitle") or "抖音作品"
                duration = info.get("duration", 0)
                desc = info.get("description", "")
                uploader = info.get("uploader") or info.get("artist") or ""
                tags = info.get("tags", [])
            except Exception:
                pass

        media_files = [f for f in tmp_dir.glob("media*") if f.suffix.lower() in VIDEO_AUDIO_EXTS]
        if not media_files:
            return {"status": "error", "error": "无法下载该作品的音频流，可能是博主主页链接、视频已删除或链接私密。"}

        # Resample to 16k mono wav
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            subprocess.run(
                [ffmpeg, "-y", "-i", str(media_files[0]), "-vn", "-ac", "1", "-ar", "16000", str(audio_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

        # Transcribe with mlx_whisper
        transcript = ""
        if audio_path.exists() and audio_path.stat().st_size > 1000:
            transcript = run_mlx_whisper(audio_path)

        return {
            "status": "success",
            "title": title,
            "uploader": uploader,
            "duration_seconds": duration,
            "tags": tags,
            "description": desc,
            "transcript": transcript if transcript else desc,
            "url": url
        }

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="抖音极速文案与字幕提取工具")
    parser.add_argument("url", help="抖音视频分享链接或文本")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出完整结果")
    parser.add_argument("--output", "-o", help="输出到文件")
    args = parser.parse_args()

    res = extract_douyin_fast(args.url)

    if args.json:
        out_text = json.dumps(res, ensure_ascii=False, indent=2)
    else:
        if res.get("status") == "success":
            out_text = f"【标题】：{res.get('title')}\n"
            if res.get("uploader"):
                out_text += f"【作者】：{res.get('uploader')}\n"
            if res.get("duration_seconds"):
                out_text += f"【时长】：{res.get('duration_seconds')} 秒\n"
            out_text += f"\n【口播逐字稿】：\n{res.get('transcript')}\n"
        else:
            out_text = f"❌ 提取失败：{res.get('error')}"

    if args.output:
        Path(args.output).write_text(out_text, encoding="utf-8")
        print(f"已保存至：{args.output}")
    else:
        print(out_text)


if __name__ == "__main__":
    main()
