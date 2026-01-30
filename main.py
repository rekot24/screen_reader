"""
Bare OCR Framework (Tkinter + MSS + Tesseract)

What this app does:
- Captures the screen (all monitors) at an interval
- Runs OCR
- Stores OCR results as dataclasses
- Prints a readable debug output so you can learn and tune OCR
- Provides a tiny helper function to anchor on specific tokens and cache their locations

Hotkeys:
- F5: Start scanning loop
- F8: Stop scanning loop

Notes:
- This is intentionally minimal and heavily commented so you can learn it.
- Later you can remove or comment out the DEBUG blocks.
"""

import time
import threading
import queue
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

import win32gui
import win32con
import win32process

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

import mss
import numpy as np
from PIL import Image

import pytesseract

import pyautogui
from pyscreeze import ImageNotFoundException

# =========================
# USER CONFIG
# =========================
APP_DIR = Path(__file__).resolve().parent
ASSETS_DIR = APP_DIR / "assets"
# Target window title substring to activate before capture (case-insensitive).
TARGET_WINDOW_TITLE_CONTAINS = "Roblox"
ACTIVATE_BEFORE_CAPTURE = True

# If your laptop has Tesseract installed and you want a fixed path, set it here.
# If Tesseract is already on PATH, you can leave this as None.
TESSERACT_EXE_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

if TESSERACT_EXE_PATH:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE_PATH


# =========================
# DATA MODELS (dataclasses)
# =========================

@dataclass
class OcrHit:
    """
    One OCR word (or token) detected on screen.
    bbox is (x, y, w, h) relative to the captured screenshot.
    """
    text: str
    conf: int
    bbox: Tuple[int, int, int, int]


# =========================
# DETECTOR REGISTRY
# Put near the top of main.py (after imports and dataclasses)
# =========================

# Unified result type for any detector (OCR or IMAGE)
@dataclass
class DetectResult:
    name: str
    kind: str                 # "ocr" or "image"
    found: bool
    bbox: Optional[Tuple[int, int, int, int]] = None  # x, y, w, h in desktop coords
    text: Optional[str] = None
    conf: Optional[int] = None
    extra: Optional[Dict[str, Any]] = None


# Registry that defines all detection rules in one place
DETECTORS: Dict[str, Dict[str, Any]] = {
    # OCR detectors
    # token is substring match against OCR hits, case-insensitive
    "END_RUN_TEXT": {
        "kind": "ocr",
        "token": "End Run",           # placeholder, you edit later
        "min_conf": 40,               # per-detector threshold
    },
    "AUTO_TEXT": {
        "kind": "ocr",
        "token": "Auto",              # placeholder
        "min_conf": 30,
    },

    # IMAGE detectors (template matching)
    "AUTO_RED_ICON": {
        "kind": "image",
        "path": str(ASSETS_DIR / "auto_red.png"),
        "confidence": 0.82,
        "timeout_s": 1.5,
    },
    "AUTO_GREEN_ICON": {
        "kind": "image",
        "path": str(ASSETS_DIR / "auto_green.png"),
        "confidence": 0.82,
        "timeout_s": 1.5,
    },
}

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.02

def find_image_on_screen(template_path: str, confidence: float = 0.85, timeout_s: float = 2.0):
    """
    Returns a pyautogui Box (left, top, width, height) or None.
    Never raises ImageNotFoundException.
    """
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            box = pyautogui.locateOnScreen(template_path, confidence=confidence)
        except ImageNotFoundException:
            # PyAutoGUI/PyScreeze sometimes throws instead of returning None
            box = None
        except Exception:
            # Any unexpected issues should not kill your scan loop
            box = None

        if box:
            return box

    return None



# =========================
# DETECTOR ENGINE HELPERS
# These functions assume you already have:
# - hits: List[OcrHit] from your OCR scan
# - find_image_on_screen(...) using pyautogui.locateOnScreen
# =========================

def _first_ocr_hit_containing(hits: List["OcrHit"], token: str, min_conf: int) -> Optional["OcrHit"]:
    token_l = token.lower()
    # Sort by confidence so the best match wins
    for h in sorted(hits, key=lambda x: x.conf, reverse=True):
        if h.conf < min_conf:
            continue
        if token_l in h.text.lower():
            return h
    return None


