"""Tk GUI for l99screen: drop a picture or GIF, preview it on a mock screen, upload it."""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from PIL import Image, ImageTk

from . import __version__, encode, linux_access, protocol

try:  # optional drag-and-drop support
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # pragma: no cover - depends on optional package
    TkinterDnD = None

FILETYPES = [("Images and animations", "*.gif *.png *.jpg *.jpeg *.bmp *.webp *.apng"),
             ("All files", "*.*")]

# ---- palette (dark, with AULA's orange as the accent) ----------------------------------
BG = "#14151b"
CARD = "#1d1f28"
FIELD = "#272a36"
BORDER = "#30333f"
TEXT = "#eceef4"
MUTED = "#9497a8"
FAINT = "#6b6e80"
ACCENT = "#ff7a33"
ACCENT_HI = "#ff9354"
ACCENT_LO = "#7a4a2f"
OK = "#3ecf8e"
WARN = "#f5b041"
ERR = "#ff5f5f"
BEZEL = "#0b0c10"

PAD = 16          # outer padding
BEZEL_PAD = 14    # mock screen bezel around the 320x480 preview


def _rounded_rect(cv: tk.Canvas, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("L99 Screen")
        root.configure(bg=BG)
        root.resizable(False, False)

        self.path: str | None = None
        self.animated = False
        self.frames: list[Image.Image] = []
        self.delays: list[int] = []
        self._tk_frames: list[ImageTk.PhotoImage] = []
        self._img_item = None
        self._anim_job = None
        self._render_token = 0
        self._busy = False
        self._connected_port: str | None = None
        self.events: queue.Queue = queue.Queue()

        self.fit = tk.StringVar(value="cover")
        self.rotate = tk.StringVar(value="0")
        self.target = tk.StringVar(value="auto")
        self.delay = tk.IntVar(value=0)
        self.port = tk.StringVar()
        self.status = tk.StringVar(value="Drop a picture or GIF to get started.")
        self._adv_open = False

        self._fonts()
        self._style()
        self._build()
        self.refresh_ports()
        self.root.after(50, self._poll)
        self.root.after(2000, self._watch_connection)

    # ------------------------------------------------------------------ styling
    def _fonts(self):
        base = tkfont.nametofont("TkDefaultFont")
        fam = base.actual("family")
        self.f_body = (fam, 10)
        self.f_small = (fam, 9)
        self.f_label = (fam, 9, "bold")
        self.f_title = (fam, 15, "bold")
        self.f_name = (fam, 11, "bold")
        self.f_button = (fam, 12, "bold")
        self.f_hint_big = (fam, 13, "bold")

    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=TEXT, font=self.f_body,
                    bordercolor=BORDER, lightcolor=BG, darkcolor=BG, troughcolor=FIELD,
                    focuscolor=ACCENT, selectbackground=ACCENT, selectforeground="#ffffff")
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("TLabel", background=BG, foreground=TEXT)
        s.configure("Card.TLabel", background=CARD, foreground=TEXT)
        s.configure("Muted.Card.TLabel", background=CARD, foreground=MUTED, font=self.f_small)
        s.configure("Section.Card.TLabel", background=CARD, foreground=MUTED, font=self.f_label)
        s.configure("Name.Card.TLabel", background=CARD, foreground=TEXT, font=self.f_name)
        s.configure("Title.TLabel", background=BG, foreground=TEXT, font=self.f_title)
        s.configure("Muted.TLabel", background=BG, foreground=MUTED, font=self.f_small)
        s.configure("Faint.TLabel", background=BG, foreground=FAINT, font=self.f_small)

        # segmented buttons
        s.configure("Seg.Toolbutton", background=FIELD, foreground=MUTED, padding=(10, 6),
                    borderwidth=0, relief="flat", anchor="center", font=self.f_body)
        s.map("Seg.Toolbutton",
              background=[("disabled", FIELD), ("selected", ACCENT), ("active", "#323646")],
              foreground=[("disabled", FAINT), ("selected", "#ffffff"), ("active", TEXT)])

        # buttons
        s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", font=self.f_button,
                    padding=(16, 12), borderwidth=0, relief="flat", anchor="center")
        s.map("Accent.TButton",
              background=[("disabled", ACCENT_LO), ("pressed", "#e8662a"), ("active", ACCENT_HI)],
              foreground=[("disabled", "#c9a993")])
        s.configure("Ghost.TButton", background=FIELD, foreground=TEXT, padding=(12, 7),
                    borderwidth=0, relief="flat")
        s.map("Ghost.TButton", background=[("pressed", "#3a3e50"), ("active", "#323646")])
        s.configure("Link.TButton", background=CARD, foreground=MUTED, padding=(0, 2),
                    borderwidth=0, relief="flat", font=self.f_small)
        s.map("Link.TButton", background=[("active", CARD)], foreground=[("active", TEXT)])

        # inputs
        for w in ("TCombobox", "TSpinbox"):
            s.configure(w, fieldbackground=FIELD, background=FIELD, foreground=TEXT,
                        arrowcolor=MUTED, bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD,
                        padding=4, insertcolor=TEXT)
            s.map(w, fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
                  bordercolor=[("focus", ACCENT)])
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        s.configure("Accent.Horizontal.TProgressbar", background=ACCENT, troughcolor=FIELD,
                    bordercolor=FIELD, lightcolor=ACCENT, darkcolor=ACCENT, thickness=6)

    # ------------------------------------------------------------------- layout
    def _build(self):
        outer = ttk.Frame(self.root, padding=PAD)
        outer.grid(row=0, column=0)

        # header: title + connection pill
        head = ttk.Frame(outer)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text="L99 Screen", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(head, text="  picture & GIF uploader for the AULA L99",
                  style="Muted.TLabel").grid(row=0, column=1, sticky="w", pady=(4, 0))
        self.pill = tk.Canvas(head, height=28, width=210, bg=BG, highlightthickness=0,
                              cursor="hand2")
        self.pill.grid(row=0, column=2, sticky="e")
        self.pill.bind("<Button-1>", lambda e: self.refresh_ports())

        # left: mock screen
        sw, sh = encode.W + 2 * BEZEL_PAD, encode.H + 2 * BEZEL_PAD
        left = ttk.Frame(outer)
        left.grid(row=1, column=0, sticky="n", padx=(0, PAD))
        self.canvas = tk.Canvas(left, width=sw, height=sh, bg=BG, highlightthickness=0,
                                cursor="hand2")
        self.canvas.grid(row=0, column=0)
        self.canvas.bind("<Button-1>", lambda e: self.open_dialog())
        ttk.Label(left, text="Preview: exactly what the keyboard will show",
                  style="Faint.TLabel").grid(row=1, column=0, pady=(8, 0))
        self._draw_empty()

        # right: controls
        right = ttk.Frame(outer, width=330)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        # file card
        card = self._card(right, 0)
        top = ttk.Frame(card, style="Card.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        self.name_lbl = ttk.Label(top, text="No file chosen", style="Name.Card.TLabel",
                                  width=24)
        self.name_lbl.grid(row=0, column=0, sticky="w")
        ttk.Button(top, text="Browse…", style="Ghost.TButton",
                   command=self.open_dialog).grid(row=0, column=1, sticky="e")
        self.info = ttk.Label(card, text="JPG, PNG, GIF, WebP…", style="Muted.Card.TLabel")
        self.info.grid(row=1, column=0, sticky="w", pady=(4, 0))

        # options card
        card = self._card(right, 1)
        self._section(card, 0, "FIT")
        self.fit_seg = self._segmented(card, 1, self.fit, [("cover", "Fill"), ("contain", "Fit"),
                                                           ("stretch", "Stretch")])
        self._section(card, 2, "ROTATE")
        self._segmented(card, 3, self.rotate, [("0", "0°"), ("90", "90°"), ("180", "180°"),
                                               ("270", "270°")])
        self._section(card, 4, "SEND TO")
        self.target_seg = self._segmented(card, 5, self.target, [
            ("auto", "Automatic"), ("still", "Picture"), ("anim", "Animation")])
        self.target_hint = ttk.Label(card, text="", style="Muted.Card.TLabel")
        self.target_hint.grid(row=6, column=0, sticky="w", pady=(6, 0))

        # advanced card (collapsible)
        card = self._card(right, 2)
        self.adv_btn = ttk.Button(card, text="▸  Advanced", style="Link.TButton",
                                  command=self._toggle_advanced)
        self.adv_btn.grid(row=0, column=0, sticky="w")
        self.adv = ttk.Frame(card, style="Card.TFrame")
        self.adv.columnconfigure(1, weight=1)
        ttk.Label(self.adv, text="Frame delay (ms)", style="Muted.Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=(8, 4))
        sp = ttk.Spinbox(self.adv, from_=0, to=5000, increment=10, width=7,
                         textvariable=self.delay, command=self.rerender)
        sp.grid(row=0, column=1, sticky="e", pady=(8, 4))
        sp.bind("<Return>", lambda e: self.rerender())
        sp.bind("<FocusOut>", lambda e: self.rerender())
        ttk.Label(self.adv, text="0 keeps the GIF's own timing", style="Muted.Card.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(self.adv, text="Port", style="Muted.Card.TLabel").grid(
            row=2, column=0, sticky="w", pady=(10, 0))
        self.port_box = ttk.Combobox(self.adv, textvariable=self.port, width=16)
        self.port_box.grid(row=2, column=1, sticky="e", pady=(10, 0))

        # upload area
        up = ttk.Frame(right)
        up.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        up.columnconfigure(0, weight=1)
        self.upload_btn = ttk.Button(up, text="Upload to keyboard", style="Accent.TButton",
                                     command=self.upload, state="disabled")
        self.upload_btn.grid(row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(up, maximum=100, style="Accent.Horizontal.TProgressbar")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.progress.grid_remove()  # only shown while uploading
        srow = ttk.Frame(up)
        srow.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.status_dot = tk.Canvas(srow, width=10, height=10, bg=BG, highlightthickness=0)
        self.status_dot.grid(row=0, column=0, padx=(0, 8), pady=(4, 0), sticky="n")
        self.status_lbl = ttk.Label(srow, textvariable=self.status, style="Muted.TLabel",
                                    wraplength=300, justify="left")
        self.status_lbl.grid(row=0, column=1, sticky="w")
        self._set_status_color(FAINT)

        ttk.Label(outer, text=f"v{__version__}  ·  Ctrl+O open  ·  Ctrl+U upload",
                  style="Faint.TLabel").grid(row=2, column=0, columnspan=2, sticky="e",
                                             pady=(12, 0))

        self.root.bind("<Control-o>", lambda e: self.open_dialog())
        self.root.bind("<Control-u>", lambda e: self.upload())

        if TkinterDnD:
            for w in (self.canvas, self.root):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
            self.canvas.dnd_bind("<<DropEnter>>", lambda e: self._drop_hover(True) or e.action)
            self.canvas.dnd_bind("<<DropLeave>>", lambda e: self._drop_hover(False) or e.action)

    def _card(self, parent, row):
        f = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=BORDER)
        f.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        inner = ttk.Frame(f, style="Card.TFrame", padding=14)
        inner.pack(fill="both", expand=True)
        inner.columnconfigure(0, weight=1)
        return inner

    def _section(self, parent, row, text):
        ttk.Label(parent, text=text, style="Section.Card.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0 if row == 0 else 12, 6))

    def _segmented(self, parent, row, var, options):
        bar = tk.Frame(parent, bg=FIELD)
        bar.grid(row=row, column=0, sticky="ew")
        buttons = []
        for i, (val, txt) in enumerate(options):
            bar.columnconfigure(i, weight=1, uniform="seg")
            b = ttk.Radiobutton(bar, text=txt, value=val, variable=var, style="Seg.Toolbutton",
                                command=self.rerender, cursor="hand2")
            b.grid(row=0, column=i, sticky="ew", padx=2, pady=2)
            buttons.append(b)
        return buttons

    def _toggle_advanced(self):
        self._adv_open = not self._adv_open
        if self._adv_open:
            self.adv.grid(row=1, column=0, sticky="ew")
            self.adv_btn.config(text="▾  Advanced")
        else:
            self.adv.grid_remove()
            self.adv_btn.config(text="▸  Advanced")

    # ------------------------------------------------------------ screen canvas
    def _screen_frame(self, outline=BORDER):
        cv = self.canvas
        cv.delete("frame")
        w, h = int(cv["width"]), int(cv["height"])
        _rounded_rect(cv, 1, 1, w - 2, h - 2, 22, fill=BEZEL, outline=outline, width=2,
                      tags="frame")
        cv.tag_lower("frame")

    def _draw_empty(self, hover=False):
        cv = self.canvas
        cv.delete("all")
        self._img_item = None
        self._screen_frame(ACCENT if hover else BORDER)
        x0, y0 = BEZEL_PAD, BEZEL_PAD
        x1, y1 = x0 + encode.W, y0 + encode.H
        col = ACCENT if hover else "#3a3d4c"
        cv.create_rectangle(x0 + 18, y0 + 18, x1 - 18, y1 - 18, outline=col, dash=(6, 5), width=2)
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2 - 30
        # simple "picture" icon
        cv.create_rectangle(cx - 34, cy - 26, cx + 34, cy + 26, outline=col, width=3)
        cv.create_oval(cx + 6, cy - 16, cx + 20, cy - 2, outline=col, width=3)
        cv.create_line(cx - 30, cy + 22, cx - 8, cy - 2, cx + 6, cy + 12, cx + 14, cy + 4,
                       cx + 30, cy + 22, fill=col, width=3, joinstyle="round")
        cv.create_text(cx, cy + 62, text="Drop a picture or GIF" if TkinterDnD else
                       "Click to choose a picture or GIF", fill=TEXT, font=self.f_hint_big)
        cv.create_text(cx, cy + 88, text="or click to browse" if TkinterDnD else
                       "JPG · PNG · GIF · WebP", fill=MUTED, font=self.f_body)
        cv.create_text(cx, y1 - 44, text="320 × 480", fill=FAINT, font=self.f_small)

    def _drop_hover(self, on: bool):
        if self.frames:
            self._screen_frame(ACCENT if on else BORDER)
        else:
            self._draw_empty(hover=on)

    def _pill(self, text, color):
        cv = self.pill
        cv.delete("all")
        w = int(cv["width"])
        tw = tkfont.Font(font=self.f_small).measure(text)
        x0 = w - tw - 38
        _rounded_rect(cv, x0, 2, w - 2, 26, 12, fill=CARD, outline=BORDER)
        cv.create_oval(x0 + 12, 10, x0 + 20, 18, fill=color, outline="")
        cv.create_text(x0 + 28, 14, text=text, anchor="w", fill=TEXT, font=self.f_small)

    def _set_status_color(self, color):
        self.status_dot.delete("all")
        self.status_dot.create_oval(1, 1, 9, 9, fill=color, outline="")

    def _say(self, text, color=MUTED):
        self.status.set(text)
        self._set_status_color(color)

    # ------------------------------------------------------------------ actions
    def refresh_ports(self):
        try:
            from serial.tools import list_ports
            ports = [p.device for p in list_ports.comports()]
        except Exception:
            ports = []
        self.port_box["values"] = ports
        found = protocol.find_port()
        self._connected_port = found
        if found:
            self._pill(f"Connected · {os.path.basename(found)}", OK)
            if not self.port.get() or self.port.get() not in ports:
                self.port.set(found)
        else:
            self._pill("Keyboard not connected", ERR)
            if not self._busy and not self.frames:
                self._say("Connect the L99 with its USB cable (not the dongle or Bluetooth).",
                          WARN)

    def _watch_connection(self):
        if not self._busy:
            before = self._connected_port
            self.refresh_ports()
            if before is None and self._connected_port and not self.frames:
                self._say("Keyboard connected. Drop a picture or GIF to get started.", OK)
        self.root.after(2000, self._watch_connection)

    def _on_drop(self, event):
        self._drop_hover(False)
        files = self.root.tk.splitlist(event.data)
        if files:
            self.load(files[0])
        return event.action

    def open_dialog(self):
        if self._busy:
            return
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
        name = os.path.basename(path)
        self.name_lbl.config(text=name if len(name) <= 28 else name[:25] + "…")
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
        self._say("Preparing preview…")
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
        cv = self.canvas
        cv.delete("all")
        self._screen_frame()
        self._img_item = cv.create_image(BEZEL_PAD, BEZEL_PAD, anchor="nw",
                                         image=self._tk_frames[0])
        if self._anim_job:
            self.root.after_cancel(self._anim_job)
            self._anim_job = None
        if anim and len(frames) > 1:
            self.info.config(text=f"Animation  ·  {len(frames)} frames  ·  "
                                  f"{sum(delays) / 1000:.1f}s loop")
            self.target_hint.config(text="Goes to the animation slot. Your picture is kept.")
            self._animate(0)
        else:
            src = " (first frame of the GIF)" if self.animated else ""
            self.info.config(text=f"Picture  ·  320 × 480{src}")
            self.target_hint.config(text="Goes to the picture slot. Your animation is kept.")
        if not self._busy:
            self.upload_btn.config(state="normal")
            self.progress["value"] = 0
            self._say("Ready to upload.", OK if self._connected_port else WARN)

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
        self.upload_btn.config(state="disabled", text="Uploading…")
        self.progress["value"] = 0
        self.progress.grid()
        self._say("Encoding…", ACCENT)

        def work():
            try:
                if anim:
                    base, blob = protocol.GIF_ADDR, encode.encode_animation(frames, delays)
                else:
                    base, blob = protocol.STILL_ADDR, encode.encode_still(frames[0])
                with protocol.Screen(port) as scr:
                    self.events.put(("status", f"Uploading to the keyboard…"))
                    scr.upload(base, blob, lambda i, n: self.events.put(("progress", i * 100 / n)))
                self.events.put(("done", "Done! Your keyboard screen is updated."))
            except protocol.PortPermissionError as e:
                if linux_access.is_linux():
                    self.events.put(("need_access", e.port))
                else:
                    self.events.put(("failed", str(e)))
            except PermissionError as e:
                self.events.put(("failed", str(e)))
            except Exception as e:
                self.events.put(("failed", f"Upload failed: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def _finish(self):
        self._busy = False
        self.progress.grid_remove()
        self.upload_btn.config(text="Upload to keyboard",
                               state="normal" if self.frames else "disabled")

    def _setup_access(self, port: str):
        """Ask once, install the udev rule via pkexec, then retry the upload."""
        self._finish()
        if not messagebox.askyesno(
                "L99 Screen",
                "Linux needs a one-time permission before this app can use the keyboard's "
                "screen.\n\nSet it up now? Your system will ask for your password once; "
                "after that it works without asking."):
            self._say("Upload cancelled: permission not set up.", WARN)
            return
        self._busy = True
        self.upload_btn.config(state="disabled")
        self._say("Waiting for your password…", ACCENT)

        def work():
            ok, msg = linux_access.install_rule()
            if ok and not linux_access.wait_for_access(port):
                ok, msg = False, ("Permission was installed but the port is still locked. "
                                  "Unplug and replug the keyboard, then upload again.")
            self.events.put(("access_done", ok, msg))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------- event pump
    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "rendered" and ev[1] == self._render_token:
                    self._show(*ev[2:])
                elif kind == "progress":
                    self.progress["value"] = ev[1]
                    self.upload_btn.config(text=f"Uploading…  {int(ev[1])}%")
                elif kind == "status":
                    self._say(ev[1], ACCENT)
                elif kind == "need_access":
                    self._setup_access(ev[1])
                elif kind == "access_done":
                    self._finish()
                    if ev[1]:
                        self._say(ev[2], OK)
                        self.upload()
                    else:
                        self._say(ev[2], ERR)
                        messagebox.showerror("L99 Screen", ev[2])
                elif kind == "done":
                    self._finish()
                    self._say(ev[1], OK)
                elif kind in ("failed", "error"):
                    self._finish()
                    self.progress["value"] = 0
                    self._say(ev[1], ERR)
                    if kind == "failed":
                        messagebox.showerror("L99 Screen", ev[1])
        except queue.Empty:
            pass
        self.root.after(50, self._poll)


def main(argv=None) -> int:
    if os.name == "nt":  # sharp text on scaled Windows displays instead of bitmap-stretched
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    bundle = getattr(sys, "_MEIPASS", None)  # set inside the Windows .exe build
    if bundle and os.path.exists(os.path.join(bundle, "l99screen.ico")):
        try:
            root.iconbitmap(default=os.path.join(bundle, "l99screen.ico"))
        except tk.TclError:
            pass
    app = App(root)
    if argv:
        app.load(argv[0])
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
