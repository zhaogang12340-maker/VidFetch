#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载抖音某博主的所有作品（Playwright 版）
用法:
  python douyin_user_playwright.py --url "https://www.douyin.com/user/MS4wLjAB..."
  python douyin_user_playwright.py --url "..." --quality low -o D:/Videos
"""
import sys, io, os, time, json, argparse, http.cookiejar, asyncio, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import yt_dlp
from playwright.async_api import async_playwright

DOUYIN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://www.douyin.com/",
}

QUALITY_PRESETS = {
    "best":   {"format": "bestvideo+bestaudio/best",                                      "label": "最高画质", "suffix": "_最高画质"},
    "4k":     {"format": "bestvideo[height<=2160]+bestaudio/best[height<=2160]/bestvideo+bestaudio/best", "label": "4K",      "suffix": "_4K"},
    "1080p":  {"format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/bestvideo+bestaudio/best", "label": "1080p",   "suffix": "_1080p"},
    "720p":   {"format": "bestvideo[height<=720]+bestaudio/best[height<=720]/bestvideo+bestaudio/best",   "label": "720p",    "suffix": "_720p"},
    "low":    {"format": "bestvideo[height<=360]+bestaudio/best[height<=360]/worst+bestaudio/worst/best", "label": "360p",    "suffix": "_360p"},
    "audio":  {"format": "bestaudio/best", "label": "MP3音频", "suffix": "_audio",
               "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}]},
}


def extract_sec_uid(url: str) -> str:
    m = re.search(r'douyin\.com/user/([^?&/]+)', url)
    if m:
        return m.group(1)
    raise ValueError(f"无法从 URL 中提取 sec_uid: {url}")


def load_cookies(cookie_file: str) -> list:
    jar = http.cookiejar.MozillaCookieJar(cookie_file)
    jar.load(ignore_discard=True, ignore_expires=True)
    result = []
    for c in jar:
        if "douyin" not in c.domain:
            continue
        if not c.name or c.value is None:
            continue
        result.append({
            "name": str(c.name),
            "value": str(c.value),
            "domain": c.domain if c.domain.startswith(".") else "." + c.domain,
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": False,
            "sameSite": "Lax",
        })
    return result


async def collect_user_videos(user_url: str, cookie_file: str) -> list:
    sec_uid = extract_sec_uid(user_url)
    page_url = f"https://www.douyin.com/user/{sec_uid}"
    videos = []
    seen_ids = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=DOUYIN_HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        cookies = load_cookies(cookie_file)
        await context.add_cookies(cookies)
        print(f"已注入 {len(cookies)} 个 Cookie")

        page = await context.new_page()

        async def handle_response(response):
            url = response.url
            # 拦截用户作品列表 API
            if ("aweme/v1/web/aweme/post" in url or
                "aweme/v1/web/user/profile/other" in url) and response.status == 200:
                try:
                    body = await response.json()
                    items = body.get("aweme_list") or []
                    for item in items:
                        vid_id = item.get("aweme_id", "")
                        title = (item.get("desc") or "").strip() or vid_id
                        if vid_id and vid_id not in seen_ids:
                            seen_ids.add(vid_id)
                            videos.append({"id": vid_id, "title": title})
                            print(f"  发现: {title[:50]}")
                except Exception:
                    pass

        page.on("response", handle_response)

        print(f"\n正在打开用户主页: {page_url}")
        try:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            pass
        await asyncio.sleep(5)

        print("\n滚动加载全部视频...")
        prev_count = 0
        no_change = 0
        while no_change < 6:
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            await asyncio.sleep(2.5)
            cur = len(videos)
            if cur == prev_count:
                no_change += 1
            else:
                no_change = 0
            prev_count = cur
            print(f"  已收集 {cur} 个视频", end="\r")

        print(f"\n\n共获取 {len(videos)} 个视频")
        await context.close()
        await browser.close()

    return videos


def download_videos(videos: list, cookie_file: str, output_dir: str, quality: str):
    os.makedirs(output_dir, exist_ok=True)
    archive = os.path.join(output_dir, "downloaded_archive.txt")
    preset = QUALITY_PRESETS[quality]
    is_audio = bool(preset.get("postprocessors"))
    quality_tag = "_audio" if is_audio else "_%(height)sp"

    opts = {
        "format": preset["format"],
        "cookiefile": cookie_file,
        "download_archive": archive,
        "concurrent_fragment_downloads": 4,
        "retries": 5,
        "ignoreerrors": True,
        "http_headers": DOUYIN_HEADERS,
        "color": "never",
    }
    if preset.get("postprocessors"):
        opts["postprocessors"] = preset["postprocessors"]

    total = len(videos)
    for i, v in enumerate(videos, 1):
        url = f"https://www.douyin.com/video/{v['id']}"
        opts["outtmpl"] = os.path.join(output_dir, f"{i:03d}_%(title).80B{quality_tag}.%(ext)s")
        print(f"\n[{i}/{total}] {v['title'][:60]}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        time.sleep(0.3)


async def main_async(args):
    print("=" * 60)
    print("  抖音用户作品下载器（Playwright 版）")
    print("=" * 60)
    print(f"清晰度: {QUALITY_PRESETS[args.quality]['label']}")

    videos = await collect_user_videos(args.url, args.cookies)
    if not videos:
        print("\n[!] 未能获取视频列表")
        print("    可能原因：Cookie 已失效，或页面结构已变化")
        sys.exit(1)

    print(f"\n开始下载 {len(videos)} 个视频 → {args.output}")
    download_videos(videos, args.cookies, args.output, args.quality)
    print("\n=== 全部完成！===")


def main():
    parser = argparse.ArgumentParser(description="下载抖音博主所有作品（Playwright 版）")
    parser.add_argument("--url", required=True, help="博主主页 URL（douyin.com/user/...）")
    parser.add_argument("--cookies", default="all_cookies.txt",
                        help="Cookie 文件路径（默认：当前目录下 all_cookies.txt）")
    parser.add_argument("-o", "--output",
                        default=os.path.join(os.path.expanduser("~"), "Videos", "抖音用户视频"),
                        help="下载目录（默认：用户主目录下 Videos/抖音用户视频）")
    parser.add_argument("-q", "--quality", default="best",
                        choices=list(QUALITY_PRESETS.keys()),
                        help="best/4k/1080p/720p/low/audio（默认: best）")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
