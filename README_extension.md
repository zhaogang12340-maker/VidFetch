# VidFetch 浏览器扩展（右键下载）安装说明

在 Chrome / Edge 的视频页面右键「用 VidFetch 下载此视频」，即可调用本地 VidFetch 自动下载。
采用 **Native Messaging + 手动加载**（不经应用商店）。

## 一、文件准备（放在同一个文件夹）
把下面这些放进同一目录（例如 `D:\VidFetch\`）：

```
VidFetch_v1.06.exe         ← 主程序
ffmpeg\                    ← 主程序自带的 ffmpeg 文件夹
vidfetch_host.exe          ← Native Messaging 宿主（本扩展用）
install_extension.bat      ← 一键注册脚本
uninstall_extension.bat    ← 注销脚本
install_extension.ps1      ← 注册脚本（被 .bat 调用）
browser_extension\         ← 扩展本体（用于“加载已解压的扩展”）
```

## 二、注册宿主（一次即可）
双击 **`install_extension.bat`**（普通用户即可，写入当前用户注册表 HKCU）。
它会：
- 生成 `com.vidfetch.host.json`（指向同目录的 `vidfetch_host.exe`）
- 在 Chrome 和 Edge 各注册一处 Native Messaging 宿主

> 换了文件夹位置后，**重新双击一次** install_extension.bat 即可（路径会更新）。

## 三、加载扩展
1. 打开 Chrome/Edge 的 **扩展管理**（`chrome://extensions` 或 `edge://extensions`）
2. 打开右上角 **开发者模式**
3. 点 **加载已解压的扩展程序** → 选择 `browser_extension` 文件夹
4. 加载后，扩展 ID 应为：`iklkefonkeckmifmdkbniphnngimfdgm`
   （由 manifest 里的 `key` 固定；install 脚本已按此 ID 授权，二者必须一致）

## 四、使用
- 打开任意视频页面（B站 / YouTube / 抖音等）
- 在**视频上**或**页面空白处**右键 → **「用 VidFetch 下载此视频」**
- VidFetch 会自动弹到前台并开始下载（用当前界面里的清晰度等设置）
- 若 VidFetch 没开着，会自动启动

## 常见问题
- **点了没反应 / 提示“无法连接 VidFetch”**：先运行过 `install_extension.bat` 了吗？换过目录要再跑一次。
- **下到的是 blob 地址**：扩展发送的是“观看页地址”而非视频流地址，正常；yt-dlp 需要的就是观看页地址。
- **想换清晰度/Cookie**：先在 VidFetch 主界面设置好，再用右键下载（会沿用当前设置）。
- **卸载**：浏览器扩展页移除扩展；再双击 `uninstall_extension.bat` 注销宿主。

## 技术说明
- 扩展（MV3）右键 → `chrome.runtime.sendNativeMessage` → `vidfetch_host.exe`（读 stdin 的 `{url}`）→ 启动 `VidFetch.exe --url <地址>`。
- VidFetch 单实例：第二次启动会把地址转发给已运行的窗口（仅 `127.0.0.1`，不对外）。
