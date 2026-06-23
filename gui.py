#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频下载工具 - 支持 Bilibili / 抖音"""
import sys, io, os, threading, re, shutil, zipfile, urllib.request, tempfile, asyncio, http.cookiejar, json

# 打包成 exe 后，Playwright 会去临时解压目录找浏览器（找不到）。
# 这里强制指向用户标准安装位置 %LOCALAPPDATA%\ms-playwright。
_pw_browsers = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
if os.path.isdir(_pw_browsers):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _pw_browsers

# windowed 模式下 sys.stdout/stderr 为 None，不能包装
if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")
# 固定缩放为 1.0：避免随系统 DPI 把窗口撑大到超出屏幕（保持清晰、尺寸可预期）
ctk.set_window_scaling(1.0)
ctk.set_widget_scaling(1.0)
import yt_dlp
try:
    # 在进度钩子里抛出它可中止 yt-dlp 下载，且不会被 ignoreerrors 吞掉
    from yt_dlp.utils import DownloadCancelled
except Exception:
    class DownloadCancelled(Exception):
        pass

# B站 PCDN 节点（mcdn.bilivideo.cn，常用 8082 等非标端口，企业防火墙常按域名/端口拦截）。
# yt-dlp 构建格式时只用 baseUrl、丢弃 backupUrl。这里在它构建格式之前，把 dash 里
# 属于 mcdn 的 baseUrl 换成同一条流的「非 mcdn 普通 CDN 备用地址」——这些备用地址由
# yt-dlp 自己（带登录态、正确签名）调 playurl 取到，覆盖所有清晰度，签名合法不会 403。
def _install_bili_pcdn_patch():
    try:
        from yt_dlp.extractor.bilibili import BilibiliBaseIE
    except Exception:
        return
    if getattr(BilibiliBaseIE, "_pcdn_patched", False):
        return
    _orig = BilibiliBaseIE.extract_formats

    def _patched(self, play_info):
        try:
            dash = (play_info or {}).get("dash") or {}
            streams = []
            if isinstance(dash.get("video"), list):
                streams += dash["video"]
            for grp in (dash, dash.get("dolby") or {}, dash.get("flac") or {}):
                audio = (grp or {}).get("audio")
                if isinstance(audio, list):
                    streams += audio
                elif isinstance(audio, dict):
                    streams.append(audio)
            for s in streams:
                if not isinstance(s, dict):
                    continue
                for k in ("baseUrl", "base_url"):
                    base = s.get(k)
                    if base and "mcdn.bilivideo.cn" in base:
                        backs = s.get("backupUrl") or s.get("backup_url") or []
                        good = next((u for u in backs
                                     if u and "mcdn.bilivideo.cn" not in u), None)
                        if good:
                            s[k] = good
        except Exception:
            pass
        return _orig(self, play_info)

    BilibiliBaseIE.extract_formats = _patched
    BilibiliBaseIE._pcdn_patched = True


_install_bili_pcdn_patch()

# 兜底：万一仍有 mcdn 地址漏到下载层（无可用备用地址时），去掉非标端口回落 443。
_BILI_PCDN_PORT_RE = re.compile(r'(://[^/]*\.mcdn\.bilivideo\.cn):\d+/')


class PatchedYDL(yt_dlp.YoutubeDL):
    """下载层兜底：去掉 B站 PCDN 的非标端口（回落 443）。"""
    def urlopen(self, req):
        try:
            is_str = isinstance(req, str)
            url = req if is_str else getattr(req, "url", "")
            if url and ".mcdn.bilivideo.cn:" in url:
                new = _BILI_PCDN_PORT_RE.sub(r"\1/", url)
                if new != url:
                    if is_str:
                        req = new
                    else:
                        req.url = new
        except Exception:
            pass
        return super().urlopen(req)

# ── 版本号 ────────────────────────────────────────────────────────────────
VERSION = "1.08"

# ── 颜色 / 字体常量 ───────────────────────────────────────────────────────
BG    = "#1e1e2e"
CARD  = "#2a2a3e"
ACC   = "#7c6af7"
FG    = "#e0e0f0"
DIM   = "#888898"
GREEN = "#4ade80"
RED   = "#f87171"
_CJK = "微软雅黑"
FONT_H  = (_CJK, 11, "bold")
FONT    = (_CJK, 10)
FONT_S  = (_CJK, 9)
FONT_LOG = ("Consolas", 9)

# ── ffmpeg 管理 ───────────────────────────────────────────────────────────
# 优先顺序：exe 旁边的 ffmpeg 文件夹 > PATH
FFMPEG_URL = (
    "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/"
    "latest/ffmpeg-master-latest-win64-gpl-shared.zip"
)