def run_detector(
    name: str,
    cfg: Dict[str, Any],
    hits: List["OcrHit"],
) -> DetectResult:
    kind = cfg["kind"]

    if kind == "ocr":
        token = cfg["token"]
        min_conf = int(cfg.get("min_conf", 0))
        h = _first_ocr_hit_containing(hits, token=token, min_conf=min_conf)
        if not h:
            return DetectResult(name=name, kind="ocr", found=False)

        return DetectResult(
            name=name,
            kind="ocr",
            found=True,
            bbox=h.bbox,
            text=h.text,
            conf=h.conf,
            extra={"token": token, "min_conf": min_conf},
        )

    if kind == "image":
        # This assumes your existing helper exists:
        # find_image_on_screen(template_path, confidence, timeout_s) -> Box|None
        try:
            box = find_image_on_screen(
                template_path=cfg["path"],
                confidence=float(cfg.get("confidence", 0.85)),
                timeout_s=float(cfg.get("timeout_s", 2.0)),
            )
        except Exception as e:
            return DetectResult(
            name=name,
            kind="image",
            found=False,
            extra={"error": f"{type(e).__name__}: {e}"}
        )

        if not box:
            return DetectResult(name=name, kind="image", found=False)

        # pyautogui Box is left, top, width, height
        bbox = (int(box.left), int(box.top), int(box.width), int(box.height))
        return DetectResult(
            name=name,
            kind="image",
            found=True,
            bbox=bbox,
            extra={"path": cfg["path"], "confidence": cfg.get("confidence", 0.85)},
        )

    raise ValueError(f"Unknown detector kind: {kind}")


def run_detectors(
    detector_names: List[str],
    hits: List["OcrHit"],
) -> Dict[str, DetectResult]:
    out: Dict[str, DetectResult] = {}
    for name in detector_names:
        cfg = DETECTORS[name]
        out[name] = run_detector(name, cfg, hits)
    return out


# =========================
# OPTIONAL: SIMPLE CACHE
# Caches bbox results so you do not re-search every scan
# Clear this cache when you detect a crash or when you intentionally reset the UI
# =========================

class DetectorCache:
    def __init__(self):
        self._data: Dict[str, Tuple[DetectResult, float]] = {}

    def keys(self):
        return list(self._data.keys())

    def clear(self):
        self._data.clear()

    def get(self, name: str) -> Optional[DetectResult]:
        item = self._data.get(name)
        return item[0] if item else None

    def set(self, name: str, result: DetectResult):
        self._data[name] = (result, time.time())

    def get_or_run(self, name: str, hits: List["OcrHit"], refresh: bool = False) -> DetectResult:
        if not refresh:
            cached = self.get(name)
            if cached and cached.found:
                return cached

        cfg = DETECTORS[name]
        res = run_detector(name, cfg, hits)
        if res.found:
            self.set(name, res)
        return res


# =========================
# DEBUG SECTION START
# =========================
from PIL import ImageDraw
import os
from datetime import datetime
DEBUG_SAVE_SCREENSHOTS = True          # set False to stop saving
DEBUG_SCREENSHOT_DIR = "debug_shots"   # folder inside your project
DEBUG_SAVE_EVERY_SCAN = False          # True = save every scan, False = only on Single Scan
def project_dir() -> str:
    # Folder where this script lives (stable)
    return os.path.dirname(os.path.abspath(__file__))
