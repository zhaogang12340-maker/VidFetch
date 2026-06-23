// VidFetch 下载助手 —— 后台 service worker (MV3)
// 右键菜单 → 取当前页面/链接地址 → 通过 Native Messaging 发给本地 vidfetch_host

const HOST = "com.vidfetch.host";
const MENU_ID = "vidfetch-download";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: "用 VidFetch 下载此视频",
    // 在视频上、页面空白处、链接上右键都会出现
    contexts: ["video", "page", "link"]
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== MENU_ID) return;
  // yt-dlp 需要的是“观看页”地址，而不是 <video> 的 blob 流地址：
  // 优先用右键的链接(linkUrl)，否则用当前页面地址(pageUrl)。
  const url = info.linkUrl || info.pageUrl || (tab && tab.url) || "";
  if (!url) { notify("未能获取视频链接"); return; }

  chrome.runtime.sendNativeMessage(HOST, { url: url }, (resp) => {
    if (chrome.runtime.lastError) {
      notify("无法连接 VidFetch：" + chrome.runtime.lastError.message +
             "（请确认已运行 install_extension.bat 注册宿主）");
    } else if (resp && resp.ok) {
      notify("已发送到 VidFetch 开始下载：\n" + url);
    } else {
      notify("VidFetch 宿主返回异常：" + JSON.stringify(resp));
    }
  });
});

function notify(message) {
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icons/icon128.png",
    title: "VidFetch",
    message: message
  });
}
