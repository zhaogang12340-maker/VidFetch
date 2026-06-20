#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 Playwright 打开抖音收藏夹页面，拦截 API 响应获取全部视频 ID，再用 yt-dlp 下载。
用法: python douyin_favorites_playwright.py --cookies cookies_douyin.txt -o C:\Videos\收藏夹
"""
import sys, io, os, time, json, argparse, http.cookiejar, asyncio
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import yt_dlp
from playwright.async_api import async_playwright

DOUYIN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://www.douyin.com/",
}

SEC_UID = "YOUR_SEC_UID"
FAV_URL = f"https://www.douyin.com/user/{SEC_UID}?showTab=favorite_collection"


def load_cookies_for_playwright(cookie_file: str) -> list:
    """将 Netscape cookie 文件转为 Playwright 格式。"""
    jar = http.cookiejar.MozillaCookieJar(cookie_file)
    jar.load(ignore_discard=True, ignore_expires=True)
    result = []
    for c in jar:
        if "douyin" not in c.domain:
            continue
        if not c.name or not isinstance(c.value, str):
            continue
        result.append({
            "name": str(c.name),
            "value": str(c.value) if c.value is not None else "",
            "domain": c.domain if c.domain.startswith(".") else "." + c.domain,
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": False,
            "sameSite": "Lax",
        })
    return result


async def collect_video_ids(cookie_file: str) -> list:
    videos = []
    seen_ids = set()

    def on_response(resp):
        if "listcollect" in resp.url or "collect" in resp.url and "aweme" in resp.url:
            print(f"  [API] {resp.url[:80]}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,   # 有界面，方便观察
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=DOUYIN_HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )

        # 注入 Cookie
        playwright_cookies = load_cookies_for_playwright(cookie_file)
        await context.add_cookies(playwright_cookies)
        print(f"已注入 {len(playwright_cookies)} 个 Cookie")

        page = await context.new_page()

        # 拦截 API 响应
        captured = []

        async def handle_response(response):
            url = response.url
            if ("listcollection" in url or "aweme/favorite" in url) and response.status == 200:
                try:
                    body = await response.json()
                    items = body.get("aweme_list") or []
                    for item in items:
                        vid_id = item.get("aweme_id", "")
                        title  = (item.get("desc") or "").strip() or vid_id
                        if vid_id and vid_id not in seen_ids:
                            seen_ids.add(vid_id)
                            captured.append({"id": vid_id, "title": title})
                            print(f"  发现: {title[:50]}")
                except Exception:
                    pass

        page.on("response", handle_response)

        print(f"\n正在打开收藏夹页面...")
        try:
            await page.goto(FAV_URL, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            pass
        await asyncio.sleep(5)

        print(f"\n当前页面: {page.url}")
        print("\n滚动加载更多视频...")
        prev_count = 0
        no_change_times = 0

        while no_change_times < 5:
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            await asyncio.sleep(3)

            current_count = len(captured)
            if current_count == prev_count:
                no_change_times += 1
            else:
                no_change_times = 0
            prev_count = current_count
            print(f"  已收集 {current_count} 个视频", end="\r")

        print(f"\n\n共获取 {len(captured)} 个视频")
        videos = captured

        await context.close()
        await browser.close()

    return videos


QUALITY_PRESETS = {
    "best": {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "label": "最高画质",
    },
    "medium": {
        "format": (
            "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo[height<=720]+bestaudio/best[height<=720]/best"
        ),
        "merge_output_format": "mp4",
        "label": "720p",
    },
    "low": {
        "format": (
            "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo[height<=360]+bestaudio/best[height<=360]/best"
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


def download_videos(videos: list, cookies_file: str, output_dir: str, quality: str = "best"):
    os.makedirs(output_dir, exist_ok=True)
    archive = os.path.join(output_dir, "downloaded.txt")
    preset = QUALITY_PRESETS[quality]

    is_audio = quality == "audio"
    quality_tag = "_audio" if is_audio else "_%(height)sp"
    tmpl = os.path.join(output_dir, f"%(title).80B{quality_tag}.%(ext)s")

    opts = {
        "outtmpl": tmpl,
        "format": preset["format"],
        "cookiefile": cookies_file,
        "download_archive": archive,
        "concurrent_fragment_downloads": 4,
        "retries": 5,
        "ignoreerrors": True,
        "http_headers": DOUYIN_HEADERS,
    }
    if preset.get("merge_output_format"):
        opts["merge_output_format"] = preset["merge_output_format"]
    if preset.get("postprocessors"):
        opts["postprocessors"] = preset["postprocessors"]

    total = len(videos)
    for i, v in enumerate(videos, 1):
        url = f"https://www.douyin.com/video/{v['id']}"
        print(f"\n[{i}/{total}] {v['title'][:60]}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        time.sleep(0.5)


async def main_async(args):
    print("=" * 60)
    print("  抖音收藏夹下载器（Playwright 版）")
    print("=" * 60)

    label = QUALITY_PRESETS[args.quality]["label"]
    print(f"清晰度: {label}")

    videos = await collect_video_ids(args.cookies)

    if not videos:
        print("\n[!] 未能获取视频列表")
        print("    可能原因：Cookie 已失效，或收藏夹为空，或页面结构已变化")
        sys.exit(1)

    print(f"\n开始下载 {len(videos)} 个视频 -> {args.output}")
    download_videos(videos, args.cookies, args.output, quality=args.quality)
    print("\n=== 全部完成！===")


def main():
    parser = argparse.ArgumentParser(
        description="下载抖音收藏夹（Playwright 版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
清晰度说明:
  best   最高画质，用于欣赏（默认）
  medium 720p
  low    360p，适合提取文字
  audio  纯音频 mp3，最适合语音转文字

示例:
  python douyin_favorites_playwright.py --cookies cookies_douyin.txt
  python douyin_favorites_playwright.py --quality audio --cookies cookies_douyin.txt
  python douyin_favorites_playwright.py --quality low -o D:/Videos --cookies cookies_douyin.txt
        """,
    )
    parser.add_argument("--cookies", default="cookies_douyin.txt")
    parser.add_argument("-o", "--output", default="C:/VideoDownloader/Downloads/抖音收藏夹")
    parser.add_argument("-q", "--quality", default="best",
                        choices=["best", "medium", "low", "audio"],
                        help="清晰度: best/medium/low/audio（默认: best）")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
