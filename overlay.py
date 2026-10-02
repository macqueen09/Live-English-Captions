"""Native Windows translucent, always-on-top captions; no browser required."""

import ctypes
import json
import queue
import threading
import tkinter as tk
import urllib.request
from datetime import datetime
from version import VERSION

BASE = "http://127.0.0.1:8765"


def main():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    mutex = kernel.CreateMutexW(None, False, "Local\\LiveEnglishCaptionsOverlay")
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(mutex)
        return
    root = tk.Tk()
    root.title("Live English Captions — Overlay")
    root.geometry("980x340+180+600")
    root.minsize(420, 180)
    root.configure(bg="#101622")
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.86)
    root.overrideredirect(True)
    alive = threading.Event()
    alive.set()
    updates = queue.Queue()
    last_id = 0
    previous = None

    bar = tk.Frame(root, bg="#1a2333")
    bar.pack(fill="x")
    status = tk.Label(
        bar,
        text="Live English Captions · 拖动此处移动窗口",
        fg="#aabcda",
        bg="#1a2333",
        padx=12,
    )
    status.pack(side="left")

    def close():
        alive.clear()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)

    def button(text, command):
        tk.Button(
            bar,
            text=text,
            command=command,
            bg="#223047",
            fg="white",
            relief="flat",
            padx=9,
        ).pack(side="right", padx=3, pady=4)

    button("关闭", close)
    button("跟随最新", lambda: captions.see("end"))

    def stop_recording():
        def request():
            try:
                req = urllib.request.Request(
                    BASE + "/api/stop",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=4):
                    pass
            except Exception:
                updates.put({"status": "停止请求失败，请确认服务正在运行", "rows": []})

        threading.Thread(target=request, daemon=True).start()

    button("停止记录", stop_recording)
    alpha = tk.DoubleVar(value=0.86)
    tk.Scale(
        bar,
        from_=0.35,
        to=1.0,
        resolution=0.05,
        orient="horizontal",
        variable=alpha,
        command=lambda value: root.attributes("-alpha", float(value)),
        length=95,
        showvalue=False,
        bg="#1a2333",
        highlightthickness=0,
        troughcolor="#34445e",
    ).pack(side="right")
    tk.Label(bar, text="透明度", fg="#aabcda", bg="#1a2333").pack(side="right")
    captions = tk.Text(
        root,
        bg="#101622",
        fg="#eef3fc",
        wrap="word",
        relief="flat",
        padx=15,
        pady=8,
        cursor="arrow",
        selectbackground="#365fc5",
        state="disabled",
    )
    captions.pack(fill="both", expand=True)
    captions.tag_configure("en", font=("Segoe UI", 22), spacing1=6)
    captions.tag_configure(
        "zh", font=("Microsoft YaHei", 11), foreground="#b4c2d8", spacing3=7
    )
    captions.tag_configure("meta", font=("Microsoft YaHei", 8), foreground="#899dbb")
    grip = tk.Label(root, text="◢", bg="#101622", fg="#899dbb", cursor="size_nw_se")
    grip.place(relx=1, rely=1, anchor="se")
    origin = {}

    def begin(event):
        origin.update(
            x=event.x_root,
            y=event.y_root,
            left=root.winfo_x(),
            top=root.winfo_y(),
            width=root.winfo_width(),
            height=root.winfo_height(),
        )

    def move(event):
        root.geometry(
            f"+{origin['left'] + event.x_root - origin['x']}+{origin['top'] + event.y_root - origin['y']}"
        )

    def resize(event):
        root.geometry(
            f"{max(420, origin['width'] + event.x_root - origin['x'])}x{max(180, origin['height'] + event.y_root - origin['y'])}"
        )

    for widget in (bar, status):
        widget.bind("<Button-1>", begin)
        widget.bind("<B1-Motion>", move)
    grip.bind("<Button-1>", begin)
    grip.bind("<B1-Motion>", resize)
    root.bind("<Escape>", lambda event: close())

    def fetch():
        after = 0
        while alive.is_set():
            try:
                with urllib.request.urlopen(
                    f"{BASE}/api/state?after={after}", timeout=4
                ) as response:
                    state = json.load(response)
                if state["rows"]:
                    after = max(row["id"] for row in state["rows"])
                updates.put(state)
            except Exception:
                updates.put(
                    {"status": "服务未连接，请双击桌面快捷方式恢复", "rows": []}
                )
            # Interruptible wait without blocking the UI thread.
            for _ in range(20):
                if not alive.is_set():
                    return
                threading.Event().wait(0.1)

    def render():
        nonlocal last_id, previous
        while not updates.empty():
            state = updates.get_nowait()
            status.configure(
                text=f"Live English Captions {VERSION} · " + state["status"]
            )
            follow = captions.yview()[1] >= 0.995 and not captions.tag_ranges("sel")
            position = captions.index("@0,0")
            captions.configure(state="normal")
            for row in state["rows"]:
                if row["id"] <= last_id:
                    continue
                gap = (
                    (
                        datetime.fromisoformat(row["timestamp"])
                        - datetime.fromisoformat(previous["timestamp"])
                    ).total_seconds()
                    if previous
                    else 999
                )
                merge = (
                    previous
                    and previous["source"] == row["source"]
                    and previous["speaker"] == row["speaker"]
                    and 0 <= gap <= 12
                    and len(previous["en"]) + len(row["en"]) < 380
                )
                if merge:
                    for mark, text, tag in [
                        ("lastEnglishEnd", " " + row["en"], "en"),
                        ("lastChineseEnd", " " + row["zh"], "zh"),
                    ]:
                        at = captions.index(mark)
                        captions.insert(at, text, tag)
                        captions.mark_set(mark, f"{at}+{len(text)}c")
                    row = dict(row, en=previous["en"] + " " + row["en"])
                else:
                    captions.insert("end", row["en"], "en")
                    captions.mark_set("lastEnglishEnd", "end-1c")
                    captions.mark_gravity("lastEnglishEnd", "left")
                    captions.insert(
                        "end", f"  {row['time']} · {row['speaker']}\n", "meta"
                    )
                    captions.insert("end", row["zh"], "zh")
                    captions.mark_set("lastChineseEnd", "end-1c")
                    captions.mark_gravity("lastChineseEnd", "left")
                    captions.insert("end", "\n", "zh")
                last_id = row["id"]
                previous = row
            captions.configure(state="disabled")
            if follow:
                captions.see("end")
            else:
                captions.yview(position)
        if alive.is_set():
            root.after(150, render)

    threading.Thread(target=fetch, daemon=True).start()
    root.after(100, render)
    root.mainloop()
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
