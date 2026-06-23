#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VidFetch Native Messaging 宿主（控制台小程序，打包为 vidfetch_host.exe）。

Chrome/Edge 扩展通过 Native Messaging 把 {"url": "..."} 写到本程序的 stdin，
本程序解析后，找到同目录下的 VidFetch 主程序并以 `--url <地址>` 启动它进行下载，
再向 stdout 回写 {"ok": true}。

Native Messaging 协议：每条消息 = 4字节小端长度 + 该长度的 UTF-8 JSON。
"""
import sys, os, json, struct, subprocess, glob


def _read_message():
    raw_len = sys.stdin.buffer.read(4)
    if len(raw_len) < 4:
        return None
    (length,) = struct.unpack("<I", raw_len)
    data = sys.stdin.buffer.read(length).decode("utf-8")
    return json.loads(data)


def _send_message(obj):
    data = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _host_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _find_vidfetch():
    """在宿主同目录找 VidFetch 主程序（排除自身）。"""
    d = _host_dir()
    me = os.path.basename(sys.executable if getattr(sys, "frozen", False) else __file__).lower()
    cands = sorted(glob.glob(os.path.join(d, "VidFetch*.exe")))
    for c in cands:
        if os.path.basename(c).lower() != me and "host" not in os.path.basename(c).lower():
            return c
    return None


def _launch(url):
    exe = _find_vidfetch()
    if not exe:
        return False, "未在同目录找到 VidFetch*.exe"
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([exe, "--url", url], cwd=os.path.dirname(exe),
                     creationflags=flags, close_fds=True)
    return True, exe


def main():
    try:
        msg = _read_message()
        if not msg:
            return
        url = (msg.get("url") or "").strip()
        if not url:
            _send_message({"ok": False, "error": "empty url"})
            return
        ok, info = _launch(url)
        _send_message({"ok": ok, "info": os.path.basename(info) if ok else info})
    except Exception as e:
        try:
            _send_message({"ok": False, "error": str(e)[:200]})
        except Exception:
            pass


if __name__ == "__main__":
    main()
