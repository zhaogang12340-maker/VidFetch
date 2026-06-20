# VidFetch · 多平台视频下载工具

一个**免安装**的 Windows 视频下载工具,带图形界面,支持按清晰度下载、批量下载整季/整个博主作品。基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 与 [Playwright](https://playwright.dev/)。

支持平台:**Bilibili · 抖音 · YouTube · 腾讯视频 · 爱奇艺 · 央视频**(各平台支持程度见下表)。

---

## 一、功能列表

| 功能 | 说明 | 已验证 |
|---|---|---|
| 单个视频下载 | 粘贴分享链接即可下载 | ✅ B站 / 抖音 |
| 多清晰度选择 | 最高画质 / 4K / 1080p / 720p / 360p / 纯音频 MP3 | ✅ |
| 文件名带清晰度 | 自动以**实际下载到的分辨率**命名,如 `标题_1080p.mp4` | ✅ |
| 整季 / 合集下载 | B站番剧 `bangumi/media/mdXXXX`、UP主空间自动识别并批量 | ✅ B站 |
| 博主全部作品 | 抖音博主主页一键下载全部作品(绕过抖音反爬) | ✅ 抖音 |
| 并发下载 | 批量时可设置同时下载 1~5 个,加速 | ✅ |
| 断点续传式跳过 | 已下载的自动跳过(不同清晰度互不影响) | ✅ |
| 登录态下载 | 通过 Cookie 文件下载会员 / 高清 / 需登录内容 | ✅ |
| 自动安装 ffmpeg | 首次运行若缺 ffmpeg 会自动下载 | ✅ |
| 免安装 EXE | 单文件可执行,拷到任意 Windows 电脑即用 | ✅ |

### 清晰度档位

| 选项 | 用途 |
|---|---|
| 最高画质 | 欣赏用,选平台能提供的最高质量 |
| 4K（2160p） | 限制 ≤4K,无 4K 时自动降级 |
| 1080p / 720p / 360p | 限制对应分辨率上限,平台无此档时自动取最接近的 |
| 纯音频 MP3 | 只要声音,体积最小,适合语音转文字 |

---

## 二、依赖

### 终端用户(用 EXE)
- **Windows 10 / 11**
- **网络连接**
- 浏览器(批量下载抖音博主时需要):自带 Chromium,或系统 **Edge**(Win10/11 预装)/ Chrome
- ffmpeg:首次运行自动下载,无需手动安装

### 开发者(跑源码 / 打包)
- **Python 3.12+**
- 依赖包:
  ```bash
  pip install -r requirements.txt
  playwright install chromium
  ```
- **ffmpeg**:加入 PATH,或放在脚本 / exe 同级的 `ffmpeg/` 子目录
- 打包工具:`pip install pyinstaller`

---

## 三、使用方法

### A. 图形界面(推荐)

1. 双击 `视频下载器.exe`
2. **视频链接**:粘贴链接(支持「粘贴」按钮,自动清除换行)
3. **清晰度**:下拉选择;右侧数字是**批量下载时的并发数**(1~5)
4. **保存目录**:选择下载位置
5. **Cookie 文件(可选)**:下载会员 / 高清 / 需登录内容时,选择导出的 Cookie 文件(见下)
6. 点 **下载**

不同链接的行为:

| 你粘贴的链接 | 程序行为 |
|---|---|
| B站单个视频 `bilibili.com/video/BVxxxx` | 下载该视频 |
| B站番剧整季 `bilibili.com/bangumi/media/mdXXXX` | 下载整季,文件名带集数序号 |
| B站番剧单集 `bilibili.com/bangumi/play/epXXXX` | 只下载该集 |
| 抖音单个视频 `douyin.com/video/XXXX` | 下载该视频 |
| 抖音博主主页 `douyin.com/user/XXXX`(参数随意) | 下载该博主**全部作品**(弹浏览器收集列表) |

### B. 命令行(开发者)

```bash
# 单个视频(B站/抖音)
python downloader.py "https://www.bilibili.com/video/BVxxxx"

# 指定清晰度:best / medium / low / audio
python downloader.py --quality audio "https://www.bilibili.com/video/BVxxxx"

# B站 UP主 / 合集全部视频
python downloader.py --all "https://space.bilibili.com/123456"

# 抖音博主全部作品(Playwright)
python douyin_user_playwright.py --url "https://www.douyin.com/user/XXXX" \
  --quality low -o "D:/Videos/某博主" --cookies all_cookies.txt
```

---

## 四、如何导出 Cookie(下载会员 / 高清 / 需登录内容)

1. Chrome 安装扩展 **「Get cookies.txt LOCALLY」**
2. 登录目标网站(B站 / 抖音 / 腾讯视频等),停留在该网站页面
3. 点扩展 → **Export All Cookies**(一次导出所有网站,通用)→ 保存为 `all_cookies.txt`
4. 在界面「Cookie 文件」处选择该文件

> 一个 `all_cookies.txt` 文件即可覆盖所有已登录平台,yt-dlp 会自动按域名筛选。

---

## 五、注意事项

- ⚠️ **Cookie 文件含你的登录凭证,切勿分享、切勿上传到任何公开位置。**
- **DRM 加密内容无法下载**:腾讯视频 / 爱奇艺的部分会员专享剧、电影为 DRM 加密,任何工具都无法下载(日志会提示 `DRM`)。能在网页正常播放的非加密视频通常都能下。
- **抖音博主批量**:会弹出浏览器自动滚动收集列表,**请勿手动操作该浏览器**,收集完会自动关闭并开始下载。
- **并发数**不是越大越好,过大可能触发平台对你 IP 的限流;建议 3~4,失败多时调小重跑(已下载的会跳过)。
- **不同清晰度独立记录**:已下 360p 视频后再下 MP3 音频不会被跳过(各清晰度有独立的 `downloaded_archive_*.txt`)。
- 下载内容请遵守各平台服务条款,仅用于个人学习与备份,请勿用于商业用途或侵犯版权。

---

## 六、项目结构

```
gui.py                          图形界面主程序(打包成 exe 的源码)
downloader.py                   命令行下载器(B站/抖音单个/合集)
douyin_user_playwright.py       抖音博主全部作品下载(Playwright)
douyin_favorites_playwright.py  抖音收藏夹下载(Playwright)
requirements.txt                Python 依赖
dist/视频下载器.exe              打包好的免安装程序
```

---

## 七、自行打包 EXE

```bash
pyinstaller --onefile --windowed --name "视频下载器" ^
  --collect-all yt_dlp --collect-all playwright --noconfirm gui.py
```
产物在 `dist/视频下载器.exe`。

---

## 版本

**v1.0**(首个版本)— 已验证:B站单个视频、抖音单个视频、B站多视频合集、抖音博主作品合集;含源码与免安装应用。
