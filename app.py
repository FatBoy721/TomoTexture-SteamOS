import os
import re
import shutil
import sys
import traceback
import platform
import webbrowser
import math
import json
import threading
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import zstandard as zstd
from PIL import Image, ImageTk

import swizzle
import ugctex

# ---------------------------------------------------------------------------
# Backend constants & config
# ---------------------------------------------------------------------------

KNOWN_CANVAS_TYPES = (
    'Food',
    'Goods',
    'FacePaint',
    'Cloth',
    'Exterior',
    'Interior',
    'MapObject',
    'MapFloor',
)
_KNOWN_CANVAS_GROUP = '|'.join(KNOWN_CANVAS_TYPES)
CANVAS_PATTERN = re.compile(
    rf'^(Ugc(?:{_KNOWN_CANVAS_GROUP})\d+|Ugc[A-Za-z0-9_]*\d+)\.canvas\.zs$'
)

GOODS_TYPES = {
    'Pet (256x256)':      (256, 256),
    'Treasure (256x256)': (256, 256),
    'Music (256x256)':    (256, 256),
    'Book (185x256)':     (185, 256),
    'Games (256x144)':    (256, 144),
}
CANVAS_SIZE_CANDIDATES = (
    (256, 256),
    (512, 512),
    (512, 256),
    (256, 512),
    (1024, 512),
    (512, 1024),
)
APP_VERSION = 'v1.0.2'
LATEST_RELEASE_API = 'https://api.github.com/repos/FatBoy721/TomoTexture-SteamOS/releases/latest'
RELEASES_URL = 'https://github.com/FatBoy721/TomoTexture-SteamOS/releases/latest'
PREVIEW_SIZE = 360
BACKUP_DIRNAME = '_ugc-tool-backups'

_IS_MAC = platform.system() == 'Darwin'
_IS_LINUX = platform.system() == 'Linux'

def _pick_existing(candidates: list[Path]) -> Path:
    for p in candidates:
        if p.is_dir():
            return p
    return candidates[0]


if _IS_MAC:
    DEFAULT_SAVE_ROOT = Path.home() / 'Library' / 'Application Support' / 'Ryujinx' / 'bis' / 'user' / 'save' / '0000000000000001'
elif _IS_LINUX:
    DEFAULT_SAVE_ROOT = _pick_existing([
        Path.home() / '.var' / 'app' / 'org.ryujinx.Ryujinx' / 'config' / 'Ryujinx' / 'bis' / 'user' / 'save' / '0000000000000004',
        Path.home() / '.config' / 'Ryujinx' / 'bis' / 'user' / 'save' / '0000000000000004',
    ])
else:
    DEFAULT_SAVE_ROOT = Path(os.path.expandvars(
        r'%APPDATA%\Ryujinx\bis\user\save\0000000000000004'))


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    return base / name


# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

BG = ("#f5f7fb", "#0b0b10")
SURF = ("#ffffff", "#14141f")
SURF2 = ("#eef1f7", "#1c1c2a")
SURF_SEL = ("#dbeafe", "#12324a")
BORDER = ("#d7dce8", "#26263a")
ACCENT = ("#2563eb", "#0ea5e9")
ACCENT_H = ("#1d4ed8", "#38bdf8")
SUCCESS = ("#059669", "#34d399")
ERROR = ("#dc2626", "#fb7185")
WARN = ("#d97706", "#f0c75e")
FG = ("#111827", "#dde0f5")
MUTED = ("#6b7280", "#6f7590")
MUTED2 = ("#4b5563", "#9aa3c7")
DANGER_H = ("#fee2e2", "#5a2020")


def theme_color(color):
    if isinstance(color, tuple):
        return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]
    return color

# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def load_image_rgba(path, target_w: int = 256, target_h: int = 256,
                    fit: str = 'stretch', _src_img=None) -> Image.Image:
    img = _src_img if _src_img is not None else Image.open(path)
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    if fit == 'stretch':
        img = img.resize((target_w, target_h), Image.LANCZOS)
    elif fit == 'crop':
        scale = max(target_w / img.width, target_h / img.height)
        new_w = int(img.width * scale)
        new_h = int(img.height * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        img = img.crop((left, top, left + target_w, top + target_h))
    else:  # letterbox
        canvas = Image.new('RGBA', (target_w, target_h), (0, 0, 0, 0))
        img.thumbnail((target_w, target_h), Image.LANCZOS)
        ox = (target_w - img.width) // 2
        oy = (target_h - img.height) // 2
        canvas.alpha_composite(img, dest=(ox, oy))
        img = canvas

    if (target_w <= swizzle.CANVAS_W and target_h <= swizzle.CANVAS_H
            and (img.width != swizzle.CANVAS_W or img.height != swizzle.CANVAS_H)):
        padded = Image.new('RGBA', (swizzle.CANVAS_W, swizzle.CANVAS_H), (0, 0, 0, 0))
        padded.paste(img, (0, 0))
        img = padded

    arr = np.array(img, dtype=np.uint8)
    mask = arr[..., 3] == 0
    if mask.any():
        arr[mask] = (0, 0, 0, 0)
    return Image.fromarray(arr, mode='RGBA')


def _infer_canvas_size(raw_size: int) -> tuple[int, int]:
    for size in CANVAS_SIZE_CANDIDATES:
        if size[0] * size[1] * swizzle.BPP == raw_size:
            return size
    if raw_size % swizzle.BPP:
        raise ValueError(f"Invalid RGBA canvas size: {raw_size} bytes")
    pixels = raw_size // swizzle.BPP
    raise ValueError(f"Unsupported canvas dimensions for {pixels} RGBA pixels")


def image_to_canvas_bytes(img: Image.Image) -> bytes:
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    linear = img.tobytes()
    if img.size == (swizzle.CANVAS_W, swizzle.CANVAS_H):
        swizzled = swizzle.swizzle(linear)
    else:
        swizzled = swizzle.nsw_swizzle(linear, img.size, (1, 1), swizzle.BPP, 4)
    return zstd.ZstdCompressor(level=19).compress(swizzled)


def canvas_file_to_image(path: Path) -> Image.Image:
    raw = zstd.ZstdDecompressor().decompress(path.read_bytes())
    size = _infer_canvas_size(len(raw))
    if size == (swizzle.CANVAS_W, swizzle.CANVAS_H):
        linear = swizzle.deswizzle(raw)
    else:
        linear = swizzle.nsw_deswizzle(raw, size, (1, 1), swizzle.BPP, 4)
    return Image.frombytes('RGBA', size, linear)


def make_checker_bg(size: int, sq: int = 8,
                    c1: tuple = (40, 42, 60, 255),
                    c2: tuple = (30, 32, 48, 255)) -> Image.Image:
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    yy, xx = np.indices((size, size))
    pattern = (xx // sq + yy // sq) % 2 == 0
    arr[pattern] = c1
    arr[~pattern] = c2
    return Image.fromarray(arr, mode='RGBA')


def composite_on_checker(img: Image.Image, size: int) -> Image.Image:
    scaled = img.copy()
    scaled.thumbnail((size, size), Image.LANCZOS)
    bg = make_checker_bg(size)
    result = bg.copy()
    ox = (size - scaled.size[0]) // 2
    oy = (size - scaled.size[1]) // 2
    result.alpha_composite(scaled, dest=(ox, oy))
    return result


# ---------------------------------------------------------------------------
# CanvasEntry & scanner
# ---------------------------------------------------------------------------


class CanvasEntry:
    def __init__(self, base_name: str, paths: dict[str, Path],
                 save_root: Path):
        self.base_name = base_name
        self.paths = paths
        self.save_root = save_root

    def primary_path(self) -> Path:
        return max(
            (p for p in self.paths.values() if p.exists()),
            key=lambda p: p.stat().st_mtime,
        )

    def backup_path(self, slot: str) -> Path:
        safe_slot = re.sub(r'[\\/]+', '_', slot).strip('_') or 'root'
        return self.save_root / BACKUP_DIRNAME / f'{safe_slot}__{self.base_name}.canvas.zs'

    def has_backup(self) -> bool:
        return any(self.backup_path(s).exists() for s in self.paths)

    def revert(self, slots: Optional[set[str]] = None) -> int:
        restored = 0
        for slot, dst in self.paths.items():
            if slots is not None and slot not in slots:
                continue
            bak = self.backup_path(slot)
            if not bak.exists():
                continue
            shutil.copy2(bak, dst)
            restored += 1
        return restored

    def write_bytes(self, compressed: bytes,
                    slots: Optional[set[str]] = None) -> int:
        n = 0
        for slot, dst in self.paths.items():
            if slots is not None and slot not in slots:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(compressed)
            n += 1
        return n

    def ensure_backup(self, slots: Optional[set[str]] = None):
        (self.save_root / BACKUP_DIRNAME).mkdir(exist_ok=True)
        for slot, src in self.paths.items():
            if slots is not None and slot not in slots:
                continue
            bak = self.backup_path(slot)
            if bak.exists():
                continue
            if not src.exists():
                continue
            shutil.copy2(src, bak)


def _slot_key(save_root: Path, canvas_file: Path) -> str:
    try:
        rel = canvas_file.parent.relative_to(save_root)
    except ValueError:
        return str(canvas_file.parent)
    s = rel.as_posix()
    if s not in ('', '.'):
        return s
    return '(root)'


def find_canvases(save_root: Path, max_depth: int = 8) -> tuple[list[CanvasEntry], list[str]]:
    entries = {}
    all_slots = set()

    root_depth = len(save_root.parts)
    for dirpath, dirnames, filenames in os.walk(save_root):
        p = Path(dirpath)

        dirnames[:] = [d for d in dirnames
                       if d != BACKUP_DIRNAME and not d.startswith('.')]

        if len(p.parts) - root_depth > max_depth:
            dirnames[:] = []
            continue

        for fn in filenames:
            m = CANVAS_PATTERN.match(fn)
            if not m:
                continue
            f = p / fn
            slot = _slot_key(save_root, f)
            all_slots.add(slot)
            entries.setdefault(m.group(1), {})[slot] = f

    result = [CanvasEntry(b, p, save_root)
              for b, p in sorted(entries.items())]
    return result, sorted(all_slots)


# ---------------------------------------------------------------------------
# CTk helpers
# ---------------------------------------------------------------------------

def _lbl(parent, text, size=12, weight="normal", color=FG, **kw) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, text_color=color,
                        font=ctk.CTkFont(size=size, weight=weight), **kw)


def _card(parent, **kw) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color=SURF, corner_radius=14,
                        border_width=1, border_color=BORDER, **kw)


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------