def save_debug_screenshot(pil_img, subfolder="debug_shots", prefix="desktop") -> str:
    """
    Saves a PIL image into <project folder>/<subfolder>/prefix_timestamp.png
    Returns the file path.
    Raises exception if it fails (caller should catch/log).
    """
    base_dir = os.path.join(project_dir(), subfolder)
    os.makedirs(base_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.join(base_dir, f"{prefix}_{ts}.png")

    pil_img.save(path, format="PNG")
    return path
def draw_ocr_boxes(pil_img: Image.Image, hits: List[OcrHit], max_boxes: Optional[int] = None) -> Image.Image:
    """
    Returns a COPY of the image with OCR bounding boxes drawn on it.
    max_boxes can be used to limit how many boxes are drawn (None = all).
    """
    out = pil_img.copy()
    draw = ImageDraw.Draw(out)

    # Optionally sort by confidence so the "best" boxes are drawn first
    hits_sorted = sorted(hits, key=lambda h: h.conf, reverse=True)

    if max_boxes is not None:
        hits_sorted = hits_sorted[:max_boxes]

    for h in hits_sorted:
        x, y, w, hh = h.bbox
        x2, y2 = x + w, y + hh

        # Rectangle around the OCR hit
        draw.rectangle([x, y, x2, y2], outline="yellow", width=2)

        # Label (text + conf) drawn above the box if possible
        label = f"{h.text} ({h.conf})"
        text_y = y - 14 if y - 14 > 0 else y + 2
        draw.text((x, text_y), label, fill="yellow")

    return out
# =========================
# DEBUG SECTION END
# =========================


# =========================
# DPI AWARENESS (Windows)
# Put this at the top of main.py BEFORE creating Tk()
# =========================
import sys

if sys.platform.startswith("win"):
    try:
        import ctypes
        # Best option on Win 8.1+ / Win 10/11: Per-monitor DPI aware
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 2 = PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            import ctypes
            # Fallback for older Windows: System DPI aware
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# =========================
# OCR ENGINE
# =========================

def grab_full_desktop_pil() -> Image.Image:
    """
    Capture the full virtual desktop (all monitors) and return a PIL image.
    This keeps the coordinate system consistent across crashes and window moves.
    """
    with mss.mss() as sct:
        monitor = sct.monitors[0]  # 0 means "all monitors" in MSS
        frame = sct.grab(monitor)
        img = Image.frombytes("RGB", frame.size, frame.rgb)
        return img


def ocr_image_to_hits(pil_img: Image.Image, conf_threshold: int = 60) -> List[OcrHit]:
    """
    Run Tesseract OCR and convert results into a list of OcrHit objects.
    We use image_to_data because it includes bounding boxes + confidences.
    """
    # Convert to grayscale to help OCR a bit
    gray = pil_img.convert("L")

    data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)

    hits: List[OcrHit] = []
    n = len(data.get("text", []))

    for i in range(n):
        txt = (data["text"][i] or "").strip()
        if not txt:
            continue

        # Tesseract sometimes returns conf as string float, sometimes "-1"
        try:
            conf = int(float(data["conf"][i]))
        except Exception:
            conf = -1

        if conf < conf_threshold:
            continue

        x = int(data["left"][i])
        y = int(data["top"][i])
        w = int(data["width"][i])
        h = int(data["height"][i])

        hits.append(OcrHit(text=txt, conf=conf, bbox=(x, y, w, h)))

    return hits


# =========================
# ACTIVATE TARGET WINDOW HELPERS
# =========================
def _enum_windows():
    """Return a list of (hwnd, title) for visible top-level windows."""
    out = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title:
            out.append((hwnd, title))
    win32gui.EnumWindows(callback, None)
    return out


def find_window_by_title_contains(title_substring: str):
    """
    Find the first top-level window whose title contains title_substring (case-insensitive).
    Returns hwnd or None.
    """
    needle = title_substring.lower().strip()
    for hwnd, title in _enum_windows():
        if needle in title.lower():
            return hwnd
    return None


