"""Small Tk GUI for l99screen: pick or drop a picture/GIF, preview it, upload it."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from . import encode, protocol

try:  # optional drag-and-drop support
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # pragma: no cover - depends on optional package
    TkinterDnD = None

FILETYPES = [("Images and animations", "*.gif *.png *.jpg *.jpeg *.bmp *.webp *.apng"),
             ("All files", "*.*")]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("L99 Screen")
        root.resizable(False, False)

        self.path: str | None = None
        self.animated = False
        self.frames: list[Image.Image] = []
        self.delays: list[int] = []
        self._tk_frames: list[ImageTk.PhotoImage] = []
        self._anim_job = None
        self._render_token = 0
        self._busy = False
        self.events: queue.Queue = queue.Queue()

        self.fit = tk.StringVar(value="cover")
        self.rotate = tk.StringVar(value="0")
        self.target = tk.StringVar(value="auto")
        self.delay = tk.IntVar(value=0)
        self.port = tk.StringVar()
        self.status = tk.StringVar(value="Open or drop a picture or GIF.")

        self._build()
        self.refresh_ports()
        self.root.after(50, self._poll)

    # ---------------------------------------------------------------- layout
    def _build(self):
        pad = {"padx": 8, "pady": 4}
        left = ttk.Frame(self.root, padding=8)
        left.grid(row=0, column=0, sticky="n")
        self.canvas = tk.Canvas(left, width=encode.W, height=encode.H, bg="#111",
                                highlightthickness=1, highlightbackground="#444")
        self.canvas.grid(row=0, column=0)
        self._hint = self.canvas.create_text(
            encode.W // 2, encode.H // 2, fill="#aaa", justify="center",
            text="Drop a picture or GIF here\nor click Open…" if TkinterDnD else "Click Open…")
        self.canvas.bind("<Button-1>", lambda e: self.open_dialog())

        right = ttk.Frame(self.root, padding=8)
        right.grid(row=0, column=1, sticky="ns")

        ttk.Button(right, text="Open…", command=self.open_dialog).grid(row=0, column=0, sticky="ew", **pad)
        self.file_label = ttk.Label(right, text="No file", width=34, wraplength=250)
        self.file_label.grid(row=1, column=0, sticky="w", **pad)

        box = ttk.LabelFrame(right, text="Fit", padding=6)
        box.grid(row=2, column=0, sticky="ew", **pad)
        for i, (val, txt) in enumerate([("cover", "Fill & crop"), ("contain", "Fit (letterbox)"),
                                        ("stretch", "Stretch")]):
            ttk.Radiobutton(box, text=txt, value=val, variable=self.fit,
                            command=self.rerender).grid(row=i, column=0, sticky="w")

        row = ttk.Frame(right)
        row.grid(row=3, column=0, sticky="ew", **pad)
        ttk.Label(row, text="Rotate").pack(side="left")
        cb = ttk.Combobox(row, textvariable=self.rotate, values=("0", "90", "180", "270"),
                          width=5, state="readonly")
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self.rerender())

        box = ttk.LabelFrame(right, text="Upload as", padding=6)
        box.grid(row=4, column=0, sticky="ew", **pad)
        for i, (val, txt) in enumerate([("auto", "Automatic"), ("still", "Still picture"),
                                        ("anim", "Animation")]):
            ttk.Radiobutton(box, text=txt, value=val, variable=self.target,
                            command=self.rerender).grid(row=i, column=0, sticky="w")

        row = ttk.Frame(right)
        row.grid(row=5, column=0, sticky="ew", **pad)
        ttk.Label(row, text="Frame delay (ms, 0 = from file)").pack(side="left")
        sp = ttk.Spinbox(row, from_=0, to=5000, increment=10, width=6, textvariable=self.delay,
                         command=self.rerender)
        sp.pack(side="left", padx=6)
        sp.bind("<Return>", lambda e: self.rerender())
        sp.bind("<FocusOut>", lambda e: self.rerender())
        self.info = ttk.Label(right, text="", foreground="#666")
        self.info.grid(row=6, column=0, sticky="w", **pad)

        row = ttk.Frame(right)
        row.grid(row=7, column=0, sticky="ew", **pad)
        ttk.Label(row, text="Port").pack(side="left")
        self.port_box = ttk.Combobox(row, textvariable=self.port, width=18)
        self.port_box.pack(side="left", padx=6)
        ttk.Button(row, text="↻", width=3, command=self.refresh_ports).pack(side="left")

        self.upload_btn = ttk.Button(right, text="Upload to keyboard", command=self.upload,
                                     state="disabled")
        self.upload_btn.grid(row=8, column=0, sticky="ew", padx=8, pady=(12, 4))
        self.progress = ttk.Progressbar(right, maximum=100)
        self.progress.grid(row=9, column=0, sticky="ew", **pad)
        ttk.Label(right, textvariable=self.status, wraplength=250).grid(row=10, column=0, sticky="w", **pad)

        if TkinterDnD:
            for w in (self.canvas, self.root):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)

    # ------------------------------------------------------------- actions
    def refresh_ports(self):
        try:
            from serial.tools import list_ports
            ports = [p.device for p in list_ports.comports()]
        except Exception:
            ports = []
        self.port_box["values"] = ports
        found = protocol.find_port()
        if found:
            self.port.set(found)
            self.status.set(f"Keyboard screen found on {found}.") if not self.path else None
        elif not self.port.get():
            self.status.set("Keyboard screen not found. Connect it by USB cable, then press ↻.")

    def _on_drop(self, event):
        files = self.root.tk.splitlist(event.data)
        if files:
            self.load(files[0])

    def open_dialog(self):
        path = filedialog.askopenfilename(title="Choose a picture or GIF", filetypes=FILETYPES)
        if path:
            self.load(path)

    def load(self, path: str):
        try:
            with Image.open(path) as im:
                self.animated = getattr(im, "n_frames", 1) > 1
        except Exception as e:
            messagebox.showerror("L99 Screen", f"Can't open this file:\n{e}")
            return
        self.path = path
        self.file_label.config(text=path.replace("\\", "/").rsplit("/", 1)[-1])
        self.rerender()

    def _as_animation(self) -> bool:
        t = self.target.get()
        return self.animated if t == "auto" else t == "anim"

    def rerender(self):
        if not self.path:
            return
        self._render_token += 1
        token = self._render_token
        path, fit, rot = self.path, self.fit.get(), int(self.rotate.get())
        anim = self._as_animation()
        try:
            delay = int(self.delay.get()) or None
        except (tk.TclError, ValueError):
            delay = None
        self.status.set("Preparing preview…")
        self.upload_btn.config(state="disabled")

        def work():
            try:
                if anim:
                    frames, delays = encode.load_animation(path, fit, rot, delay_ms=delay)
                else:
                    frames, delays = [encode.fit(Image.open(path), fit, rot)], [0]
                self.events.put(("rendered", token, frames, delays, anim))
            except Exception as e:
                self.events.put(("error", f"Couldn't read the file: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def _show(self, frames, delays, anim):
        self.frames, self.delays = frames, delays
        self._tk_frames = [ImageTk.PhotoImage(f) for f in frames]
        self.canvas.delete("all")
        self._img_item = self.canvas.create_image(0, 0, anchor="nw", image=self._tk_frames[0])
        if self._anim_job:
            self.root.after_cancel(self._anim_job)
            self._anim_job = None
        if anim and len(frames) > 1:
            self.info.config(text=f"Animation: {len(frames)} frames (max {encode.MAX_FRAMES}), "
                                  f"{sum(delays) / 1000:.1f}s loop")
            self._animate(0)
        else:
            self.info.config(text="Still picture, 320×480")
        self.upload_btn.config(state="normal" if not self._busy else "disabled")
        self.status.set("Ready to upload.")

    def _animate(self, i):
        self.canvas.itemconfig(self._img_item, image=self._tk_frames[i])
        nxt = (i + 1) % len(self._tk_frames)
        self._anim_job = self.root.after(max(20, self.delays[i]), self._animate, nxt)

    def upload(self):
        if not self.frames or self._busy:
            return
        port = self.port.get() or None
        anim = self._as_animation() and len(self.frames) > 1
        frames, delays = list(self.frames), list(self.delays)
        self._busy = True
        self.upload_btn.config(state="disabled")
        self.progress["value"] = 0
        self.status.set("Encoding…")

        def work():
            try:
                if anim:
                    base, blob = protocol.GIF_ADDR, encode.encode_animation(frames, delays)
                else:
                    base, blob = protocol.STILL_ADDR, encode.encode_still(frames[0])
                with protocol.Screen(port) as scr:
                    self.events.put(("status", f"Uploading on {scr.port}…"))
                    scr.upload(base, blob, lambda i, n: self.events.put(("progress", i * 100 / n)))
                self.events.put(("done", "Uploaded. The keyboard screen should update now."))
            except PermissionError as e:
                self.events.put(("failed", f"No permission to open the port ({e}). "
                                           "On Linux install the udev rule from the README."))
            except Exception as e:
                self.events.put(("failed", f"Upload failed: {e}"))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------- event pump
    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "rendered" and ev[1] == self._render_token:
                    self._show(*ev[2:])
                elif kind == "progress":
                    self.progress["value"] = ev[1]
                elif kind == "status":
                    self.status.set(ev[1])
                elif kind in ("done", "failed", "error"):
                    self._busy = False
                    self.status.set(ev[1])
                    if self.frames:
                        self.upload_btn.config(state="normal")
                    if kind == "failed":
                        messagebox.showerror("L99 Screen", ev[1])
        except queue.Empty:
            pass
        self.root.after(50, self._poll)


def main(argv=None) -> int:
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    app = App(root)
    if argv:
        app.load(argv[0])
    root.mainloop()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
