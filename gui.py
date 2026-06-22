#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频下载工具 - 支持 Bilibili / 抖音"""
import sys, io, os, threading, re, shutil, zipfile, urllib.request, tempfile, asyncio, http.cookiejar

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
import yt_dlp
try:
    # 在进度钩子里抛出它可中止 yt-dlp 下载，且不会被 ignoreerrors 吞掉
    from yt_dlp.utils import DownloadCancelled
except Exception:
    class DownloadCancelled(Exception):
        pass

# ── 版本号 ────────────────────────────────────────────────────────────────
VERSION = "1.01"

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
    # 抖音博主主页：提取 sec_uid，丢弃所有查询参数 → 批量下载全部作品
    m_user = re.search(r'douyin\.com/user/([^?&/]+)', url)
    if m_user:
        sec_uid = m_user.group(1)
        return f"https://www.douyin.com/user/{sec_uid}"
    return url


# ── yt-dlp 日志重定向 ─────────────────────────────────────────────────────
class GUILogger:
    def __init__(self, log_fn, status_fn):
        self._log = log_fn
        self._status = status_fn

    def debug(self, msg):
        if "[debug]" not in msg:
            self._log(msg)

    def info(self, msg):
        self._log(msg)

    def warning(self, msg):
        self._log(f"[警告] {msg}")

    def error(self, msg):
        self._log(f"[错误] {msg}")


