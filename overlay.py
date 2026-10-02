"""Native Windows translucent, always-on-top captions; no browser required."""

import ctypes
import json
import queue
import threading
import tkinter as tk
import urllib.request
from datetime import datetime
from version import VERSION
from caption_layout import LiveParagraphs
from native_view import NativeParagraphs, NativeChinese

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
    follow_latest = True
    follow_chinese = True
    highlight_id = 0
    lookup_generation = 0
    lookup_window = None
    layout = LiveParagraphs()

    bar = tk.Frame(root, bg="#1a2333")
    bar.pack(fill="x")
    status = tk.Label(
        bar,
        text="Live English Captions · 拖动此处移动窗口",
        fg="#aabcda",
        bg="#1a2333",
        padx=12,
        width=1,
        anchor="w",
    )
    status.pack(side="left", fill="x", expand=True)

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
    def follow():
        nonlocal follow_latest, follow_chinese
        follow_latest = True
        follow_chinese = True
        captions.tag_remove("sel", "1.0", "end")
        captions.see("end")
        chinese.see("end")

    button("跟随最新", follow)

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
    chinese = tk.Text(root, height=4, bg="#121d2c", fg="#b4c2d8", wrap="word", relief="flat",
                      padx=15, pady=5, font=("Microsoft YaHei", 11), state="disabled", cursor="arrow")
    chinese.pack(side="bottom", fill="x")
    chinese.tag_configure("zh", font=("Microsoft YaHei", 11), foreground="#b4c2d8")
    chinese.tag_configure("meta", font=("Microsoft YaHei", 8), foreground="#899dbb")
    captions.pack(fill="both", expand=True)
    captions.tag_configure("en", font=("Segoe UI", 22), spacing1=6)
    captions.tag_configure(
        "zh", font=("Microsoft YaHei", 11), foreground="#b4c2d8", spacing3=7
    )
    captions.tag_configure("meta", font=("Microsoft YaHei", 8), foreground="#899dbb")

    def user_scroll(event):
        # Only user scrolling changes the sticky follow mode.
        def changed():
            nonlocal follow_latest
            follow_latest = captions.yview()[1] >= 0.995
        root.after_idle(changed)

    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>", "<KeyRelease-Prior>", "<KeyRelease-Next>", "<KeyRelease-Home>", "<KeyRelease-End>"):
        captions.bind(sequence, user_scroll, add="+")

    def chinese_scroll(event):
        def changed():
            nonlocal follow_chinese
            follow_chinese = chinese.yview()[1] >= .995
        root.after_idle(changed)
    chinese.bind("<MouseWheel>", chinese_scroll, add="+")

    def insert_fresh(at, text, language, widget=None):
        nonlocal highlight_id
        highlight_id += 1
        widget = widget or captions
        tag = f"fresh{highlight_id}"
        # Colour only: adding/removing emphasis must never change glyph metrics.
        widget.tag_configure(tag, background="#25465d", foreground="#fff0b3")
        widget.insert(at, text, (language, tag))
        widget.tag_raise("sel")
        root.after(4500, lambda: widget.tag_delete(tag) if alive.is_set() else None)

    english_view = NativeParagraphs(captions, insert_fresh)
    chinese_view = NativeChinese(chinese, insert_fresh)

    def post(path, body):
        request = urllib.request.Request(BASE + "/api/" + path,
            data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def select_word(event=None):
        nonlocal lookup_window, lookup_generation
        ranges = captions.tag_ranges("sel")
        if not ranges:
            return
        start, end = ranges
        # Both ends and every character must belong to English, not metadata/Chinese.
        context = None
        english = captions.tag_ranges("en")
        for left, right in zip(english[::2], english[1::2]):
            if captions.compare(start, ">=", left) and captions.compare(end, "<=", right):
                context = captions.get(left, right).strip()
                break
        term = captions.get(start, end).strip()
        if context is None or not term or len(term) > 120:
            return
        lookup_generation += 1
        if lookup_window is not None and lookup_window.winfo_exists():
            lookup_window.destroy()
        popup = lookup_window = tk.Toplevel(root)
        popup.title("选词翻译 · 个人单词本")
        popup.attributes("-topmost", True)
        popup.geometry(f"440x230+{root.winfo_x()+40}+{root.winfo_y()+40}")
        value = tk.StringVar(value=term)
        tk.Entry(popup, textvariable=value, font=("Segoe UI", 14)).pack(fill="x", padx=12, pady=10)
        result = tk.Label(popup, text="点击翻译查看释义", wraplength=410, font=("Microsoft YaHei", 11))
        result.pack(fill="x", padx=12, pady=8)
        saved = {"term": term, "zh": "", "context": context}

        def launch(path, body, callback):
            generation = lookup_generation
            def worker():
                try:
                    data, error = post(path, body), None
                except Exception as exc:
                    data, error = None, str(exc)
                updates.put({"callback": lambda: callback(data, error) if generation == lookup_generation and popup.winfo_exists() else None})
            threading.Thread(target=worker, daemon=True).start()

        def translate():
            nonlocal lookup_generation
            lookup_generation += 1
            saved["zh"] = ""
            save.configure(state="disabled")
            result.configure(text="正在本机翻译…")
            def done(data, error):
                if error:
                    result.configure(text=error)
                    return
                saved.update(term=data["term"], zh=data["zh"])
                result.configure(text=data["zh"])
                save.configure(state="normal")
            launch("translate-word", {"term": value.get().strip()}, done)

        def save_word():
            save.configure(state="disabled")
            def done(data, error):
                result.configure(text=error or "已保存到个人本地单词本。")
                if error:
                    save.configure(state="normal")
            launch("words", dict(saved), done)

        def edited(*args):
            nonlocal lookup_generation
            lookup_generation += 1
            saved["zh"] = ""
            save.configure(state="disabled")
            result.configure(text="点击翻译查看释义")

        tk.Button(popup, text="单独翻译", command=translate).pack(side="left", padx=12, pady=12)
        save = tk.Button(popup, text="保存到生词本", state="disabled", command=save_word)
        save.pack(side="left", padx=12, pady=12)
        value.trace_add("write", edited)

    captions.bind("<ButtonRelease-1>", select_word, add="+")
    captions.bind("<KeyRelease>", lambda event: select_word() if event.state & 1 else None, add="+")
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
        revision = -1
        while alive.is_set():
            wait_steps = 1
            try:
                with urllib.request.urlopen(
                    f"{BASE}/api/live?after={after}&revision={revision}", timeout=20
                ) as response:
                    state = json.load(response)
                revision = state.get("revision", -1)
                if state["rows"]:
                    after = max(row["id"] for row in state["rows"])
                updates.put(state)
            except Exception:
                wait_steps = 10
                updates.put(
                    {"status": "服务未连接，请双击桌面快捷方式恢复", "rows": []}
                )
            # Interruptible wait without blocking the UI thread.
            for _ in range(wait_steps):
                if not alive.is_set():
                    return
                threading.Event().wait(0.1)

    def render():
        nonlocal last_id
        while not updates.empty():
            state = updates.get_nowait()
            if "callback" in state:
                state["callback"]()
                continue
            hardware = state.get("hardware", {})
            mode = f"ASR {hardware.get('asr_model', 'small.en')} {hardware.get('asr', '--')} / 中文 {hardware.get('translation', '--')}"
            title = f"Live English Captions {VERSION} · {mode}"
            root.title(title)
            status.configure(text=title + " · " + state["status"])
            should_follow = follow_latest and not captions.tag_ranges("sel")
            position = captions.index("@0,0")
            captions.configure(state="normal")
            paragraphs = state.get("paragraphs")
            if paragraphs is None:
                paragraphs = layout.apply(state["rows"] + state.get("updates", []), state.get("partials", []))
            english_view.sync(paragraphs)
            captions.configure(state="disabled")
            rows = [row for paragraph in paragraphs for row in paragraph["rows"]]
            chinese_view.sync(rows + state.get("updates", []), follow=follow_chinese)
            if state["rows"]:
                last_id = max(last_id, max(row["id"] for row in state["rows"]))
            if should_follow:
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
