#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频下载工具 - 支持 Bilibili / 抖音
用法:
  单个视频:         python downloader.py "https://..."
  博主全部视频:     python downloader.py --all "https://space.bilibili.com/xxxxx"
  指定清晰度:       python downloader.py --quality low "https://..."
  纯音频(提取文字): python downloader.py --quality audio "https://..."
"""

import argparse
import sys
import os
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import yt_dlp

DEFAULT_OUTPUT = str(Path.home() / "Videos" / "Downloaded")

BILIBILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}
DOUYIN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://www.douyin.com/",
}

# ── 清晰度预设 ──────────────────────────────────────────────────────────────
# best   最高画质，用于欣赏
# medium 720p，均衡
# low    360p，用于文字提取（有画面参考）
# audio  纯音频 mp3，最适合语音转文字，文件最小
QUALITY_PRESETS = {
    "best": {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "label": "最高画质",
    },
    "medium": {
        "format": (
            "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo[height<=720]+bestaudio"
            "/best[height<=720]/best"
        ),
        "merge_output_format": "mp4",
        "label": "720p",
    },
    "low": {
        "format": (
            "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo[height<=360]+bestaudio"
            "/best[height<=360]/best"
        ),
        "merge_output_format": "mp4",
        "label": "360p（适合文字提取）",
    },
    "audio": {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "merge_output_format": None,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }],
        "label": "纯音频 mp3（最适合语音转文字）",
    },
}


def detect_site(url: str) -> str:
    u = url.lower()
    if "bilibili.com" in u or "b23.tv" in u:
        return "bilibili"
    if "douyin.com" in u or "iesdouyin.com" in u or "tiktok.com" in u:
        return "douyin"
    return "auto"


def build_opts(output_dir: str, site: str, quality: str = "best",
               cookies_file: str = None, cookies_from_browser: str = None,
               is_playlist: bool = False, max_count: int = None,
               date_after: str = None) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    headers = BILIBILI_HEADERS if site == "bilibili" else DOUYIN_HEADERS
    preset = QUALITY_PRESETS[quality]

    # audio 模式用 .%(ext)s，视频模式固定 .mp4
    if quality == "audio":
        tmpl = str(out / "%(uploader)s" / "%(title).100B.%(ext)s")
    else:
        tmpl = str(out / "%(uploader)s" / "%(title).100B.mp4")

    opts = {
        "outtmpl": tmpl,
        "format": preset["format"],
        "concurrent_fragment_downloads": 4,
        "retries": 8,
        "fragment_retries": 8,
        "ignoreerrors": True,
        "http_headers": headers,
        "color": "never",
    }

    if preset.get("merge_output_format"):
        opts["merge_output_format"] = preset["merge_output_format"]
    if preset.get("postprocessors"):
        opts["postprocessors"] = preset["postprocessors"]

    if cookies_file and os.path.exists(cookies_file):
        opts["cookiefile"] = cookies_file
        print(f"[Cookie] 使用文件: {cookies_file}")
    elif cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
        print(f"[Cookie] 从浏览器读取: {cookies_from_browser}")

    if is_playlist:
        opts["download_archive"] = str(out / "downloaded.txt")
        if date_after:
            opts["dateafter"] = date_after
        if max_count:
            opts["playlistend"] = max_count

    if site == "bilibili":
        opts.setdefault("extractor_args", {})["bilibili"] = {
            "prefer_multi_flv": ["false"],
        }

    return opts


def print_video_info(info: dict):
    print("-" * 60)
    print(f"  标题: {info.get('title', '-')}")
    print(f"  作者: {info.get('uploader', '-')}")
    dur = info.get("duration", 0) or 0
    print(f"  时长: {int(dur) // 60}分{int(dur) % 60}秒")
    print(f"  网站: {info.get('extractor_key', '-')}")
    print("-" * 60)


def download_single(url: str, output_dir: str, quality: str = "best",
                    cookies_file: str = None, cookies_from_browser: str = None):
    site = detect_site(url)
    opts = build_opts(output_dir, site, quality=quality,
                      cookies_file=cookies_file,
                      cookies_from_browser=cookies_from_browser)

    label = QUALITY_PRESETS[quality]["label"]
    print(f"\n=== 下载视频 [{site}] 清晰度: {label} ===")

    info_opts = {**opts, "quiet": True, "no_warnings": True}
    try:
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                print_video_info(info)
    except Exception as e:
        print(f"[提示] 获取元数据失败: {e}")

    print(f"保存到: {output_dir}\n")
    with yt_dlp.YoutubeDL(opts) as ydl:
        code = ydl.download([url])

    print("\n" + ("=== 下载完成！===" if code == 0 else "=== 下载遇到问题，请检查上方日志 ==="))
    return code


def download_channel(url: str, output_dir: str, quality: str = "best",
                     cookies_file: str = None, cookies_from_browser: str = None,
                     max_count: int = None, date_after: str = None):
    site = detect_site(url)
    opts = build_opts(output_dir, site, quality=quality,
                      cookies_file=cookies_file,
                      cookies_from_browser=cookies_from_browser,
                      is_playlist=True,
                      max_count=max_count,
                      date_after=date_after)

    label = QUALITY_PRESETS[quality]["label"]
    print(f"\n=== 下载博主全部视频 [{site}] 清晰度: {label} ===")

    list_opts = {**opts, "quiet": True, "extract_flat": "in_playlist"}
    try:
        with yt_dlp.YoutubeDL(list_opts) as ydl:
            playlist = ydl.extract_info(url, download=False)
            if playlist and "entries" in playlist:
                entries = [e for e in (playlist["entries"] or []) if e]
                total = len(entries)
                print(f"发现 {total} 个视频（以下显示前10个）:")
                for i, e in enumerate(entries[:10], 1):
                    print(f"  {i:3d}. {e.get('title', '-')[:70]}")
                if total > 10:
                    print(f"  ... 共 {total} 个")
    except Exception as e:
        print(f"[提示] 获取列表时出错: {e}，将直接下载...")

    print(f"\n保存到: {output_dir}")
    print("已下载的视频将自动跳过（记录于 downloaded.txt）\n")

    with yt_dlp.YoutubeDL(opts) as ydl:
        code = ydl.download([url])

    print("\n=== 全部完成！===")
    return code


def main():
    parser = argparse.ArgumentParser(
        description="视频下载工具 — 支持 Bilibili / 抖音",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
清晰度说明:
  best   最高画质，用于欣赏（默认）
  medium 720p，均衡
  low    360p，适合提取文字（文件小，有画面）
  audio  纯音频 mp3，最适合语音转文字（文件最小）

示例:
  # 欣赏用，最高画质
  python downloader.py "https://www.bilibili.com/video/BV1NvRyBzEhq/"

  # 文字提取，只要音频
  python downloader.py --quality audio "https://www.bilibili.com/video/BV1NvRyBzEhq/"

  # 下载博主全部视频，低画质（批量提取文字时省空间）
  python downloader.py --all --quality low "https://space.bilibili.com/123456"

  # 下载抖音收藏夹所有视频，纯音频
  python douyin_favorites_playwright.py --quality audio --cookies cookies_douyin.txt
        """,
    )
    parser.add_argument("url", help="视频或博主主页 URL")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT,
                        help=f"下载目录（默认: {DEFAULT_OUTPUT}）")
    parser.add_argument("-q", "--quality", default="best",
                        choices=["best", "medium", "low", "audio"],
                        help="清晰度: best/medium/low/audio（默认: best）")
    parser.add_argument("--all", action="store_true", dest="download_all",
                        help="下载博主所有视频")
    parser.add_argument("--max", type=int, default=None, dest="max_count",
                        help="频道模式：最多下载几个")
    parser.add_argument("--after", default=None, dest="date_after",
                        help="频道模式：只下载该日期后的视频（YYYYMMDD）")
    parser.add_argument("--cookies", default=None,
                        help="Cookie 文件路径（Netscape 格式）")
    parser.add_argument("--browser", default=None,
                        choices=["chrome", "firefox", "edge", "safari", "brave", "chromium"],
                        help="从指定浏览器自动读取 Cookie")

    args = parser.parse_args()

    print("=" * 60)
    print("  视频下载工具  (基于 yt-dlp)")
    print("=" * 60)

    if args.download_all:
        download_channel(
            args.url, args.output,
            quality=args.quality,
            cookies_file=args.cookies,
            cookies_from_browser=args.browser,
            max_count=args.max_count,
            date_after=args.date_after,
        )
    else:
        download_single(
            args.url, args.output,
            quality=args.quality,
            cookies_file=args.cookies,
            cookies_from_browser=args.browser,
        )


if __name__ == "__main__":
    main()