# ── 主窗口 ────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"VidFetch视频下载工具 v{VERSION}")
        self.resizable(True, True)
        self.configure(bg=BG)
        self.minsize(520, 480)

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
        w = max(self.winfo_width(), 560)
        h = self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    # ── UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        # 标题栏
        hdr = tk.Frame(self, bg=ACC, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  VidFetch视频下载工具", font=("微软雅黑", 14, "bold"),
                 bg=ACC, fg="white").pack(side="left")
        tk.Label(hdr, text=f"v{VERSION} ", font=FONT_S,
                 bg=ACC, fg="white").pack(side="left", anchor="s", pady=(0, 2))
        tk.Label(hdr, text="Bilibili · 抖音 · YouTube · 腾讯视频 · 爱奇艺  ", font=FONT_S,
                 bg=ACC, fg="#ddd").pack(side="right")

        body = tk.Frame(self, bg=BG, padx=20, pady=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(13, weight=1)

        def lbl(text, row, pady=(0, 4)):
            tk.Label(body, text=text, font=FONT, bg=BG, fg=DIM,
                     anchor="w").grid(row=row, column=0, sticky="w", pady=pady)

        def card_entry(row, var, width=50, show_paste=False, show_browse=False,
                       browse_cmd=None, browse_label="浏览", is_dir=False):
            f = tk.Frame(body, bg=CARD, highlightbackground="#444458",
                         highlightthickness=1)
            f.grid(row=row, column=0, sticky="ew", pady=(0, 12))
            f.columnconfigure(0, weight=1)
            e = tk.Entry(f, textvariable=var, font=FONT, bg=CARD, fg=FG,
                         insertbackground=FG, relief="flat", bd=8)
            e.grid(row=0, column=0, sticky="ew")
            col = 1
            if show_paste:
                tk.Button(f, text="粘贴", font=FONT_S, bg=ACC, fg="white",
                          relief="flat", bd=0, padx=8, cursor="hand2",
                          command=self._paste_url).grid(row=0, column=col, padx=(0,4), pady=4)
                col += 1
            if show_browse:
                tk.Button(f, text=browse_label, font=FONT_S, bg="#444458", fg=FG,
                          relief="flat", bd=0, padx=8, cursor="hand2",
                          command=browse_cmd).grid(row=0, column=col, padx=(0,4), pady=4)
            return f

        # 视频链接
        lbl("视频链接", 0)
        self.url_var = tk.StringVar()
        card_entry(1, self.url_var, show_paste=True)

        # 清晰度 + 同时下载数量
        lbl("清晰度  /  同时下载数量（批量时生效）", 2)
        self.quality_var = tk.StringVar(value=list(QUALITIES.keys())[0])
        self.concurrency_var = tk.StringVar(value="3")
        qf = tk.Frame(body, bg=CARD, highlightbackground="#444458", highlightthickness=1)
        qf.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        qf.columnconfigure(0, weight=1)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.TCombobox",
                        fieldbackground=CARD, background=CARD,
                        foreground=FG, selectbackground=ACC,
                        selectforeground="white", arrowcolor=FG,
                        bordercolor=CARD, lightcolor=CARD, darkcolor=CARD)
        # readonly 状态下 ttk 用「选中色」绘制当前值，必须为该状态显式映射颜色，
        # 否则深色主题下文字与背景同色，导致选了值却看不见
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", CARD), ("disabled", CARD)],
                  foreground=[("readonly", FG), ("disabled", DIM)],
                  selectbackground=[("readonly", CARD)],
                  selectforeground=[("readonly", FG)],
                  background=[("readonly", CARD)],
                  arrowcolor=[("readonly", FG)])
        # 下拉弹出列表（独立 Listbox，不受 TCombobox 样式控制）配色
        self.option_add("*TCombobox*Listbox.background", CARD)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACC)
        self.option_add("*TCombobox*Listbox.selectForeground", "white")
        ttk.Combobox(qf, textvariable=self.quality_var,
                     values=list(QUALITIES.keys()), state="readonly",
                     font=FONT, style="Dark.TCombobox").grid(
                         row=0, column=0, sticky="ew", padx=8, pady=6)
        ttk.Combobox(qf, textvariable=self.concurrency_var,
                     values=["1", "2", "3", "4", "5"], state="readonly",
                     width=4, font=FONT, style="Dark.TCombobox").grid(
                         row=0, column=1, sticky="e", padx=(0, 8), pady=6)

        # 保存目录
        lbl("保存目录", 4)
        self.dir_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Videos", "Downloaded"))
        card_entry(5, self.dir_var, show_browse=True,
                   browse_cmd=self._browse_dir, browse_label="浏览")

        # Cookie 文件
        lbl("Cookie 文件（可选，用于抖音登录/B站高清）", 6)
        self.cookie_var = tk.StringVar()
        card_entry(7, self.cookie_var, show_browse=True,
                   browse_cmd=self._browse_cookie, browse_label="选择")

        # ffmpeg 状态
        self.ffmpeg_var = tk.StringVar()
        self._ffmpeg_label = tk.Label(body, textvariable=self.ffmpeg_var,
                                      font=FONT_S, bg=BG, anchor="w")
        self._ffmpeg_label.grid(row=8, column=0, sticky="w", pady=(0, 8))
        self._update_ffmpeg_label()

        # 下载 / 暂停 / 停止 按钮
        btnrow = tk.Frame(body, bg=BG)
        btnrow.grid(row=9, column=0, sticky="ew", pady=(0, 12))
        btnrow.columnconfigure(0, weight=3)
        btnrow.columnconfigure(1, weight=1)
        btnrow.columnconfigure(2, weight=1)
        self.btn = tk.Button(btnrow, text="下  载",
                             font=("微软雅黑", 12, "bold"),
                             bg=ACC, fg="white", relief="flat", bd=0,
                             pady=10, cursor="hand2",
                             activebackground="#6a5ce6", activeforeground="white",
                             command=self._start_download)
        self.btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.pause_btn = tk.Button(btnrow, text="暂停",
                                   font=("微软雅黑", 11, "bold"),
                                   bg="#555568", fg="white", relief="flat", bd=0,
                                   pady=10, cursor="hand2", state="disabled",
                                   activebackground="#6a6a7e", activeforeground="white",
                                   command=self._toggle_pause)
        self.pause_btn.grid(row=0, column=1, sticky="ew", padx=3)
        self.stop_btn = tk.Button(btnrow, text="停止",
                                  font=("微软雅黑", 11, "bold"),
                                  bg="#555568", fg="white", relief="flat", bd=0,
                                  pady=10, cursor="hand2", state="disabled",
                                  activebackground="#c0504d", activeforeground="white",
                                  command=self._stop_download)
        self.stop_btn.grid(row=0, column=2, sticky="ew", padx=(6, 0))

        # 进度条
        pb_style = ttk.Style()
        pb_style.configure("Acc.Horizontal.TProgressbar",
                           troughcolor=CARD, background=ACC,
                           bordercolor=CARD, lightcolor=ACC, darkcolor=ACC)
        self.progress = ttk.Progressbar(body, style="Acc.Horizontal.TProgressbar",
                                        mode="determinate", maximum=100)
        self.progress.grid(row=10, column=0, sticky="ew", pady=(0, 4))

        self.status_var = tk.StringVar(value="就绪")
        tk.Label(body, textvariable=self.status_var, font=FONT_S,
                 bg=BG, fg=DIM, anchor="w").grid(row=11, column=0, sticky="w")

        # 日志
        tk.Label(body, text="下载日志", font=FONT_S, bg=BG, fg=DIM,
                 anchor="w").grid(row=12, column=0, sticky="w", pady=(10, 4))
        log_outer = tk.Frame(body, bg=CARD, highlightbackground="#444458",
                             highlightthickness=1)
        log_outer.grid(row=13, column=0, sticky="nsew", pady=(0, 4))
        log_outer.columnconfigure(0, weight=1)
        log_outer.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_outer, font=FONT_LOG, bg="#12121e", fg="#c0c0d0",
                                relief="flat", bd=8, height=10, wrap="word",
                                state="disabled", cursor="arrow")
        sb = tk.Scrollbar(log_outer, command=self.log_text.yview,
                          bg=CARD, troughcolor=CARD, relief="flat")
        self.log_text.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

    def _update_ffmpeg_label(self):
        if self._ffmpeg_path:
            self.ffmpeg_var.set(f"✓ ffmpeg 已就绪")
            self._ffmpeg_label.configure(fg=GREEN)
        else:
            self.ffmpeg_var.set("✗ 未检测到 ffmpeg（点击下载按钮后将自动安装）")
            self._ffmpeg_label.configure(fg=RED)

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
                    progress_cb=lambda p: self.after(0, lambda: self.progress.configure(value=p)),
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
                self.after(0, lambda: self.progress.configure(value=0))

        threading.Thread(target=_run, daemon=True).start()

    def _log(self, msg):
        def _upd():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", str(msg).strip() + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _upd)

    def _set_progress(self, pct):
        self.after(0, lambda: self.progress.configure(value=pct))

    def _set_status(self, msg):
        self.after(0, lambda: self.status_var.set(msg))

    def _set_btn(self, enabled):
        """enabled=True 表示空闲态（可开始下载）；False 表示下载中。"""
        def _upd():
            self.btn.configure(
                state="normal" if enabled else "disabled",
                bg=ACC if enabled else "#555568",
                text="下  载" if enabled else "下载中...",
            )
            self.pause_btn.configure(
                state="disabled" if enabled else "normal",
                text="暂停")
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
        try:
            concurrency = max(1, min(5, int(self.concurrency_var.get())))
        except (ValueError, TypeError):
            concurrency = 3

        self._stop_event.clear()
        self._pause_event.set()
        self._set_btn(False)
        self.progress.configure(value=0)
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
            args=(url, out_dir, quality, cookie, concurrency),
            daemon=True,
        )
        self._thread.start()

    def _do_download(self, url, out_dir, quality_label, cookie_file, concurrency=3):
        site = detect_site(url)

        # 抖音用户主页 → Playwright 批量下载
        if site == "douyin" and _is_douyin_user_url(url):
            self._do_douyin_user_batch(url, out_dir, quality_label, cookie_file, concurrency)
            return

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
            "logger": GUILogger(self._log, self._set_status),
            "progress_hooks": [self._control_hook, self._progress_hook],
            "color": "never",
        }
        if playlist:
            opts["download_archive"] = os.path.join(out_dir, archive_name(quality_label))
        if preset.get("merge_output_format"):
            opts["merge_output_format"] = preset["merge_output_format"]
        if preset.get("postprocessors"):
            opts["postprocessors"] = preset["postprocessors"]
        if cookie_file and os.path.exists(cookie_file):
            opts["cookiefile"] = cookie_file
        if site == "bilibili":
            opts.setdefault("extractor_args", {})["bilibili"] = {"prefer_multi_flv": ["false"]}

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                code = ydl.download([url])
            if code == 0:
                self._log("✓ 下载完成！")
                self._set_status("下载完成 ✓")
                self.after(0, lambda: self.progress.configure(value=100))
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
            self.after(0, lambda: self.progress.configure(value=100))
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
            "logger": GUILogger(self._log, self._set_status),
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
            with yt_dlp.YoutubeDL(opts) as ydl:
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


if __name__ == "__main__":
    try:
        app = App()
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
