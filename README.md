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
| 浏览器右键下载 | Chrome / Edge 扩展,视频页右键「用 VidFetch 下载」自动下载 | ✅ |

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

1. 双击 `VidFetch.exe`
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

## 四、保姆级使用指南（强烈建议第一次按此操作）

> 下面是从零开始的完整步骤。**不下载会员/高清/需登录的内容时，第 2~4 步的 Cookie 可以跳过**，直接看第 5 步。

### 第 1 步：下载并打开 VidFetch

1. 到本仓库的 **[Releases](../../releases)** 页面，下载 `VidFetch_v1.0.exe`
2. 放到任意文件夹（如 `D:\VidFetch\`），**双击运行**（免安装，无需管理员权限）
3. 首次打开会出现深色界面：视频链接、清晰度、保存目录、Cookie 文件、下载按钮

> 💡 若 Windows 弹出「已保护你的电脑」蓝色提示，点 **更多信息 → 仍要运行**（因为 exe 未做数字签名，属正常现象）。

### 第 2 步：安装 Chrome 扩展「Get cookies.txt LOCALLY」

> 这个扩展用来把你已登录的网站 Cookie 导出成文件，VidFetch 用它来「以你的身份」下载会员/高清内容。

1. 打开 Chrome，访问 Chrome 应用商店：
   https://chromewebstore.google.com/
2. 在搜索框输入 **`Get cookies.txt LOCALLY`**
3. 找到该扩展，点 **「添加至 Chrome」→「添加扩展程序」**
4. 安装后，点浏览器右上角的「拼图」🧩图标，把 **Get cookies.txt LOCALLY** 旁边的「图钉」点亮，让它固定显示在工具栏

### 第 3 步：登录网站，并导出 Cookie

1. 在 Chrome 里打开 **抖音**（https://www.douyin.com）**或 B站**（https://www.bilibili.com）
2. **用你自己的账号登录**（确认右上角显示你的头像 = 已登录）
   - 下载 B站 4K / 大会员内容，需要登录**有大会员的账号**
   - 下载抖音博主作品，需要登录任意抖音账号
3. **保持停留在该网站的页面上**（很重要，扩展导出的是「当前所在网站」的 Cookie）
4. 点工具栏上的 **Get cookies.txt LOCALLY** 图标
5. 点 **「Export All Cookies」**（导出全部网站的 Cookie，一个文件通吃所有平台）
6. 浏览器会下载一个 `.txt` 文件，把它改名为 `all_cookies.txt`，记住保存位置（如 `D:\VidFetch\all_cookies.txt`）

> 💡 **一个 `all_cookies.txt` 就够了**：它包含你所有已登录网站的 Cookie，VidFetch（yt-dlp）会自动按网站域名挑选对应的那部分，无需为每个网站单独导出。
> 想同时支持多个平台？登录哪个就先访问哪个页面，分别用「Export All Cookies」覆盖同一个文件即可（最后导出的会包含之前访问过且仍登录的站点）。

### 第 4 步：把 Cookie 加载到 VidFetch

1. 回到 VidFetch 界面
2. 找到 **「Cookie 文件」** 那一栏，点右侧 **「选择」** 按钮
3. 选中第 3 步保存的 `all_cookies.txt`
4. 完成。之后下载会员/高清/需登录内容都会自动带上你的登录态

### 第 5 步：开始下载

1. **复制链接**：在浏览器地址栏或分享按钮复制视频/博主主页链接
2. 回到 VidFetch，点 **「粘贴」** 按钮（会自动清除多余换行）
3. 选 **清晰度**；如果是批量下载，右边的数字是**同时下载几个**（1~5）
4. 选 **保存目录**
5. 点 **下载**，进度和日志会实时显示

> ⚠️ **Cookie 文件含你的登录凭证（等同账号密码），切勿发给别人、切勿上传到任何公开位置！**

---

## 五、关于 ffmpeg（合并音视频 / 转 MP3 的必备工具）

**你不需要手动安装 ffmpeg。** VidFetch 会自动处理：

- 启动时自动检测系统是否已有 ffmpeg（PATH 中，或 exe 同级的 `ffmpeg/` 文件夹）
- 如果**没检测到**，界面底部会显示红字「✗ 未检测到 ffmpeg」，并在你点下载时**弹窗询问是否自动下载**
- 点「是」后，程序会**自动从网上下载并安装** ffmpeg（约 30MB，进度显示在日志区），完成后即可正常下载
- 下载的 ffmpeg 会放在 exe 同级的 `ffmpeg/` 文件夹，**只需装一次**，以后自动复用

> 所以全程只要有网络，ffmpeg 完全自动搞定，无需你操心。

---

## 六、抖音博主「全部作品」下载的特别说明 ⚠️

当你粘贴的是**抖音博主主页链接**（`douyin.com/user/...`）时，VidFetch 需要先把该博主的所有视频链接「爬」下来：

1. 点下载后，**会自动弹出一个浏览器窗口**，自动打开该博主主页
2. **此时切记：不要碰鼠标、不要操作这个浏览器！** 程序正在自动滚动页面、收集全部视频地址
3. 你会在 VidFetch 日志里看到「已收集 X/总数 个视频...」实时增长
4. 收集完成后，**浏览器会自动关闭**，然后开始批量下载
5. 整个收集过程通常几十秒到一两分钟（视频越多越久），**耐心等待即可**

> 💡 如果手动操作了那个浏览器（比如滚动、点击、关闭），可能导致收集中断或不全。让它自己跑完就好。

---

## ★ 浏览器扩展（Chrome / Edge 右键下载）

在浏览器视频页面**右键 →「用 VidFetch 下载此视频」**，即可调用本地 VidFetch 自动下载，无需手动复制链接。

### 原理（Native Messaging，不经应用商店）
```
视频页右键 → 扩展(MV3) → 本地宿主 vidfetch_host.exe → 启动 VidFetch.exe --url <地址> → 自动下载
```
- 扩展只负责把「当前页面地址」交给本地 VidFetch（真正的解析/下载仍由 yt-dlp 完成）。
- VidFetch 单实例：再次触发会把地址转发给已打开的窗口（仅本机 `127.0.0.1`，不对外）。

### 安装（手动加载，三步）
1. 解压扩展包，双击 **`install_extension.bat`** 注册宿主（写当前用户注册表，无需管理员）。
2. Chrome/Edge → 扩展页 → 开**开发者模式** → **加载已解压的扩展** → 选 `browser_extension` 文件夹。
3. 打开视频页 → 右键 →「用 VidFetch 下载此视频」。

> **⚠️ 首次安装后请完全重启一次 Chrome / Edge**（MV3 后台脚本首次激活 + 新注册宿主的识别，都需要一次重启；只此一次，之后永久正常）。

> 详细步骤与常见问题见 **[README_extension.md](README_extension.md)**。
> 扩展相关文件位于仓库 `browser_extension/`、`host.py`、`install_extension.*`。
> 未上架 Chrome/Edge 商店（视频下载类审核易被拒），采用手动加载分发。

---

## 七、注意事项

- ⚠️ **Cookie 文件含你的登录凭证,切勿分享、切勿上传到任何公开位置。**
- **DRM 加密内容无法下载**:腾讯视频 / 爱奇艺的部分会员专享剧、电影为 DRM 加密,任何工具都无法下载(日志会提示 `DRM`)。能在网页正常播放的非加密视频通常都能下。
- **并发数**不是越大越好,过大可能触发平台对你 IP 的限流;建议 3~4,失败多时调小重跑(已下载的会跳过)。
- **不同清晰度独立记录**:已下 360p 视频后再下 MP3 音频不会被跳过(各清晰度有独立的 `downloaded_archive_*.txt`)。
- 下载内容请遵守各平台服务条款,仅用于个人学习与备份,请勿用于商业用途或侵犯版权。

---

## 八、项目结构

```
gui.py                          图形界面主程序(打包成 exe 的源码)
downloader.py                   命令行下载器(B站/抖音单个/合集)
douyin_user_playwright.py       抖音博主全部作品下载(Playwright)
douyin_favorites_playwright.py  抖音收藏夹下载(Playwright)
requirements.txt                Python 依赖
dist/VidFetch.exe              打包好的免安装程序
```

---

## 九、自行打包 EXE

```bash
pyinstaller --onefile --windowed --name "VidFetch" ^
  --collect-all yt_dlp --collect-all playwright --noconfirm gui.py
```
产物在 `dist/VidFetch.exe`。

---

## 版本

**v1.0**(首个版本)— 已验证:B站单个视频、抖音单个视频、B站多视频合集、抖音博主作品合集;含源码与免安装应用。