class ItemTypeDialog(tk.Toplevel):

    def __init__(self, master, base_name: str, preview_img: Optional[Image.Image] = None):
        super().__init__(master)
        self.result_size = None
        self._preview_photo = None
        self.title('Select Item Type')
        self.resizable(False, False)
        self.transient(master)
        self.configure(bg=theme_color(SURF))

        content = tk.Frame(self, bg=theme_color(SURF), padx=24, pady=18)
        content.pack(fill='both', expand=True)

        tk.Label(
            content, text=f'Configure {base_name}', bg=theme_color(SURF),
            fg=theme_color(FG), font=('Helvetica', 18, 'bold'),
        ).pack(anchor='w')
        tk.Label(
            content,
            text='What type of Goods/Pets item is this?\nThis sets the canvas resolution.',
            bg=theme_color(SURF), fg=theme_color(MUTED2),
            font=('Helvetica', 11), justify='left',
        ).pack(anchor='w', pady=(4, 0))

        if preview_img is not None:
            tk.Label(
                content, text='Current canvas:', bg=theme_color(SURF),
                fg=theme_color(MUTED2), font=('Helvetica', 10),
            ).pack(anchor='w', pady=(12, 4))
            preview_composite = composite_on_checker(preview_img, 180)
            self._preview_photo = ImageTk.PhotoImage(preview_composite)
            tk.Label(
                content, image=self._preview_photo, text='', bd=0,
                highlightthickness=0, bg=theme_color(SURF),
            ).pack(anchor='w')

        btn_frame = tk.Frame(content, bg=theme_color(SURF))
        btn_frame.pack(pady=(16, 10), fill='x')

        for label, size in GOODS_TYPES.items():
            tk.Button(
                btn_frame, text=label, command=lambda s=size: self._select(s),
                bg=theme_color(SURF2), fg=theme_color(FG),
                activebackground=theme_color(BORDER),
                activeforeground=theme_color(FG),
                relief='flat', bd=0, highlightthickness=1,
                highlightbackground=theme_color(BORDER),
                font=('Helvetica', 12), height=2,
            ).pack(fill='x', pady=3)

        tk.Button(
            content, text='Cancel', command=self._cancel,
            bg=theme_color(SURF2), fg=theme_color(MUTED2),
            activebackground=theme_color(BORDER),
            activeforeground=theme_color(FG),
            relief='flat', bd=0, highlightthickness=1,
            highlightbackground=theme_color(BORDER),
            font=('Helvetica', 11), padx=18, pady=6,
        ).pack(anchor='e')

        self.protocol('WM_DELETE_WINDOW', self._cancel)
        self.bind('<Escape>', lambda e: self._cancel())
        self.update_idletasks()
        self.minsize(320, self.winfo_reqheight())
        self.geometry(f'360x{self.winfo_reqheight()}')
        self.after(50, self._show_modal)

    def _show_modal(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        px, py = self.master.winfo_rootx(), self.master.winfo_rooty()
        pw, ph = self.master.winfo_width(), self.master.winfo_height()
        self.geometry(f'+{max(px + (pw - w) // 2, 0)}+{max(py + (ph - h) // 3, 0)}')
        self.lift()
        self.focus_force()
        self.grab_set()

    def _select(self, size):
        self.result_size = size
        self.destroy()

    def _cancel(self):
        self.result_size = None
        self.destroy()


class ImageFitDialog(tk.Toplevel):

    def __init__(self, master, img: Image.Image, target_size: tuple[int, int]):
        super().__init__(master)
        self.result_img = None
        w, h = target_size
        self.title('Resize Required')
        self.resizable(False, False)
        self.transient(master)
        self.configure(bg=theme_color(SURF))

        content = tk.Frame(self, bg=theme_color(SURF), padx=24, pady=18)
        content.pack(fill='both', expand=True)

        tk.Label(
            content, text='Resize Required', bg=theme_color(SURF),
            fg=theme_color(FG), font=('Helvetica', 18, 'bold'),
        ).pack(anchor='w')
        tk.Label(
            content,
            text=f'Your image is {img.width}x{img.height}. Target is {w}x{h}.\nChoose how to fit:',
            bg=theme_color(SURF), fg=theme_color(MUTED2),
            font=('Helvetica', 11), justify='left',
        ).pack(anchor='w', pady=(4, 10))

        options = [
            ('Crop (Fill)', 'crop', 'Scales up and crops to fill.'),
            ('Fit (Letterbox)', 'letterbox', 'Scales to fit with transparent padding.'),
            ('Stretch', 'stretch', 'Stretches to exact target size.'),
        ]

        self._fit = tk.StringVar(self, value='crop')
        for label, val, desc in options:
            row = tk.Frame(
                content, bg=theme_color(SURF2),
                highlightthickness=1, highlightbackground=theme_color(BORDER),
                padx=10, pady=8,
            )
            row.pack(fill='x', pady=3)
            tk.Radiobutton(
                row, text=label, variable=self._fit, value=val,
                bg=theme_color(SURF2), fg=theme_color(FG),
                selectcolor=theme_color(BG),
                activebackground=theme_color(SURF2),
                activeforeground=theme_color(FG),
                font=('Helvetica', 12, 'bold'),
                highlightthickness=0, bd=0,
            ).pack(side='left')
            tk.Label(
                row, text=desc, bg=theme_color(SURF2),
                fg=theme_color(MUTED2), font=('Helvetica', 10),
            ).pack(side='left', padx=(8, 0))

        tip = tk.Frame(content, bg=theme_color(SURF))
        tip.pack(fill='x', pady=(10, 0))
        tk.Label(
            tip, text='Tip: Use transparent PNGs for best results.',
            bg=theme_color(SURF), fg=theme_color(MUTED2),
            font=('Helvetica', 10),
        ).pack(side='left')
        link = tk.Label(
            tip, text='remove.bg', bg=theme_color(SURF),
            fg=theme_color(ACCENT), font=('Helvetica', 10, 'bold'),
            cursor='hand2',
        )
        link.pack(side='left', padx=(6, 0))
        link.bind('<Button-1>', lambda e: webbrowser.open('https://www.remove.bg'))

        btns = tk.Frame(content, bg=theme_color(SURF))
        btns.pack(pady=(16, 0), fill='x')
        tk.Button(
            btns, text='Cancel', command=self._cancel,
            bg=theme_color(SURF2), fg=theme_color(MUTED2),
            activebackground=theme_color(BORDER),
            activeforeground=theme_color(FG),
            relief='flat', bd=0, highlightthickness=1,
            highlightbackground=theme_color(BORDER),
            font=('Helvetica', 11), padx=18, pady=6,
        ).pack(side='right', padx=(8, 0))
        tk.Button(
            btns, text='Apply', command=lambda: self._apply(img, target_size),
            bg=theme_color(ACCENT), fg='white',
            activebackground=theme_color(ACCENT_H),
            activeforeground='white',
            relief='flat', bd=0, highlightthickness=0,
            font=('Helvetica', 11, 'bold'), padx=18, pady=6,
        ).pack(side='right')

        self.protocol('WM_DELETE_WINDOW', self._cancel)
        self.bind('<Escape>', lambda e: self._cancel())
        self.bind('<Return>', lambda e: self._apply(img, target_size))
        self.update_idletasks()
        self.minsize(420, self.winfo_reqheight())
        self.geometry(f'520x{self.winfo_reqheight()}')
        self.after(50, self._show_modal)

    def _show_modal(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        px, py = self.master.winfo_rootx(), self.master.winfo_rooty()
        pw, ph = self.master.winfo_width(), self.master.winfo_height()
        self.geometry(f'+{max(px + (pw - w) // 2, 0)}+{max(py + (ph - h) // 3, 0)}')
        self.lift()
        self.focus_force()
        self.grab_set()

    def _apply(self, img, target_size):
        self.result_img = load_image_rgba(
            None, target_size[0], target_size[1], self._fit.get(), _src_img=img)
        self.destroy()

    def _cancel(self):
        self.result_img = None
        self.destroy()


class ConfirmReplaceDialog(tk.Toplevel):

    def __init__(self, master, entry: CanvasEntry, new_image: Image.Image, target_slots: set[str]):
        super().__init__(master)
        self.result = False
        self.title(f'Confirm Replace — {entry.base_name}')
        self.resizable(False, False)
        self.transient(master)
        self.configure(bg=theme_color(SURF))

        content = tk.Frame(self, bg=theme_color(SURF), padx=24, pady=18)
        content.pack(fill='both', expand=True)

        tk.Label(
            content, text=f'Replace {entry.base_name}?',
            bg=theme_color(SURF), fg=theme_color(FG),
            font=('Helvetica', 18, 'bold'),
        ).pack(anchor='w')

        slots_str = ', '.join(sorted(target_slots)) or '—'
        tk.Label(
            content,
            text=f'Slot(s): {slots_str}\nA backup is saved automatically on first replace.',
            bg=theme_color(SURF), fg=theme_color(MUTED2),
            font=('Helvetica', 11), justify='left',
        ).pack(anchor='w', pady=(4, 14))

        body = tk.Frame(content, bg=theme_color(SURF))
        body.pack()

        cur_img = canvas_file_to_image(entry.primary_path())
        cur_composite = composite_on_checker(cur_img, PREVIEW_SIZE)
        new_composite = composite_on_checker(new_image, PREVIEW_SIZE)

        self._cur_photo = ImageTk.PhotoImage(cur_composite)
        self._new_photo = ImageTk.PhotoImage(new_composite)

        col_cur = tk.Frame(body, bg=theme_color(SURF))
        col_cur.grid(row=0, column=0, padx=(0, 8))
        tk.Label(
            col_cur, text='CURRENT', bg=theme_color(SURF),
            fg=theme_color(MUTED2), font=('Helvetica', 9, 'bold'),
        ).pack(anchor='w', pady=(0, 4))
        tk.Label(
            col_cur, image=self._cur_photo, text='', bd=0,
            highlightthickness=0, bg=theme_color(SURF),
        ).pack()

        tk.Label(
            body, text='>', bg=theme_color(SURF),
            fg=theme_color(ACCENT), font=('Helvetica', 24, 'bold'),
        ).grid(row=0, column=1, padx=10)

        col_new = tk.Frame(body, bg=theme_color(SURF))
        col_new.grid(row=0, column=2, padx=(8, 0))
        tk.Label(
            col_new, text='NEW', bg=theme_color(SURF),
            fg=theme_color(SUCCESS), font=('Helvetica', 9, 'bold'),
        ).pack(anchor='w', pady=(0, 4))
        tk.Label(
            col_new, image=self._new_photo, text='', bd=0,
            highlightthickness=0, bg=theme_color(SURF),
        ).pack()

        btns = tk.Frame(content, bg=theme_color(SURF))
        btns.pack(pady=(16, 0), fill='x')
        tk.Button(
            btns, text='Cancel', command=self._cancel,
            bg=theme_color(SURF2), fg=theme_color(MUTED2),
            activebackground=theme_color(BORDER),
            activeforeground=theme_color(FG),
            relief='flat', bd=0, highlightthickness=1,
            highlightbackground=theme_color(BORDER),
            font=('Helvetica', 11), padx=18, pady=6,
        ).pack(side='right', padx=(8, 0))
        tk.Button(
            btns, text='Replace', command=self._confirm,
            bg=theme_color(ACCENT), fg='white',
            activebackground=theme_color(ACCENT_H),
            activeforeground='white',
            relief='flat', bd=0, highlightthickness=0,
            font=('Helvetica', 11, 'bold'), padx=18, pady=6,
        ).pack(side='right')

        self.protocol('WM_DELETE_WINDOW', self._cancel)
        self.bind('<Escape>', lambda e: self._cancel())
        self.bind('<Return>', lambda e: self._confirm())
        self.update_idletasks()
        self.minsize(760, self.winfo_reqheight())
        self.geometry(f'820x{self.winfo_reqheight()}')
        self.after(50, self._show_modal)

    def _show_modal(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        px, py = self.master.winfo_rootx(), self.master.winfo_rooty()
        pw, ph = self.master.winfo_width(), self.master.winfo_height()
        self.geometry(f'+{max(px + (pw - w) // 2, 0)}+{max(py + (ph - h) // 3, 0)}')
        self.lift()
        self.focus_force()
        self.grab_set()

    def _confirm(self):
        self.result = True
        self.destroy()

    def _cancel(self):
        self.result = False
        self.destroy()


class PreviewDialog(ctk.CTkToplevel):

    def __init__(self, master, entry: CanvasEntry, img: Image.Image):
        super().__init__(master)
        self.title(f'{entry.base_name} — Preview')
        self.resizable(False, False)
        self.transient(master)

        _lbl(self, entry.base_name, size=16, weight="bold").pack(
            padx=20, pady=(16, 2), anchor='w')
        _lbl(self, '256x256  RGBA  Swizzled', size=10, color=MUTED2).pack(
            padx=20, anchor='w')

        composite = composite_on_checker(img, 480)
        self._photo = ctk.CTkImage(light_image=composite, dark_image=composite,
                                   size=(480, 480))
        ctk.CTkLabel(self, image=self._photo, text='').pack(padx=20, pady=16)
        self.bind('<Escape>', lambda e: self.destroy())


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------


class App(ctk.CTk):

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title('TomoTexture')
        self.geometry('1100x750')
        self.minsize(900, 600)

        self._entries: list[CanvasEntry] = []
        self._all_slots: list[str] = []
        self._slot_vars: dict[str, tk.BooleanVar] = {}
        self._selected: Optional[CanvasEntry] = None
        self._theme_animating = False
        self._item_rows: dict[str, ctk.CTkFrame] = {}
        self._empty_widgets: list = []
        self._img_refs: list = []
        self._detail_photo = None

        initial_root = ''
        if DEFAULT_SAVE_ROOT.is_dir():
            initial_root = str(DEFAULT_SAVE_ROOT)

        self._save_root_var = tk.StringVar(value=initial_root)
        self._status_var = tk.StringVar(value='Select a save folder to begin.')

        self._build()

        if initial_root:
            self.after(50, self._refresh)

    def _selected_slots(self) -> set[str]:
        return {s for s, v in self._slot_vars.items() if v.get()}

    # ── build UI ──────────────────────────────────────────────────────────

    def _build(self):
        self._build_header()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=(10, 0))

        self._build_folder_row(body)
        self._build_content(body)
        self._build_status(body)

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=SURF, corner_radius=0, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkFrame(hdr, fg_color=ACCENT, corner_radius=0, width=4).pack(
            side="left", fill="y")
        _lbl(hdr, "TomoTexture", size=16, weight="bold").pack(
            side="left", padx=16)
        _lbl(hdr, "Canvas Texture Manager", size=11, color=MUTED).pack(
            side="left", padx=(0, 16))

        self._mode_switch = ctk.CTkSwitch(
            hdr, text="Dark Mode", font=ctk.CTkFont(size=11),
            command=self._toggle_theme, onvalue=1, offvalue=0,
            button_color=ACCENT, button_hover_color=ACCENT_H,
        )
        self._mode_switch.pack(side="right", padx=18)

        self._update_btn = ctk.CTkButton(
            hdr, text="Check Updates", width=112, height=28,
            command=self._on_check_updates,
            fg_color=SURF2, hover_color=BORDER, text_color=MUTED2,
            font=ctk.CTkFont(size=11),
        )
        self._update_btn.pack(side="right", padx=(0, 10))

    def _toggle_theme(self):
        if self._theme_animating:
            return
        target_mode = "light" if self._mode_switch.get() else "dark"
        target_label = "Light Mode" if target_mode == "light" else "Dark Mode"
        self._fade_theme(target_mode, target_label)

    def _fade_theme(self, target_mode: str, target_label: str):
        self._theme_animating = True
        self._mode_switch.configure(state="disabled")
        fade_out_values = self._ease_values(1.0, 0.58, 12)
        fade_in_values = self._ease_values(0.58, 1.0, 14)

        def fade_out(i=0):
            if i < len(fade_out_values):
                try:
                    self.attributes("-alpha", fade_out_values[i])
                    self.update_idletasks()
                except tk.TclError:
                    ctk.set_appearance_mode(target_mode)
                    self._mode_switch.configure(text=target_label)
                    self._finish_theme_animation()
                    return
                self.after(14, lambda: fade_out(i + 1))
                return
            ctk.set_appearance_mode(target_mode)
            self._mode_switch.configure(text=target_label)
            self.update_idletasks()
            fade_in(0)

        def fade_in(i=0):
            if i < len(fade_in_values):
                try:
                    self.attributes("-alpha", fade_in_values[i])
                    self.update_idletasks()
                except tk.TclError:
                    self._finish_theme_animation()
                    return
                self.after(14, lambda: fade_in(i + 1))
                return
            self._finish_theme_animation()

        fade_out()

    @staticmethod
    def _ease_values(start: float, end: float, steps: int) -> list[float]:
        values = []
        for i in range(steps):
            t = i / max(steps - 1, 1)
            eased = (1 - math.cos(t * math.pi)) / 2
            values.append(start + (end - start) * eased)
        return values

    def _finish_theme_animation(self):
        try:
            self.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        self._mode_switch.configure(state="normal")
        self._theme_animating = False
        self._sync_preview_bg()

    def _on_check_updates(self):
        self._update_btn.configure(state="disabled", text="Checking...")
        self._set_status("Checking for updates...", ACCENT)
        threading.Thread(target=self._check_updates_worker, daemon=True).start()

    def _check_updates_worker(self):
        try:
            req = urllib.request.Request(
                LATEST_RELEASE_API,
                headers={
                    'Accept': 'application/vnd.github+json',
                    'User-Agent': f'TomoTexture/{APP_VERSION}',
                },
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
            latest = data.get('tag_name', '').strip()
            release_url = data.get('html_url') or RELEASES_URL
            self.after(0, lambda: self._handle_update_result(latest, release_url))
        except Exception as exc:
            error = str(exc)
            self.after(0, lambda: self._handle_update_error(error))

    def _handle_update_result(self, latest: str, release_url: str):
        self._update_btn.configure(state="normal", text="Check Updates")
        if not latest:
            self._set_status("Could not read latest release version.", WARN)
            messagebox.showwarning(
                'Update check failed',
                'GitHub did not return a latest release version.',
            )
            return

        if self._version_tuple(latest) > self._version_tuple(APP_VERSION):
            self._set_status(f"Update available: {latest}", SUCCESS)
            if messagebox.askyesno(
                'Update available',
                f'TomoTexture {latest} is available.\n\nOpen the download page?',
            ):
                webbrowser.open(release_url)
            return

        self._set_status(f"TomoTexture is up to date ({APP_VERSION}).", SUCCESS)
        messagebox.showinfo('No update available', f'You are on {APP_VERSION}.')

    def _handle_update_error(self, error: str):
        self._update_btn.configure(state="normal", text="Check Updates")
        self._set_status("Update check failed.", ERROR)
        messagebox.showerror(
            'Update check failed',
            f'Could not check GitHub releases.\n\n{error}',
        )

    @staticmethod
    def _version_tuple(version: str) -> tuple[int, ...]:
        parts = re.findall(r'\d+', version)
        return tuple(int(part) for part in parts) if parts else (0,)

    def _build_folder_row(self, parent):
        card = _card(parent)
        card.pack(fill="x", pady=(0, 10))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        _lbl(row, "Save Folder", size=11, color=MUTED2, width=90, anchor="w").pack(side="left")

        self._folder_entry = ctk.CTkEntry(
            row, textvariable=self._save_root_var,
            placeholder_text="Path to Ryujinx save folder...",
            font=ctk.CTkFont(size=11), fg_color=SURF2,
            border_color=BORDER, text_color=FG,
        )
        self._folder_entry.pack(side="left", fill="x", expand=True)
        self._folder_entry.bind('<Return>', lambda e: self._refresh())

        ctk.CTkButton(
            row, text="Browse", width=72, height=30,
            fg_color=ACCENT, hover_color=ACCENT_H,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._browse_folder,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            row, text="Refresh", width=72, height=30,
            fg_color=SURF2, hover_color=BORDER, text_color=MUTED2,
            font=ctk.CTkFont(size=11),
            command=self._refresh,
        ).pack(side="left", padx=(6, 0))

        self._slot_frame = ctk.CTkFrame(inner, fg_color="transparent")
        self._slot_frame.pack(fill="x", pady=(8, 0))
        self._slot_label = _lbl(self._slot_frame, "Slots:", size=10, color=MUTED2)
        self._slot_label.pack(side="left")
        self._slot_widgets: list[ctk.CTkCheckBox] = []

    def _build_content(self, parent):
        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, pady=(0, 8))
        content.columnconfigure(0, minsize=260)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)

        self._build_item_list(content)
        self._build_detail_panel(content)

    def _build_item_list(self, parent):
        card = _card(parent)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 6))
        _lbl(header, "Canvases", size=13, weight="bold").pack(side="left")
        self._count_lbl = _lbl(header, "", size=10, color=MUTED2)
        self._count_lbl.pack(side="right")

        self._item_scroll = ctk.CTkScrollableFrame(
            card, fg_color="transparent",
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=MUTED,
        )
        self._item_scroll.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self._empty_lbl = _lbl(
            self._item_scroll,
            "No canvases found.\nSelect a save folder above.",
            size=11, color=MUTED, justify="center",
        )
        self._empty_lbl.pack(pady=40)
        self._empty_widgets.append(self._empty_lbl)

    def _build_detail_panel(self, parent):
        card = _card(parent)
        card.grid(row=0, column=1, sticky="nsew")

        self._detail_inner = ctk.CTkFrame(card, fg_color="transparent")
        self._detail_inner.pack(fill="both", expand=True, padx=20, pady=20)

        self._preview_lbl = tk.Label(
            self._detail_inner, text="", bd=0, highlightthickness=0,
            width=PREVIEW_SIZE, height=PREVIEW_SIZE,
        )
        self._preview_lbl.pack(pady=(0, 12))
        self._sync_preview_bg()

        self._name_lbl = _lbl(self._detail_inner, "Select a texture from the list",
                              size=14, weight="bold", color=MUTED)
        self._name_lbl.pack(anchor="w")

        guidance = ctk.CTkFrame(self._detail_inner, fg_color="transparent")
        guidance.pack(fill="x", pady=(8, 0))
        self._guidance_lbl = _lbl(
            guidance,
            "Use images with transparent backgrounds for best results.",
            size=11, color=MUTED2,
        )
        self._guidance_lbl.pack(side="left")
        self._guidance_link = ctk.CTkLabel(
            guidance, text="remove.bg", text_color=ACCENT,
            font=ctk.CTkFont(size=11, weight="bold"), cursor="hand2",
        )
        self._guidance_link.pack(side="left", padx=(6, 0))
        self._guidance_link.bind(
            "<Button-1>", lambda e: webbrowser.open("https://www.remove.bg"))

        self._info_lbl = _lbl(self._detail_inner, "", size=10, color=MUTED2)
        self._info_lbl.pack(anchor="w", pady=(8, 0))

        self._backup_lbl = _lbl(self._detail_inner, "", size=10, color=MUTED2)
        self._backup_lbl.pack(anchor="w", pady=(2, 0))

        btn_row = ctk.CTkFrame(self._detail_inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(16, 0))

        self._btn_replace = ctk.CTkButton(
            btn_row, text="Replace texture", command=self._on_replace,
            fg_color=ACCENT, hover_color=ACCENT_H,
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38, state="disabled",
        )
        self._btn_replace.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self._btn_export = ctk.CTkButton(
            btn_row, text="Export", command=self._on_export,
            fg_color=SURF2, hover_color=BORDER, text_color=MUTED2,
            font=ctk.CTkFont(size=13), height=38, state="disabled",
        )
        self._btn_export.pack(side="left", fill="x", expand=True, padx=4)

        self._btn_revert = ctk.CTkButton(
            btn_row, text="Revert", command=self._on_revert,
            fg_color=SURF2, hover_color=DANGER_H, text_color=ERROR,
            font=ctk.CTkFont(size=13), height=38, state="disabled",
        )
        self._btn_revert.pack(side="left", fill="x", expand=True, padx=(4, 0))

        self._btn_clear = ctk.CTkButton(
            self._detail_inner, text="Clear selection", command=self._clear_selection,
            fg_color="transparent", hover_color=SURF2, text_color=MUTED2,
            border_width=1, border_color=BORDER,
            font=ctk.CTkFont(size=11), height=30, state="disabled",
        )
        self._btn_clear.pack(anchor="w", pady=(14, 0))

    def _build_status(self, parent):
        bar = ctk.CTkFrame(parent, fg_color="transparent", height=28)
        bar.pack(fill="x", pady=(0, 6))
        self._status_dot = ctk.CTkLabel(bar, text="●", text_color=ACCENT,
                                        font=ctk.CTkFont(size=8), width=16)
        self._status_dot.pack(side="left")
        ctk.CTkLabel(bar, textvariable=self._status_var, text_color=MUTED2,
                     font=ctk.CTkFont(size=11), anchor="w").pack(side="left", fill="x", expand=True)
        _lbl(bar, "TomoTexture", size=9, color=MUTED).pack(side="right")

    # ── folder / refresh ──────────────────────────────────────────────────

    def _browse_folder(self):
        initial = self._save_root_var.get() or os.path.expanduser('~')
        chosen = filedialog.askdirectory(
            title='Select save folder', initialdir=initial)
        if chosen:
            self._save_root_var.set(chosen)
            self._refresh()

    def _refresh(self):
        for row in self._item_rows.values():
            try:
                row.destroy()
            except Exception:
                pass
        self._item_rows.clear()
        for w in self._empty_widgets:
            try:
                w.destroy()
            except Exception:
                pass
        self._empty_widgets.clear()
        self._selected = None
        self._clear_detail()
        self._img_refs.clear()

        raw = self._save_root_var.get().strip()
        if not raw:
            self._show_empty("No save folder selected", "Click Browse to get started.")
            self._set_status("Select a save folder to begin.", MUTED)
            self._rebuild_slots([])
            return

        root = Path(raw)
        if not root.is_dir():
            self._show_empty("Folder not found", str(root))
            self._set_status("Save folder not found.", ERROR)
            self._rebuild_slots([])
            return

        entries, all_slots = find_canvases(root)
        self._entries = entries
        self._all_slots = all_slots

        if not entries:
            self._show_empty("No editable textures found", f"No *.canvas.zs under\n{root}")
            self._set_status("No editable textures found in that save folder.", WARN)
            self._rebuild_slots(all_slots)
            return

        self._rebuild_slots(all_slots)
        self._count_lbl.configure(text=str(len(entries)))

        for entry in entries:
            self._add_item_row(entry)

        self._set_status(
            f"Found {len(entries)} editable texture(s). Select one, then click Replace texture.",
            SUCCESS)

    def _show_empty(self, title, sub):
        self._count_lbl.configure(text="0")
        lbl = _lbl(self._item_scroll, f"{title}\n{sub}",
                    size=11, color=MUTED, justify="center")
        lbl.pack(pady=40)
        self._empty_widgets.append(lbl)

    def _add_item_row(self, entry: CanvasEntry):
        try:
            img = canvas_file_to_image(entry.primary_path())
            thumb = composite_on_checker(img, 48)
            ctk_img = ctk.CTkImage(light_image=thumb, dark_image=thumb, size=(48, 48))
            self._img_refs.append(ctk_img)
        except Exception:
            ctk_img = None

        slots_str = ', '.join(sorted(entry.paths.keys()))
        backup_str = " · Backup" if entry.has_backup() else ""
        text = f"  {entry.base_name}\n  {slots_str}{backup_str}"

        btn = ctk.CTkButton(
            self._item_scroll,
            image=ctk_img,
            text=text,
            compound="left",
            anchor="w",
            fg_color=SURF2,
            hover_color=SURF_SEL,
            text_color=FG,
            corner_radius=8,
            height=64,
            font=ctk.CTkFont(size=11),
            command=lambda ent=entry: self._on_item_selected(ent),
        )
        btn.pack(fill="x", pady=(0, 4), padx=2)

        self._item_rows[entry.base_name] = btn

    @staticmethod
    def _all_widgets(root) -> list:
        result = [root]
        for child in root.winfo_children():
            result.extend(App._all_widgets(child))
        return result

    # ── item selection ────────────────────────────────────────────────────

    def _on_item_selected(self, entry: CanvasEntry, row=None):
        for r in self._item_rows.values():
            try:
                r.configure(fg_color=SURF2, hover_color=SURF_SEL)
            except Exception:
                pass
        target = row if row else self._item_rows.get(entry.base_name)
        if target is not None:
            try:
                target.configure(fg_color=SURF_SEL, hover_color=SURF_SEL)
            except Exception:
                pass

        self._selected = entry
        self._show_detail(entry)

    def _sync_preview_bg(self):
        try:
            parent = self._preview_lbl.master
            bg = parent.cget("fg_color")
            if isinstance(bg, (tuple, list)):
                bg = bg[0] if ctk.get_appearance_mode() == "Light" else bg[1]
            if bg in (None, "transparent"):
                bg = theme_color(SURF)
            self._preview_lbl.configure(bg=bg, fg=theme_color(MUTED))
        except Exception:
            pass

    def _show_detail(self, entry: CanvasEntry):
        try:
            img = canvas_file_to_image(entry.primary_path())
            composite = composite_on_checker(img, PREVIEW_SIZE)
            self._detail_photo = ImageTk.PhotoImage(composite)
            self._preview_lbl.configure(image=self._detail_photo, text="", width=PREVIEW_SIZE, height=PREVIEW_SIZE)
        except Exception as e:
            self._detail_photo = None
            self._preview_lbl.configure(image="", text=f"[error]\n{e}")

        self._name_lbl.configure(text=entry.base_name, text_color=FG)

        slots_str = ', '.join(sorted(entry.paths.keys()))
        self._info_lbl.configure(text=f"Slots: {slots_str}")

        if entry.has_backup():
            self._backup_lbl.configure(text="Backup available", text_color=SUCCESS)
        else:
            self._backup_lbl.configure(text="No backup yet", text_color=MUTED2)

        self._btn_replace.configure(state="normal")
        self._btn_export.configure(state="normal")
        self._btn_revert.configure(state="normal" if entry.has_backup() else "disabled")
        self._btn_clear.configure(state="normal")

        self._set_status(f"Selected: {entry.base_name}. Click Replace texture to choose an image.", ACCENT)

    def _clear_selection(self):
        self._selected = None
        for r in self._item_rows.values():
            try:
                r.configure(fg_color=SURF2, hover_color=SURF_SEL)
            except Exception:
                pass
        self._clear_detail()
        self._set_status("Selection cleared. Pick a texture from the list.", MUTED)

    def _clear_detail(self):
        self._detail_photo = None
        self._preview_lbl.configure(image="", text="")
        self._name_lbl.configure(text="Select a texture from the list", text_color=MUTED)
        self._info_lbl.configure(text="PNG, JPG, WebP, GIF, BMP, and TIFF are accepted.")
        self._backup_lbl.configure(text="")
        self._btn_replace.configure(state="disabled")
        self._btn_export.configure(state="disabled")
        self._btn_revert.configure(state="disabled")
        self._btn_clear.configure(state="disabled")

    # ── slots ─────────────────────────────────────────────────────────────

    def _rebuild_slots(self, slots: list[str]):
        for w in self._slot_widgets:
            w.destroy()
        self._slot_widgets.clear()
        self._slot_vars.clear()

        if not slots:
            return

        for slot in slots:
            var = tk.BooleanVar(value=True)
            self._slot_vars[slot] = var
            cb = ctk.CTkCheckBox(
                self._slot_frame, text=slot, variable=var,
                font=ctk.CTkFont(size=10),
                checkbox_width=16, checkbox_height=16, corner_radius=4,
                fg_color=ACCENT, hover_color=ACCENT_H,
            )
            cb.pack(side="left", padx=(10, 0))
            self._slot_widgets.append(cb)

    # ── actions ───────────────────────────────────────────────────────────

    def _on_replace(self):
        entry = self._selected
        if not entry:
            return

        try:
            current_img = canvas_file_to_image(entry.primary_path())
            target_w, target_h = current_img.size
        except Exception:
            current_img = None
            target_w, target_h = 256, 256
        if entry.base_name.startswith('UgcGoods'):
            type_dlg = ItemTypeDialog(self, entry.base_name, current_img)
            self.wait_window(type_dlg)
            if type_dlg.result_size is None:
                self._set_status("Replace cancelled.", MUTED)
                return
            target_w, target_h = type_dlg.result_size

        src = filedialog.askopenfilename(
            title=f'Select image for {entry.base_name}',
            filetypes=[
                ('Image files', '*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tiff *.tif'),
                ('PNG files', '*.png'),
                ('All files', '*.*'),
            ],
        )
        if not src:
            return

        try:
            src_img = Image.open(Path(src))
            if src_img.mode != 'RGBA':
                src_img = src_img.convert('RGBA')
            if src_img.width != target_w or src_img.height != target_h:
                fit_dlg = ImageFitDialog(self, src_img, (target_w, target_h))
                self.wait_window(fit_dlg)
                if fit_dlg.result_img is None:
                    self._set_status("Replace cancelled (resize aborted).", MUTED)
                    return
                new_img = fit_dlg.result_img
            else:
                new_img = load_image_rgba(None, target_w, target_h, 'stretch', _src_img=src_img)
        except Exception:
            messagebox.showerror('Failed to open image', traceback.format_exc())
            return

        target_slots = self._selected_slots() & set(entry.paths.keys())
        if not target_slots:
            messagebox.showwarning('No slots selected',
                                   'Enable at least one slot above.')
            return

        dlg = ConfirmReplaceDialog(self, entry, new_img, target_slots)
        self.wait_window(dlg)
        if not dlg.result:
            self._set_status("Replace cancelled.", MUTED)
            return

        try:
            entry.ensure_backup(target_slots)
            compressed = image_to_canvas_bytes(new_img)
            n = entry.write_bytes(compressed, target_slots)

            companion_count = 0
            for slot, canvas_path in entry.paths.items():
                if slot not in target_slots:
                    continue
                try:
                    ugctex.write_companion_files(new_img, canvas_path)
                    companion_count += 1
                except Exception:
                    pass
        except Exception:
            messagebox.showerror('Replace failed', traceback.format_exc())
            return

        self._show_detail(entry)
        self._refresh_row_thumb(entry)
        slots_str = '+'.join(sorted(target_slots))
        extra = f' + ugctex/thumb' if companion_count else ''
        self._set_status(
            f"Replaced {entry.base_name} in {n} slot(s) [{slots_str}]{extra}.",
            SUCCESS)

    def _on_export(self):
        entry = self._selected
        if not entry:
            return
        dest = filedialog.asksaveasfilename(
            title=f'Export {entry.base_name} as PNG',
            defaultextension='.png',
            initialfile=f'{entry.base_name}.png',
            filetypes=[('PNG', '*.png'), ('All files', '*.*')],
        )
        if not dest:
            return
        try:
            img = canvas_file_to_image(entry.primary_path())
            img.save(dest)
        except Exception:
            messagebox.showerror('Export failed', traceback.format_exc())
            return
        self._set_status(f"Exported {entry.base_name} → {dest}", SUCCESS)

    def _on_revert(self):
        entry = self._selected
        if not entry:
            return
        if not entry.has_backup():
            messagebox.showinfo('No backup',
                                f'No backup for {entry.base_name}.')
            return

        target_slots = self._selected_slots() & set(entry.paths.keys())
        if not target_slots:
            messagebox.showwarning('No slots selected',
                                   'Enable at least one slot above.')
            return

        slots_str = '+'.join(sorted(target_slots))
        if not messagebox.askyesno('Confirm revert',
                                    f'Revert {entry.base_name} [{slots_str}] to backup?'):
            return

        try:
            n = entry.revert(target_slots)
        except Exception:
            messagebox.showerror('Revert failed', traceback.format_exc())
            return

        self._show_detail(entry)
        self._refresh_row_thumb(entry)
        self._set_status(
            f"Reverted {entry.base_name} in {n} slot(s) [{slots_str}].",
            SUCCESS)

    def _refresh_row_thumb(self, entry: CanvasEntry):
        row = self._item_rows.get(entry.base_name)
        if not row:
            return
        try:
            img = canvas_file_to_image(entry.primary_path())
            thumb = composite_on_checker(img, 48)
            ctk_img = ctk.CTkImage(light_image=thumb, dark_image=thumb, size=(48, 48))
            self._img_refs.append(ctk_img)
            thumb_holder = row.winfo_children()[0]
            for w in thumb_holder.winfo_children():
                w.destroy()
            ctk.CTkLabel(thumb_holder, image=ctk_img, text="").place(
                relx=0.5, rely=0.5, anchor="center")
        except Exception:
            pass

    def show_preview(self, entry: CanvasEntry):
        try:
            img = canvas_file_to_image(entry.primary_path())
        except Exception:
            messagebox.showerror('Preview failed', traceback.format_exc())
            return
        PreviewDialog(self, entry, img)

    # ── status bar ────────────────────────────────────────────────────────

    def _set_status(self, msg: str, color=MUTED2):
        self._status_var.set(msg)
        self._status_dot.configure(text_color=color)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    try:
        App().mainloop()
    except Exception:
        traceback.print_exc()
        input('Press Enter to exit...')


if __name__ == '__main__':
    main()