def _exe_dir() -> str:
    """返回可执行文件所在目录（打包后是 exe 目录，开发中是脚本目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_ffmpeg() -> str | None:
    """返回 ffmpeg.exe 路径，找不到返回 None。"""
    # 1. exe 旁边的 ffmpeg 子文件夹
    local = os.path.join(_exe_dir(), "ffmpeg", "ffmpeg.exe")
    if os.path.isfile(local):
        return local
    # 2. PATH
    found = shutil.which("ffmpeg")
    return found


def download_ffmpeg(progress_cb=None, log_cb=None) -> str:
    """下载并解压精简版 ffmpeg，返回 ffmpeg.exe 路径。"""
    dest_dir = os.path.join(_exe_dir(), "ffmpeg")
    os.makedirs(dest_dir, exist_ok=True)

    tmp_zip = os.path.join(tempfile.gettempdir(), "ffmpeg_dl.zip")

    def reporthook(count, block, total):
        if total > 0 and progress_cb:
            progress_cb(count * block / total * 100)

    if log_cb:
        log_cb("正在下载 ffmpeg（约 30 MB）...")
    urllib.request.urlretrieve(FFMPEG_URL, tmp_zip, reporthook)

    if log_cb:
        log_cb("正在解压...")
    with zipfile.ZipFile(tmp_zip, "r") as z:
        for name in z.namelist():
            basename = os.path.basename(name)
            if not basename:
                continue
            if basename.endswith(".exe") or basename.endswith(".dll"):
                z.extract(name, tempfile.gettempdir())
                src = os.path.join(tempfile.gettempdir(), name)
                if os.path.isfile(src):
                    shutil.move(src, os.path.join(dest_dir, basename))

    os.remove(tmp_zip)
    exe = os.path.join(dest_dir, "ffmpeg.exe")
    if log_cb:
        log_cb(f"ffmpeg 已就绪: {exe}")
    return exe


# ── 清晰度预设 ────────────────────────────────────────────────────────────
# 注意：非"最高"选项末尾不加无约束 /best 兜底，避免跌回最高画质
QUALITIES = {
    "最高画质": {
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "ext": "mp4",
        "suffix": "_最高画质",
    },
    "4K（2160p）": {
        "format": "bestvideo[height<=2160]+bestaudio/best[height<=2160]/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "ext": "mp4",
        "suffix": "_4K",
    },
    "1080p": {
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "ext": "mp4",
        "suffix": "_1080p",
    },
    "720p": {
        "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "ext": "mp4",
        "suffix": "_720p",
    },
    "360p（提取文字用）": {
        "format": "bestvideo[height<=360]+bestaudio/best[height<=360]/worst+bestaudio/worst/best",
        "merge_output_format": "mp4",
        "ext": "mp4",
        "suffix": "_360p",
    },
    "纯音频 MP3（语音转文字）": {
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }],
        "ext": "mp3",
        "suffix": "_audio",
    },
}

# 清晰度 → 存档文件标签（不同清晰度用不同存档，互不影响跳过判断）
_ARCHIVE_TAGS = {
    "最高画质": "best",
    "4K（2160p）": "4k",
    "1080p": "1080p",
    "720p": "720p",
    "360p（提取文字用）": "360p",
    "纯音频 MP3（语音转文字）": "audio",
}

def archive_name(quality_label: str) -> str:
    tag = _ARCHIVE_TAGS.get(quality_label, "best")
    return f"downloaded_archive_{tag}.txt"

HEADERS_BILIBILI = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}
HEADERS_DOUYIN = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://www.douyin.com/",
}

def detect_site(url):
    u = url.lower()
    if "bilibili.com" in u or "b23.tv" in u:
        return "bilibili"
    if "douyin.com" in u or "iesdouyin.com" in u:
        return "douyin"
    return "auto"

def is_playlist_url(url):
    u = url.lower()
    return ("/bangumi/media/" in u or
            "space.bilibili.com" in u or
            "/playlist?" in u or
            "/channel/" in u or
            _is_douyin_user_url(url))

def _is_douyin_user_url(url):
    return bool(re.search(r'douyin\.com/user/[^?]+', url))


def _load_douyin_cookies(cookie_file: str) -> list:
    jar = http.cookiejar.MozillaCookieJar(cookie_file)
    jar.load(ignore_discard=True, ignore_expires=True)
    result = []
    for c in jar:
        if "douyin" not in c.domain or not c.name or c.value is None:
            continue
        result.append({
            "name": str(c.name), "value": str(c.value),
            "domain": c.domain if c.domain.startswith(".") else "." + c.domain,
            "path": c.path or "/", "secure": bool(c.secure),
            "httpOnly": False, "sameSite": "Lax",
        })
    return result


def _sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符。"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name)
    name = name.strip().strip(".")
    return name or "video"


def _extract_douyin_formats(item: dict) -> list:
    """从抖音作品 JSON 中提取各清晰度的真实播放地址。

    返回 [{"height": int, "width": int, "url": str, "size": int}, ...]
    按高度从高到低排序。这些地址是浏览器合法拿到的 CDN 直链，
    可直接下载，无需再请求抖音详情 API（绕过 a_bogus 签名 / 限流）。
    """
    video = item.get("video") or {}
    out = []
    # 1. bit_rate 数组：通常含多档清晰度
    for br in (video.get("bit_rate") or []):
        pa = br.get("play_addr") or {}
        urls = pa.get("url_list") or []
        if not urls:
            continue
        url = next((u for u in urls if u.startswith("http")), urls[0])
        # 抖音返回的常是 //v3-... 协议相对地址
        if url.startswith("//"):
            url = "https:" + url
        out.append({
            "height": pa.get("height") or 0,
            "width": pa.get("width") or 0,
            "url": url,
            "size": pa.get("data_size") or 0,
        })
    # 2. 兜底：默认 play_addr
    if not out:
        pa = video.get("play_addr") or {}
        urls = pa.get("url_list") or []
        if urls:
            url = urls[0]
            if url.startswith("//"):
                url = "https:" + url
            out.append({
                "height": pa.get("height") or 0,
                "width": pa.get("width") or 0,
                "url": url,
                "size": pa.get("data_size") or 0,
            })
    # 去重 + 按高度降序
    seen_h, uniq = set(), []
    for f in sorted(out, key=lambda x: x["height"], reverse=True):
        key = f["height"]
        if key in seen_h:
            continue
        seen_h.add(key)
        uniq.append(f)
    return uniq


def _pick_douyin_format(formats: list, quality_label: str) -> dict:
    """按用户选择的清晰度档位，从可用格式里挑一个。"""
    if not formats:
        return None
    # 目标高度上限
    caps = {
        "最高画质": 99999, "4K（2160p）": 2160, "1080p": 1080,
        "720p": 720, "360p（提取文字用）": 360,
        "纯音频 MP3（语音转文字）": 360,  # 音频取最小体积流再提取
    }
    cap = caps.get(quality_label, 99999)
    # 优先选 <= cap 里最高的；都超过 cap 则选最低的
    le = [f for f in formats if f["height"] <= cap]
    if le:
        return max(le, key=lambda x: x["height"])
    return min(formats, key=lambda x: x["height"])


async def _launch_browser(p, log_fn):
    """多级回退启动浏览器，最大化兼容任意电脑。

    顺序：
    1. Playwright 自带 Chromium（运行过 playwright install 的机器）
    2. 系统 Edge（Windows 10/11 预装，几乎必有）
    3. 系统 Chrome
    """
    args = ["--disable-blink-features=AutomationControlled"]
    # 1. 自带 Chromium
    try:
        b = await p.chromium.launch(headless=False, args=args)
        log_fn("已启动 Chromium 浏览器")
        return b
    except Exception as e1:
        log_fn(f"自带 Chromium 不可用（{str(e1)[:60]}），尝试系统 Edge...")
    # 2. 系统 Edge
    try:
        b = await p.chromium.launch(headless=False, channel="msedge", args=args)
        log_fn("已启动系统 Edge 浏览器")
        return b
    except Exception as e2:
        log_fn(f"Edge 不可用（{str(e2)[:60]}），尝试系统 Chrome...")
    # 3. 系统 Chrome
    b = await p.chromium.launch(headless=False, channel="chrome", args=args)
    log_fn("已启动系统 Chrome 浏览器")
    return b


async def _playwright_collect_user_videos(user_url: str, cookie_file: str, log_fn) -> list:
    from playwright.async_api import async_playwright
    m = re.search(r'douyin\.com/user/([^?&/]+)', user_url)
    sec_uid = m.group(1) if m else ""
    page_url = f"https://www.douyin.com/user/{sec_uid}"
    videos, seen = [], set()

    async with async_playwright() as p:
        browser = await _launch_browser(p, log_fn)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        if cookie_file and os.path.exists(cookie_file):
            await ctx.add_cookies(_load_douyin_cookies(cookie_file))
            log_fn(f"已注入 Cookie")

        page = await ctx.new_page()

        async def on_response(resp):
            url = resp.url
            if "aweme/v1/web/aweme/post" in url and resp.status == 200:
                try:
                    body = await resp.json()
                    for item in (body.get("aweme_list") or []):
                        vid = item.get("aweme_id", "")
                        title = (item.get("desc") or "").strip() or vid
                        if vid and vid not in seen:
                            seen.add(vid)
                            formats = _extract_douyin_formats(item)
                            videos.append({"id": vid, "title": title, "formats": formats})
                            tag = f"（{len(formats)}档画质）" if formats else "（无内嵌地址）"
                            log_fn(f"  发现: {title[:46]} {tag}")
                except Exception:
                    pass

        page.on("response", on_response)
        log_fn(f"正在打开博主主页: {page_url}")
        try:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            pass
        await asyncio.sleep(6)

        # 读取"作品 N"里的目标数量，用于判断是否收齐
        expected = 0
        try:
            txt = await page.inner_text("body")
            mt = re.search(r'作品\s*(\d+)', txt)
            if mt:
                expected = int(mt.group(1))
                log_fn(f"页面显示作品总数: {expected}")
        except Exception:
            pass

        log_fn("滚动加载全部视频（请勿手动操作浏览器）...")
        try:
            await page.mouse.move(640, 450)  # 鼠标移到内容区，确保滚轮事件生效
        except Exception:
            pass
        prev, no_change, rounds = 0, 0, 0
        max_rounds = 200          # 死循环保护
        max_no_change = 12        # 连续 12 轮无新增才认定到底（容忍懒加载延迟）

        while rounds < max_rounds:
            rounds += 1
            # 用真实滚轮事件触发懒加载，并配合滚到底部
            try:
                await page.mouse.wheel(0, 3000)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                # 偶尔向上一点再向下，刺激监听器
                if no_change >= 3:
                    await page.evaluate("window.scrollBy(0, -600)")
                    await asyncio.sleep(0.4)
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            await asyncio.sleep(2.0)

            cur = len(videos)
            if cur == prev:
                no_change += 1
            else:
                no_change = 0
            prev = cur
            self_status = f"已收集 {cur}"
            if expected:
                self_status += f"/{expected}"
            log_fn(self_status + " 个视频...")

            # 收齐了就提前结束
            if expected and cur >= expected:
                log_fn("已收集到全部作品")
                break
            # 长时间无新增才停（且至少滚过几轮）
            if no_change >= max_no_change:
                log_fn(f"连续 {max_no_change} 轮无新增，停止滚动")
                break

        await ctx.close()
        await browser.close()
    return videos

def preprocess_url(url):
    """规整链接。

    抖音博主主页（douyin.com/user/...）无论后面带多少参数（vid=、
    from_tab_name= 等），都剥离参数还原成纯主页地址，用于批量下载
    该博主的全部视频。
    """
    # 抖音弹窗式打开的单个视频：modal_id 在任何页面（精选/发现/首页/博主页）都代表
    # 点开了某个具体视频，优先级最高 → 规范化为 douyin.com/video/<id> 下载该单条。
    # 注意：必须先于 /user/ 判断，否则 /user/self?modal_id=… 会被误当成博主批量。
    if "douyin.com" in url.lower():
        m_modal = re.search(r'[?&]modal_id=(\d+)', url)
        if m_modal:
            return f"https://www.douyin.com/video/{m_modal.group(1)}"
    # 抖音博主主页：提取 sec_uid，丢弃所有查询参数 → 批量下载全部作品
    m_user = re.search(r'douyin\.com/user/([^?&/]+)', url)
    if m_user:
        sec_uid = m_user.group(1)
        return f"https://www.douyin.com/user/{sec_uid}"
    # B站：裸域名 bilibili.com / m.bilibili.com 某些接口会 403，统一规范成 www 主域
    # （不动 space./b23.tv 等其它子域名与短链）
    m_bili = re.match(r'(?i)^\s*(?:https?://)?(?:www\.|m\.)?bilibili\.com(/[^\s]*)?$', url)
    if m_bili:
        return "https://www.bilibili.com" + (m_bili.group(1) or "")
    return url


# ── yt-dlp 日志重定向 ─────────────────────────────────────────────────────
class GUILogger:
    def __init__(self, log_fn, status_fn, control_fn=None):
        self._log = log_fn
        self._status = status_fn
        # 控制回调：在提取/下载的每条日志处检查暂停/停止，
        # 让「停止」在提取阶段（如腾讯卡在 Downloading m3u8 information）也能中断
        self._control = control_fn

    def _ctl(self):
        if self._control:
            self._control()

    def debug(self, msg):
        self._ctl()
        if "[debug]" not in msg:
            self._log(msg)

    def info(self, msg):
        self._ctl()
        self._log(msg)

    def warning(self, msg):
        self._ctl()
        self._log(f"[警告] {msg}")

    def error(self, msg):
        self._log(f"[错误] {msg}")


# ── 主窗口 ────────────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"VidFetch视频下载工具 v{VERSION}")
        self.geometry("600x720")
        self.minsize(540, 560)

        self._ffmpeg_path = find_ffmpeg()
        self._thread = None
        # 下载控制：pause_event 置位=运行中，清除=暂停；stop_event 置位=请求停止
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_event = threading.Event()
        self._build_ui()
        self._center()

        # 启动时检测 ffmpeg
        if not self._ffmpeg_path:
            self.after(300, self._prompt_ffmpeg)

    def _center(self):
        self.update_idletasks()
        w, h = 600, 720
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2 - 20)
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ── UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        PURPLE, PURPLE_H = "#7c6af7", "#6a5ce6"
        GREY, GREY_H, REDH = "#3a3a4a", "#4a4a5e", "#c0504d"
        DIMC = "#9a9ab0"

        def F(sz=13, bold=False):
            return ctk.CTkFont("微软雅黑", sz, "bold" if bold else "normal")

        # 顶部标题栏
        header = ctk.CTkFrame(self, fg_color=PURPLE, corner_radius=0, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="VidFetch 视频下载工具", text_color="white",
                     font=F(18, True)).pack(side="left", padx=(20, 8))
        ctk.CTkLabel(header, text=f"v{VERSION}", text_color="#e6e0ff",
                     font=F(12)).pack(side="left", pady=(6, 0))
        ctk.CTkLabel(header, text="Bilibili · 抖音 · YouTube · 腾讯 · 爱奇艺",
                     text_color="#ddd6ff", font=F(11)).pack(side="right", padx=20)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=14)
        body.columnconfigure(0, weight=1)
        r = 0

        def section(text, pady=(0, 4)):
            nonlocal r
            ctk.CTkLabel(body, text=text, anchor="w", text_color=DIMC,
                         font=F(12)).grid(row=r, column=0, sticky="w", pady=pady)
            r += 1

        # 视频链接
        section("视频链接")
        urlrow = ctk.CTkFrame(body, fg_color="transparent")
        urlrow.grid(row=r, column=0, sticky="ew", pady=(0, 12)); r += 1
        urlrow.columnconfigure(0, weight=1)
        self.url_var = tk.StringVar()
        ctk.CTkEntry(urlrow, textvariable=self.url_var, font=F(13), height=34,
                     placeholder_text="粘贴视频或博主主页链接").grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(urlrow, text="粘贴", width=64, height=34, font=F(12),
                      fg_color=PURPLE, hover_color=PURPLE_H,
                      command=self._paste_url).grid(row=0, column=1, padx=(8, 0))

        # 清晰度 + 并发
        section("清晰度  /  同时下载数量（批量时生效）")
        qrow = ctk.CTkFrame(body, fg_color="transparent")
        qrow.grid(row=r, column=0, sticky="ew", pady=(0, 12)); r += 1
        qrow.columnconfigure(0, weight=1)
        self.quality_var = tk.StringVar(value=list(QUALITIES.keys())[0])
        self.concurrency_var = tk.StringVar(value="3")
        ctk.CTkOptionMenu(qrow, variable=self.quality_var, values=list(QUALITIES.keys()),
                          font=F(13), height=34, fg_color=GREY, button_color=PURPLE,
                          button_hover_color=PURPLE_H).grid(row=0, column=0, sticky="ew")
        ctk.CTkOptionMenu(qrow, variable=self.concurrency_var, values=["1", "2", "3", "4", "5"],
                          width=82, font=F(13), height=34, fg_color=GREY, button_color=PURPLE,
                          button_hover_color=PURPLE_H).grid(row=0, column=1, padx=(8, 0))

        # 保存目录
        section("保存目录")
        dirrow = ctk.CTkFrame(body, fg_color="transparent")
        dirrow.grid(row=r, column=0, sticky="ew", pady=(0, 12)); r += 1
        dirrow.columnconfigure(0, weight=1)
        self.dir_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Videos", "Downloaded"))
        ctk.CTkEntry(dirrow, textvariable=self.dir_var, font=F(13), height=34).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(dirrow, text="浏览", width=64, height=34, font=F(12),
                      fg_color=GREY, hover_color=GREY_H,
                      command=self._browse_dir).grid(row=0, column=1, padx=(8, 0))

        # Cookie 文件
        section("Cookie（可选，仅需登录的视频才用）")
        ckrow = ctk.CTkFrame(body, fg_color="transparent")
        ckrow.grid(row=r, column=0, sticky="ew", pady=(0, 8)); r += 1
        ckrow.columnconfigure(0, weight=1)
        self.cookie_var = tk.StringVar()
        ctk.CTkEntry(ckrow, textvariable=self.cookie_var, font=F(13), height=34,
                     placeholder_text="手动选择 cookies.txt（或下方从浏览器获取）").grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(ckrow, text="选择", width=64, height=34, font=F(12),
                      fg_color=GREY, hover_color=GREY_H,
                      command=self._browse_cookie).grid(row=0, column=1, padx=(8, 0))

        # 浏览器取 Cookie
        brow = ctk.CTkFrame(body, fg_color="transparent")
        brow.grid(row=r, column=0, sticky="w", pady=(0, 10)); r += 1
        ctk.CTkLabel(brow, text="从浏览器自动获取 Cookie:", text_color=DIMC,
                     font=F(12)).pack(side="left", padx=(0, 8))
        self.cookie_browser_var = tk.StringVar(value="不使用")
        ctk.CTkOptionMenu(brow, variable=self.cookie_browser_var,
                          values=["不使用", "Chrome", "Edge", "Firefox", "Brave"],
                          width=120, font=F(12), height=32, fg_color=GREY,
                          button_color=PURPLE, button_hover_color=PURPLE_H).pack(side="left")

        # ffmpeg 状态
        self.ffmpeg_var = tk.StringVar()
        self._ffmpeg_label = ctk.CTkLabel(body, textvariable=self.ffmpeg_var, anchor="w", font=F(12))
        self._ffmpeg_label.grid(row=r, column=0, sticky="w", pady=(0, 8)); r += 1
        self._update_ffmpeg_label()

        # 下载 / 暂停 / 停止
        btnrow = ctk.CTkFrame(body, fg_color="transparent")
        btnrow.grid(row=r, column=0, sticky="ew", pady=(0, 12)); r += 1
        btnrow.columnconfigure(0, weight=3)
        btnrow.columnconfigure(1, weight=1)
        btnrow.columnconfigure(2, weight=1)
        self.btn = ctk.CTkButton(btnrow, text="下  载", height=40, font=F(15, True),
                                 fg_color=PURPLE, hover_color=PURPLE_H, command=self._start_download)
        self.btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.pause_btn = ctk.CTkButton(btnrow, text="暂停", height=40, font=F(13, True),
                                       fg_color=GREY, hover_color=GREY_H, state="disabled",
                                       command=self._toggle_pause)
        self.pause_btn.grid(row=0, column=1, sticky="ew", padx=3)
        self.stop_btn = ctk.CTkButton(btnrow, text="停止", height=40, font=F(13, True),
                                      fg_color=GREY, hover_color=REDH, state="disabled",
                                      command=self._stop_download)
        self.stop_btn.grid(row=0, column=2, sticky="ew", padx=(6, 0))

        # 进度条 + 状态
        self.progress = ctk.CTkProgressBar(body, height=14, progress_color=PURPLE)
        self.progress.grid(row=r, column=0, sticky="ew", pady=(2, 4)); r += 1
        self.progress.set(0)
        self.status_var = tk.StringVar(value="就绪")
        ctk.CTkLabel(body, textvariable=self.status_var, anchor="w", text_color=DIMC,
                     font=F(12)).grid(row=r, column=0, sticky="w"); r += 1

        # 日志
        ctk.CTkLabel(body, text="下载日志", anchor="w", text_color=DIMC,
                     font=F(12)).grid(row=r, column=0, sticky="w", pady=(8, 4)); r += 1
        body.rowconfigure(r, weight=1)
        self.log_text = ctk.CTkTextbox(body, font=("Consolas", 12), fg_color="#15151f",
                                       text_color="#c8c8da", wrap="word")
        self.log_text.grid(row=r, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

    def _update_ffmpeg_label(self):
        if self._ffmpeg_path:
            self.ffmpeg_var.set("✓ ffmpeg 已就绪")
            self._ffmpeg_label.configure(text_color=GREEN)
        else:
            self.ffmpeg_var.set("✗ 未检测到 ffmpeg（点击下载按钮后将自动安装）")
            self._ffmpeg_label.configure(text_color=RED)

    # ── 操作 ─────────────────────────────────────────────────────────────
    def _paste_url(self):
        try:
            self.url_var.set("".join(self.clipboard_get().split()))
        except Exception:
            pass

    def _browse_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get())
        if d:
            self.dir_var.set(d)

    def _browse_cookie(self):
        f = filedialog.askopenfilename(
            title="选择 Cookie 文件",
            filetypes=[("Cookie 文件", "*.txt"), ("所有文件", "*.*")],
        )
        if f:
            self.cookie_var.set(f)

    def _prompt_ffmpeg(self):
        if messagebox.askyesno(
            "需要 ffmpeg",
            "ffmpeg 是合并音视频所必需的工具（约 30 MB）。\n\n是否现在自动下载安装？",
        ):
            self._auto_install_ffmpeg()

    def _auto_install_ffmpeg(self):
        self._set_btn(False)
        self._log("开始下载 ffmpeg...")

        def _run():
            try:
                path = download_ffmpeg(
                    progress_cb=lambda p: self.after(0, lambda: self.progress.set(max(0.0, min(1.0, p / 100.0)))),
                    log_cb=self._log,
                )
                self._ffmpeg_path = path
                self.after(0, self._update_ffmpeg_label)
                self._log("ffmpeg 安装完成，可以开始下载视频了！")
                self.after(0, lambda: self.status_var.set("ffmpeg 已就绪"))
            except Exception as e:
                self._log(f"[错误] ffmpeg 下载失败: {e}")
                self.after(0, lambda: messagebox.showerror(
                    "下载失败", f"请手动安装 ffmpeg 并将其加入 PATH。\n\n错误: {e}"
                ))
            finally:
                self._set_btn(True)
                self.after(0, lambda: self.progress.set(0))

        threading.Thread(target=_run, daemon=True).start()

    def _log(self, msg):
        def _upd():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", str(msg).strip() + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _upd)

    def _set_progress(self, pct):
        self.after(0, lambda: self.progress.set(max(0.0, min(1.0, pct / 100.0))))

    def _set_status(self, msg):
        self.after(0, lambda: self.status_var.set(msg))

    def _set_btn(self, enabled):
        """enabled=True 表示空闲态（可开始下载）；False 表示下载中。"""
        def _upd():
            self.btn.configure(
                state="normal" if enabled else "disabled",
                text="下  载" if enabled else "下载中...")
            self.pause_btn.configure(
                state="disabled" if enabled else "normal", text="暂停")
            self.stop_btn.configure(
                state="disabled" if enabled else "normal")
        self.after(0, _upd)

    # ── 暂停 / 停止 控制 ─────────────────────────────────────────────────
    def _wait_if_paused(self):
        """若处于暂停态则阻塞，直到继续或请求停止。"""
        while not self._pause_event.is_set():
            if self._stop_event.wait(0.1):   # 暂停期间也能立即响应停止
                return

    def _check_control(self):
        """下载循环/进度钩子里的检查点：暂停则等待，停止则抛出取消异常。"""
        self._wait_if_paused()
        if self._stop_event.is_set():
            raise DownloadCancelled()

    def _control_hook(self, d):
        # 作为 yt-dlp 的第一个 progress_hook，负责暂停阻塞与停止中止
        self._check_control()

    def _toggle_pause(self):
        if self._thread is None or not self._thread.is_alive():
            return
        if self._pause_event.is_set():
            self._pause_event.clear()
            self.pause_btn.configure(text="继续")
            self._set_status("已暂停")
            self._log("⏸ 已暂停")
        else:
            self._pause_event.set()
            self.pause_btn.configure(text="暂停")
            self._set_status("继续下载...")
            self._log("▶ 继续下载")

    def _stop_download(self):
        if self._thread is None or not self._thread.is_alive():
            return
        self._stop_event.set()
        self._pause_event.set()   # 解除可能存在的暂停等待，让线程尽快看到停止
        self.stop_btn.configure(state="disabled")
        self.pause_btn.configure(state="disabled")
        self._set_status("正在停止...")
        self._log("⏹ 正在停止...")

    # ── 单实例 / 浏览器扩展 入口 ─────────────────────────────────────────
    def _start_single_instance_server(self):
        """绑定本地回环端口作为单实例标志；成功则起监听线程接收转发的下载地址。
        返回 True=本进程是首个实例；False=已有实例在运行。"""
        import socket
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind((_SINGLE_HOST, _SINGLE_PORT))
            srv.listen(5)
        except OSError:
            return False
        self._single_srv = srv

        def _loop():
            while True:
                try:
                    conn, _ = srv.accept()
                    buf = conn.recv(8192).decode("utf-8", "replace")
                    conn.close()
                    for line in buf.splitlines():
                        if line.startswith("ADD "):
                            u = line[4:].strip()
                            if u:
                                self.after(0, lambda u=u: self._add_url(u))
                except Exception:
                    break
        threading.Thread(target=_loop, daemon=True).start()
        return True

    def _add_url(self, url):
        """收到（扩展或第二实例转发来的）下载地址：填入并自动开始下载，并把窗口提到前台。"""
        try:
            self.url_var.set(url)
            self._log(f"\n▶ 收到下载请求：{url}")
            try:
                self.deiconify()
            except Exception:
                pass
            self.lift()
            self.focus_force()
            if self._thread and self._thread.is_alive():
                self._log("（当前已有下载在进行，地址已填入，等完成后点“下载”即可）")
                return
            self._start_download()
        except Exception as e:
            self._log(f"[错误] 处理下载请求失败：{e}")

    # ── 下载 ─────────────────────────────────────────────────────────────
    def _start_download(self):
        url = preprocess_url("".join(self.url_var.get().split()))
        if not url:
            messagebox.showwarning("提示", "请输入视频链接")
            return
        if self._thread and self._thread.is_alive():
            messagebox.showinfo("提示", "正在下载中，请等待完成后再试")
            return
        if not self._ffmpeg_path:
            if messagebox.askyesno("需要 ffmpeg", "需要先安装 ffmpeg 才能下载，现在安装？"):
                self._auto_install_ffmpeg()
            return

        out_dir = self.dir_var.get().strip() or os.path.join(os.path.expanduser("~"), "Videos", "Downloaded")
        quality = self.quality_var.get()
        cookie  = self.cookie_var.get().strip()
        cookie_browser = self.cookie_browser_var.get()
        try:
            concurrency = max(1, min(5, int(self.concurrency_var.get())))
        except (ValueError, TypeError):
            concurrency = 3

        self._stop_event.clear()
        self._pause_event.set()
        self._set_btn(False)
        self.progress.set(0)
        self._set_status("准备中...")
        raw_url = "".join(self.url_var.get().split())
        self._log(f"\n{'─'*48}")
        if url != raw_url:
            self._log(f"原始链接: {raw_url}")
            self._log(f"转换后:   {url}")
        else:
            self._log(f"链接: {url}")
        self._log(f"清晰度: {quality}")
        self._log(f"保存到: {out_dir}")

        self._thread = threading.Thread(
            target=self._do_download,
            args=(url, out_dir, quality, cookie, concurrency, cookie_browser),
            daemon=True,
        )
        self._thread.start()

    # ── B站分集 / PCDN 备用地址 ───────────────────────────────────────────
    def _get_bili_pages(self, url, site):
        """B站 /video/BV 的分集 [(page, title, cid), ...]（含单P）；非B站或失败返回 None。"""
        if site != "bilibili":
            return None
        m = re.search(r'/video/(BV[0-9A-Za-z]+)', url)
        if not m:
            return None
        try:
            api = f"https://api.bilibili.com/x/player/pagelist?bvid={m.group(1)}"
            req = urllib.request.Request(api, headers={
                "User-Agent": HEADERS_BILIBILI["User-Agent"],
                "Referer": "https://www.bilibili.com/"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.load(resp)
            pages = data.get("data") or []
            if pages:
                return [(p.get("page", i + 1),
                         (p.get("part") or f"P{p.get('page', i + 1)}").strip(),
                         p.get("cid"))
                        for i, p in enumerate(pages)]
        except Exception as e:
            self._log(f"[提示] 获取分集列表失败：{str(e)[:50]}")
        return None

    def _ask_episode_selection(self, parts):
        """主线程弹分集勾选框。返回选中的 page 列表；点取消/关闭返回 None。"""
        holder = {"result": None}
        done = threading.Event()

        def _show():
            FF = lambda sz=12, b=False: ctk.CTkFont("微软雅黑", sz, "bold" if b else "normal")
            win = ctk.CTkToplevel(self)
            win.title("选择要下载的分集")
            win.geometry("540x480")
            win.transient(self)
            win.after(200, lambda: win.grab_set())   # CTkToplevel 需稍延迟再 grab
            ctk.CTkLabel(win, text=f"共 {len(parts)} 个分集，默认全选；取消勾选不想下载的：",
                         font=FF(13), anchor="w").pack(anchor="w", padx=16, pady=(14, 6))
            scroll = ctk.CTkScrollableFrame(win, fg_color="#2a2a3e")
            scroll.pack(fill="both", expand=True, padx=16)
            vars_ = []
            for page, title in parts:
                v = tk.BooleanVar(value=True)
                vars_.append((page, v))
                ctk.CTkCheckBox(scroll, text=f"P{page}  {title}", variable=v,
                                font=FF(12), fg_color="#7c6af7",
                                hover_color="#6a5ce6").pack(fill="x", anchor="w", pady=4)

            def _set_all(val):
                for _, v in vars_:
                    v.set(val)

            def _finish(result):
                holder["result"] = result
                win.destroy()
                done.set()

            bar = ctk.CTkFrame(win, fg_color="transparent")
            bar.pack(fill="x", padx=16, pady=12)
            ctk.CTkButton(bar, text="全选", width=64, font=FF(12), fg_color="#3a3a4a",
                          hover_color="#4a4a5e", command=lambda: _set_all(True)).pack(side="left")
            ctk.CTkButton(bar, text="全不选", width=64, font=FF(12), fg_color="#3a3a4a",
                          hover_color="#4a4a5e", command=lambda: _set_all(False)).pack(side="left", padx=6)
            ctk.CTkButton(bar, text="开始下载", font=FF(13, True), fg_color="#7c6af7",
                          hover_color="#6a5ce6",
                          command=lambda: _finish([pg for pg, v in vars_ if v.get()])).pack(side="right")
            ctk.CTkButton(bar, text="取消", width=72, font=FF(12), fg_color="#555568",
                          hover_color="#666677", command=lambda: _finish(None)).pack(side="right", padx=6)
            win.protocol("WM_DELETE_WINDOW", lambda: _finish(None))

        self.after(0, _show)
        done.wait()
        return holder["result"]

    def _do_download(self, url, out_dir, quality_label, cookie_file, concurrency=3,
                     cookie_browser="不使用"):
        site = detect_site(url)

        # 抖音用户主页 → Playwright 批量下载
        if site == "douyin" and _is_douyin_user_url(url):
            self._do_douyin_user_batch(url, out_dir, quality_label, cookie_file, concurrency)
            return

        # B站多P合集：取分集（pagelist），多P 且未指定某P 时弹勾选（默认全选）
        # PCDN→普通CDN 的规避由 _install_bili_pcdn_patch() 在提取层自动完成，无需在此另调接口
        selected_items = None
        pages = self._get_bili_pages(url, site)        # [(page, title, cid)] 或 None
        if pages and len(pages) > 1 and not re.search(r'[?&]p=\d+', url):
            self._set_status("请选择要下载的分集...")
            parts = [(pg, t) for pg, t, _ in pages]
            sel = self._ask_episode_selection(parts)
            if sel is None:
                self._log("已取消下载"); self._set_status("已取消"); self._set_btn(True); return
            if not sel:
                self._log("未勾选任何分集，已取消"); self._set_status("已取消"); self._set_btn(True); return
            if len(sel) < len(pages):
                selected_items = ",".join(str(p) for p in sel)
                self._log(f"已选择 {len(sel)}/{len(pages)} 个分集：P{selected_items}")
            else:
                self._log(f"已选择全部 {len(pages)} 个分集")

        preset  = QUALITIES[quality_label]
        headers = HEADERS_BILIBILI if site == "bilibili" else HEADERS_DOUYIN

        os.makedirs(out_dir, exist_ok=True)

        playlist = is_playlist_url(url)
        is_audio = bool(preset.get("postprocessors"))
        # 视频用实际分辨率命名，音频用 _audio
        quality_tag = "_audio" if is_audio else "_%(height)sp"

        if playlist:
            tmpl = os.path.join(out_dir, f"%(playlist_index)03d_%(title).80B{quality_tag}.%(ext)s")
            self._log("检测到系列/播放列表，将按集数顺序批量下载")
        else:
            tmpl = os.path.join(out_dir, f"%(title).100B{quality_tag}.%(ext)s")

        opts = {
            "outtmpl": tmpl,
            "format": preset["format"],
            "concurrent_fragment_downloads": 4,
            "retries": 8,
            "fragment_retries": 8,
            "ignoreerrors": True,
            "http_headers": headers,
            "ffmpeg_location": os.path.dirname(self._ffmpeg_path),
            "logger": GUILogger(self._log, self._set_status, self._check_control),
            "socket_timeout": 30,
            "progress_hooks": [self._control_hook, self._progress_hook],
            "color": "never",
        }
        if playlist:
            opts["download_archive"] = os.path.join(out_dir, archive_name(quality_label))
        if selected_items:                       # B站多P：只下用户勾选的分集
            opts["playlist_items"] = selected_items
        if preset.get("merge_output_format"):
            opts["merge_output_format"] = preset["merge_output_format"]
        if preset.get("postprocessors"):
            opts["postprocessors"] = preset["postprocessors"]
        # Cookie：浏览器自动获取优先，其次手动文件（都没有则按免登录下载）
        if cookie_browser and cookie_browser != "不使用":
            opts["cookiesfrombrowser"] = (cookie_browser.lower(),)
            self._log(f"从浏览器自动获取 Cookie：{cookie_browser}")
        elif cookie_file and os.path.exists(cookie_file):
            opts["cookiefile"] = cookie_file
        if site == "bilibili":
            opts.setdefault("extractor_args", {})["bilibili"] = {"prefer_multi_flv": ["false"]}
            has_cookie = (cookie_browser and cookie_browser != "不使用") or \
                         (cookie_file and os.path.exists(cookie_file))
            if not has_cookie:
                self._log("⚠ B站未登录：部分视频画质会被限制（常见≤480p）。若清晰度不理想，"
                          "可在「从浏览器自动获取 Cookie」选择已登录B站的浏览器（如 Edge/Chrome）；"
                          "若登录后仍是 480p，则是该视频源本身清晰度就低。")

        try:
            with PatchedYDL(opts) as ydl:
                code = ydl.download([url])
            if code == 0:
                self._log("✓ 下载完成！")
                self._set_status("下载完成 ✓")
                self.after(0, lambda: self.progress.set(1.0))
            else:
                self._log("下载遇到问题，请查看日志")
                self._set_status("下载遇到问题")
        except DownloadCancelled:
            self._log("⏹ 已停止下载")
            self._set_status("已停止")
        except Exception as e:
            self._log(f"[错误] {e}")
            self._set_status("出错")
        finally:
            self._set_btn(True)

    def _do_douyin_user_batch(self, url, out_dir, quality_label, cookie_file, concurrency=3):
        """用 Playwright 批量下载抖音博主全部视频（并发）"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        try:
            import playwright  # noqa: F401
        except ImportError:
            self._log("[错误] 批量下载抖音博主视频需要 Playwright，请在命令行运行：")
            self._log("  pip install playwright && playwright install chromium")
            self._set_btn(True)
            return

        self._log("启动浏览器收集视频列表（请勿关闭弹出的浏览器窗口）...")
        try:
            videos = asyncio.run(
                _playwright_collect_user_videos(url, cookie_file, self._log)
            )
        except Exception as e:
            self._log(f"[错误] 浏览器收集失败: {e}")
            self._set_btn(True)
            return

        if not videos:
            self._log("[!] 未能获取视频列表，可能 Cookie 已失效或页面结构变化")
            self._set_btn(True)
            return

        total = len(videos)
        with_addr = sum(1 for v in videos if v.get("formats"))
        self._log(f"\n共获取 {total} 个视频（其中 {with_addr} 个含内嵌播放地址）")
        self._log(f"开始直连 CDN 下载（同时 {concurrency} 个），绕过抖音详情 API 限流...")
        os.makedirs(out_dir, exist_ok=True)

        preset = QUALITIES[quality_label]
        is_audio = bool(preset.get("postprocessors"))

        # 下载存档，避免重复下载
        archive_path = os.path.join(out_dir, archive_name(quality_label))
        done_ids = set()
        if os.path.exists(archive_path):
            with open(archive_path, "r", encoding="utf-8") as f:
                done_ids = {ln.strip() for ln in f if ln.strip()}

        # 计数器与文件写入的线程锁
        lock = threading.Lock()
        counters = {"ok": 0, "skipped": 0, "failed": 0, "done": 0}

        def _bump(key):
            with lock:
                counters[key] += 1
                counters["done"] += 1
                self._set_progress(counters["done"] / total * 100)

        def _archive(vid):
            with lock:
                with open(archive_path, "a", encoding="utf-8") as f:
                    f.write(vid + "\n")

        def _worker(i, v):
            if self._stop_event.is_set():
                return
            vid = v["id"]
            if vid in done_ids:
                with lock:
                    counters["skipped"] += 1
                    counters["done"] += 1
                    self._set_progress(counters["done"] / total * 100)
                self._log(f"[{i}/{total}] 已下载过，跳过：{v['title'][:46]}")
                return
            fmt = _pick_douyin_format(v.get("formats") or [], quality_label)
            try:
                if fmt:
                    h = fmt["height"] or "src"
                    safe_title = _sanitize_filename(v["title"])[:80]
                    base = os.path.join(out_dir, f"{i:03d}_{safe_title}")
                    if is_audio:
                        self._download_douyin_audio_quiet(fmt["url"], base, h)
                    else:
                        self._download_douyin_video_quiet(fmt["url"], base, h)
                    _archive(vid)
                    _bump("ok")
                    self._log(f"[{i}/{total}] ✓ {v['title'][:46]}")
                else:
                    if self._fallback_ytdlp_single(vid, i, out_dir, preset, cookie_file):
                        _archive(vid)
                        _bump("ok")
                        self._log(f"[{i}/{total}] ✓（yt-dlp）{v['title'][:40]}")
                    else:
                        _bump("failed")
                        self._log(f"[{i}/{total}] [失败] {v['title'][:46]}")
            except DownloadCancelled:
                return                      # 用户停止，不计为失败
            except Exception as e:
                _bump("failed")
                self._log(f"[{i}/{total}] [失败] {v['title'][:40]}：{str(e)[:50]}")

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(_worker, i, v) for i, v in enumerate(videos, 1)]
            for _ in as_completed(futures):
                d = counters["done"]
                self._set_status(f"已完成 {d}/{total}（成功{counters['ok']} 失败{counters['failed']}）")

        if self._stop_event.is_set():
            self._log(f"\n⏹ 已停止（成功 {counters['ok']}，跳过 {counters['skipped']}，共 {total}）")
            self._set_status("已停止")
        else:
            self._log(f"\n✓ 全部完成！成功 {counters['ok']}，跳过 {counters['skipped']}，失败 {counters['failed']}（共 {total}）")
            self._set_status(f"完成：成功 {counters['ok']} / 共 {total}")
            self.after(0, lambda: self.progress.set(1.0))
        self._set_btn(True)

    def _download_douyin_video(self, cdn_url, base_path, height):
        """直连 CDN 下载抖音 mp4。"""
        out = f"{base_path}_{height}p.mp4"
        self._download_with_progress(cdn_url, out)
        self._log(f"  ✓ {os.path.basename(out)}")

    def _download_douyin_audio(self, cdn_url, base_path, height):
        """下载 mp4 后用 ffmpeg 提取为 mp3。"""
        tmp_mp4 = f"{base_path}_tmp.mp4"
        out_mp3 = f"{base_path}_audio.mp3"
        self._download_with_progress(cdn_url, tmp_mp4)
        import subprocess
        ffmpeg = self._ffmpeg_path
        try:
            subprocess.run(
                [ffmpeg, "-y", "-i", tmp_mp4, "-vn", "-acodec", "libmp3lame",
                 "-b:a", "128k", out_mp3],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._log(f"  ✓ {os.path.basename(out_mp3)}")
        finally:
            if os.path.exists(tmp_mp4):
                try:
                    os.remove(tmp_mp4)
                except OSError:
                    pass

    def _download_with_progress(self, url, out_path):
        """带进度条的流式下载（单文件场景）。"""
        req = urllib.request.Request(url, headers={
            "User-Agent": HEADERS_DOUYIN["User-Agent"],
            "Referer": "https://www.douyin.com/",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                done = 0
                chunk = 1024 * 256
                with open(out_path, "wb") as f:
                    while True:
                        self._check_control()        # 暂停/停止 检查点
                        buf = resp.read(chunk)
                        if not buf:
                            break
                        f.write(buf)
                        done += len(buf)
                        if total > 0:
                            self._set_progress(done / total * 100)
        except BaseException:
            self._remove_partial(out_path)           # 中断时清理半成品
            raise

    def _download_no_progress(self, url, out_path):
        """不更新进度条的流式下载（并发场景，进度按完成数统计）。"""
        req = urllib.request.Request(url, headers={
            "User-Agent": HEADERS_DOUYIN["User-Agent"],
            "Referer": "https://www.douyin.com/",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                chunk = 1024 * 256
                with open(out_path, "wb") as f:
                    while True:
                        self._check_control()        # 暂停/停止 检查点
                        buf = resp.read(chunk)
                        if not buf:
                            break
                        f.write(buf)
        except BaseException:
            self._remove_partial(out_path)           # 中断时清理半成品
            raise

    @staticmethod
    def _remove_partial(path):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def _download_douyin_video_quiet(self, cdn_url, base_path, height):
        out = f"{base_path}_{height}p.mp4"
        self._download_no_progress(cdn_url, out)

    def _download_douyin_audio_quiet(self, cdn_url, base_path, height):
        tmp_mp4 = f"{base_path}_tmp.mp4"
        out_mp3 = f"{base_path}_audio.mp3"
        self._download_no_progress(cdn_url, tmp_mp4)
        import subprocess
        try:
            subprocess.run(
                [self._ffmpeg_path, "-y", "-i", tmp_mp4, "-vn", "-acodec",
                 "libmp3lame", "-b:a", "128k", out_mp3],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        finally:
            if os.path.exists(tmp_mp4):
                try:
                    os.remove(tmp_mp4)
                except OSError:
                    pass

    def _fallback_ytdlp_single(self, vid, idx, out_dir, preset, cookie_file):
        """对没有内嵌地址的视频，退回 yt-dlp 单条下载。"""
        video_url = f"https://www.douyin.com/video/{vid}"
        is_audio = bool(preset.get("postprocessors"))
        quality_tag = "_audio" if is_audio else "_%(height)sp"
        opts = {
            "outtmpl": os.path.join(out_dir, f"{idx:03d}_%(title).80B{quality_tag}.%(ext)s"),
            "format": preset["format"],
            "retries": 3,
            "ignoreerrors": True,
            "http_headers": HEADERS_DOUYIN,
            "ffmpeg_location": os.path.dirname(self._ffmpeg_path),
            "logger": GUILogger(self._log, self._set_status, self._check_control),
            "socket_timeout": 30,
            "progress_hooks": [self._control_hook, self._progress_hook],
            "color": "never",
        }
        if preset.get("merge_output_format"):
            opts["merge_output_format"] = preset["merge_output_format"]
        if preset.get("postprocessors"):
            opts["postprocessors"] = preset["postprocessors"]
        if cookie_file and os.path.exists(cookie_file):
            opts["cookiefile"] = cookie_file
        try:
            with PatchedYDL(opts) as ydl:
                return ydl.download([video_url]) == 0
        except Exception:
            return False

    def _progress_hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            dl    = d.get("downloaded_bytes", 0)
            speed = d.get("speed") or 0
            eta   = d.get("eta") or 0
            if total > 0:
                pct = dl / total * 100
                self._set_progress(pct)
                spd_mb = speed / 1024 / 1024
                self._set_status(f"{pct:.1f}%  {spd_mb:.1f} MB/s  剩余 {eta}s")
        elif d["status"] == "finished":
            fname = os.path.basename(d.get("filename", ""))
            self._log(f"  ✓ {fname}")
            self._set_progress(99)


# 单实例通信：浏览器扩展/第二个实例把下载地址转发给正在运行的窗口（仅本机回环）
_SINGLE_HOST = "127.0.0.1"
_SINGLE_PORT = 47923


def _forward_url_if_running(url):
    """若已有 VidFetch 在运行，把 url 转发过去并返回 True；否则返回 False。"""
    import socket
    try:
        s = socket.create_connection((_SINGLE_HOST, _SINGLE_PORT), timeout=1.0)
        s.sendall(("ADD " + url + "\n").encode("utf-8"))
        s.close()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    _argv = sys.argv[1:]
    _url = None
    if "--url" in _argv:
        _i = _argv.index("--url")
        if _i + 1 < len(_argv):
            _url = _argv[_i + 1].strip()
    # 已有实例在跑 → 转发地址后直接退出，避免开多个窗口
    if _url and _forward_url_if_running(_url):
        sys.exit(0)
    try:
        app = App()
        if not app._start_single_instance_server():   # 绑定失败=已有实例（竞态），再转发
            if _url and _forward_url_if_running(_url):
                app.destroy()
                sys.exit(0)
        if _url:
            app.after(600, lambda: app._add_url(_url))
        app.mainloop()
    except Exception as _e:
        import traceback, datetime
        _log = os.path.join(os.path.expanduser("~"), "视频下载器错误.txt")
        with open(_log, "a", encoding="utf-8") as _f:
            _f.write(f"\n[{datetime.datetime.now()}]\n")
            _f.write(traceback.format_exc())
        # 尝试用 messagebox 显示
        try:
            import tkinter.messagebox as _mb
            _mb.showerror("启动错误", f"程序启动失败，详情已写入:\n{_log}\n\n{_e}")
        except Exception:
            pass