def activate_window(hwnd: int) -> bool:
    """
    Try to bring a window to the foreground and restore it if minimized.
    Returns True if it likely succeeded.
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False

    # Restore if minimized
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    # Make sure it is shown
    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

    try:
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        # Windows can block SetForegroundWindow in some cases.
        # A common workaround is to bring it to top then try again.
        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False
        

# =========================
# GUI APP
# =========================

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Bare OCR Framework")

        # Thread control
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        # UI variables
        self.refresh_ms = tk.IntVar(value=800)
        self.conf_threshold = tk.IntVar(value=60)
        self.is_running = tk.BooleanVar(value=False)

        # Debug filter Safe to remove later
        self.debug_filter = tk.StringVar(value="")

        # Thread-safe queue to send text output to the GUI
        self.ui_queue: "queue.Queue[str]" = queue.Queue()

        # Detector cache
        self.det_cache = DetectorCache()

        self._build_ui()

        # Hotkeys
        # F1: Single Scan
        # F5: Start
        # F8: Stop
        self.root.bind("<F1>", lambda _e: self.single_scan())
        self.root.bind("<F5>", lambda _e: self.start())
        self.root.bind("<F8>", lambda _e: self.stop())

        # Periodically drain UI queue so threads do not touch Tk directly
        self._pump_ui_queue()

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.grid(row=0, column=0, sticky="nsew")

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)

        # Controls row
        controls = ttk.LabelFrame(outer, text="Controls", padding=10)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)

        btns = ttk.Frame(controls)
        btns.grid(row=0, column=0, sticky="w")

        self.btn_start = ttk.Button(btns, text="Start (F5)", command=self.start)
        self.btn_start.grid(row=0, column=0, padx=(0, 8))

        self.btn_stop = ttk.Button(btns, text="Stop (F8)", command=self.stop, state="disabled")
        self.btn_stop.grid(row=0, column=1, padx=(0, 8))

        self.btn_scan = ttk.Button(btns, text="Single Scan", command=self.single_scan)
        self.btn_scan.grid(row=0, column=2)

        # Refresh Spinbox
        refresh_frame = ttk.Frame(controls)
        refresh_frame.grid(row=1, column=0, sticky="w", pady=(10, 0))

        ttk.Label(refresh_frame, text="Refresh (ms):").grid(row=0, column=0, sticky="w", padx=(0, 6))

        # Spinbox with:
        # - min 500
        # - max 3000
        # - step 100
        self.spin_refresh = ttk.Spinbox(
            refresh_frame,
            from_=500,
            to=3000,
            increment=100,
            textvariable=self.refresh_ms,
            width=8
        )
        self.spin_refresh.grid(row=0, column=1, sticky="w")

        ttk.Label(refresh_frame, text="(min 500, max 3000, step 100)").grid(row=0, column=2, padx=(8, 0))

        # Confidence threshold
        conf_frame = ttk.Frame(controls)
        conf_frame.grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(conf_frame, text="OCR confidence threshold:").grid(row=0, column=0, padx=(0, 6))
        ttk.Spinbox(
            conf_frame,
            from_=0,
            to=100,
            increment=5,
            textvariable=self.conf_threshold,
            width=8
        ).grid(row=0, column=1, sticky="w")

        # Debug output
        # =========================
        # DEBUG SECTION START
        # This whole section is safe to comment out later if you want no debug UI.
        # =========================
        debug = ttk.LabelFrame(outer, text="Debug Output (safe to remove later)", padding=10)
        debug.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        outer.rowconfigure(1, weight=1)

        self.txt = ScrolledText(debug, height=18, wrap="word")
        self.txt.grid(row=0, column=0, sticky="nsew")
        debug.columnconfigure(0, weight=1)
        debug.rowconfigure(0, weight=1)

        tools = ttk.Frame(debug)
        tools.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        tools.columnconfigure(4, weight=1)

        ttk.Label(tools, text="Filter OCR contains:").grid(row=0, column=2, sticky="w", padx=(0, 6))

        filter_entry = ttk.Entry(tools, textvariable=self.debug_filter, width=18)
        filter_entry.grid(row=0, column=3, sticky="w")

        ttk.Button(tools, text="Clear Filter", command=lambda: self.debug_filter.set("")).grid(row=0, column=4, sticky="w", padx=(8, 0))
        ttk.Button(tools, text="Clear Detector Cache", command=self._clear_cache).grid(row=0, column=0, sticky="w", padx=(0, 8))


        # =========================
        # DEBUG SECTION END
        # =========================

    # =========================
    # DEBUG HELPERS (safe to remove later)
    # =========================

    def _append_output(self, text: str):
        """Append text to the debug output box."""
        self.txt.insert("end", text + "\n")
        self.txt.see("end")

    def _clear_output(self):
        self.txt.delete("1.0", "end")

    def _clear_cache(self):
        self.det_cache.clear()
        self._append_output("[cache] Detector cache cleared")

    def _pump_ui_queue(self):
        """
        Drain messages from worker threads and add them to the debug output.
        We do this because Tkinter is not thread-safe.
        """
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                self._append_output(msg)
        except queue.Empty:
            pass

        self.root.after(50, self._pump_ui_queue)

    def _log(self, msg: str):
        """Thread-safe logging: worker threads call this."""
        self.ui_queue.put(msg)

    # =========================
    # BUTTON ACTIONS
    # =========================

    def start(self):
        """Start continuous scanning loop."""
        if self.is_running.get():
            return

        self._stop_event.clear()
        self.is_running.set(True)

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_scan.config(state="disabled")

        self._worker_thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._worker_thread.start()

        self._log("[run] started")

    def stop(self):
        """Stop continuous scanning loop."""
        if not self.is_running.get():
            return

        self._stop_event.set()
        self.is_running.set(False)

        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_scan.config(state="normal")

        self._log("[run] stop requested")

    def single_scan(self):
        """
        Run exactly one scan.
        We run it in a thread so the UI stays responsive.
        """
        threading.Thread(target=lambda: self._scan_once(force_refresh=True), daemon=True).start()

    # =========================
    # CORE LOOP
    # =========================

    def _scan_loop(self):
        """
        Main scanning loop.
        Each iteration:
        - capture screen
        - OCR
        - match tokens
        - print debug info
        - sleep until next scan
        """
        while not self._stop_event.is_set():
            t0 = time.time()
            self._scan_once()
            dt = time.time() - t0
            target = self.refresh_ms.get() / 1000.0

            # If OCR takes longer than the target, we do not "queue scans".
            # We just run again as soon as possible (with a tiny minimum sleep).
            sleep_s = max(0.05, target - dt)
            time.sleep(sleep_s)

        self._log("[run] stopped")

    def _scan_once(self, force_refresh: bool = False):
        """
        One scan iteration.
        This is the heart of the learning harness.
        """
        try:
            t0 = time.time()

            if ACTIVATE_BEFORE_CAPTURE:
                hwnd = find_window_by_title_contains(TARGET_WINDOW_TITLE_CONTAINS)
                if hwnd:
                    ok = activate_window(hwnd)
                    self._log(f"[focus] activate '{TARGET_WINDOW_TITLE_CONTAINS}' ok={ok}")
                    # Small delay helps Windows finish repainting before capture
                    time.sleep(0.15)
                else:
                    self._log(f"[focus] window not found for title contains: '{TARGET_WINDOW_TITLE_CONTAINS}'")

            # 1) Capture
            pil_img = grab_full_desktop_pil()

            # 2) OCR -> hits
            hits = ocr_image_to_hits(pil_img, conf_threshold=int(self.conf_threshold.get()))

            # 3) Run detectors (choose which ones you care about for now)
            detector_names = [
                "AUTO_RED_ICON",
                "AUTO_GREEN_ICON",
                "END_RUN_TEXT",
                "AUTO_TEXT",
            ]
            results = {name: self.det_cache.get_or_run(name, hits, refresh=force_refresh) for name in detector_names}

            # 4) Build signals from detector results
            signals = {
                "has_auto_red": results["AUTO_RED_ICON"].found,
                "has_auto_green": results["AUTO_GREEN_ICON"].found,
                "has_end_run": results["END_RUN_TEXT"].found,
                "has_auto_text": results["AUTO_TEXT"].found,
            }

            dt_ms = int((time.time() - t0) * 1000)

            # =========================
            # DEBUG SECTION START
            # This output is intentionally verbose so you can learn how OCR behaves.
            # You can later comment this out or reduce it.
            # =========================
            # Saves an annotated screenshot with bounding boxes around OCR hits
            try:
                annotated = draw_ocr_boxes(pil_img, hits, max_boxes=None)  # None = draw ALL
                saved_path = save_debug_screenshot(annotated, subfolder="debug_shots", prefix="annotated")
                self._log(f"[debug] saved annotated screenshot: {saved_path}")
            except Exception as e:
                self._log(f"[debug] annotated save FAILED: {type(e).__name__}: {e}")

            now = time.strftime("%H:%M:%S")
            self._log(f"[scan {now}] hits={len(hits)}  dt={dt_ms}ms  signals={signals}")

            # Print top hits by confidence
            flt = self.debug_filter.get().strip().lower()

            top = sorted(hits, key=lambda h: h.conf, reverse=True)

            # If a filter is set, show only hits containing that substring (case-insensitive)
            if flt:
                top = [h for h in top if flt in h.text.lower()]
                self._log(f"  [filter] showing only OCR hits containing '{flt}'")

            # top = top[:30] # limit number of printed hits if desired

            for h in top:
                x, y, w, hh = h.bbox
                self._log(f"  OCR: conf={h.conf:>3}  text='{h.text}'  bbox=({x},{y},{w},{hh})")

            # Print detector results (new model)
            for name, r in results.items():
                if flt:
                    hay = (name + " " + (r.text or "")).lower()
                    if flt not in hay:
                        continue
                self._log(
                    f"  DETECT: {name} kind={r.kind} found={r.found} "
                    f"bbox={r.bbox} text='{r.text}' conf={r.conf}"
                )
            
            # Print cached detectors (what is currently "sticky" across scans)
            cached = self.det_cache.keys()
            if cached:
                self._log(f"  CACHE: {cached}")
            
            # Save screenshot if enabled
            try:
                if DEBUG_SAVE_EVERY_SCAN or (not self.is_running.get()):
                    saved_path = save_debug_screenshot(pil_img, subfolder="debug_shots", prefix="desktop")
                    self._log(f"[debug] saved screenshot: {saved_path}")
            except Exception as e:
                self._log(f"[debug] screenshot save FAILED: {type(e).__name__}: {e}")
            # =========================
            # DEBUG SECTION END
            # =========================

        except Exception as e:
            self._log(f"[error] {type(e).__name__}: {e}")


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
