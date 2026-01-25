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
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

import mss
import numpy as np
from PIL import Image

import pytesseract


# =========================
# USER CONFIG
# =========================

# If your laptop has Tesseract installed and you want a fixed path, set it here.
# If Tesseract is already on PATH, you can leave this as None.
TESSERACT_EXE_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

if TESSERACT_EXE_PATH:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE_PATH


# =========================
# PLACEHOLDER TOKENS (EDIT THESE LATER)
# =========================
# These are "intent names" you care about in your future logic tree.
# Each token has a list of strings that should match OCR text.
TOKENS: Dict[str, List[str]] = {
    "TOKEN_AUTO_BUTTON": ["AUTO"],
    "TOKEN_END_RUN": ["END", "RUN", "END RUN"],
    "TOKEN_DEATH": ["YOU DIED", "DEFEAT", "DEATH"],  # placeholder
}


# =========================
# USED FOR DEBUGGING
# =========================
import os
from datetime import datetime
DEBUG_SAVE_SCREENSHOTS = True          # set False to stop saving
DEBUG_SCREENSHOT_DIR = "debug_shots"   # folder inside your project
DEBUG_SAVE_EVERY_SCAN = False          # True = save every scan, False = only on Single Scan
def save_debug_screenshot(pil_img: Image.Image, base_dir: str, prefix: str = "shot") -> str:
    """
    Save a PIL image to a timestamped PNG file inside base_dir.
    Returns the full file path.
    """
    os.makedirs(base_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{prefix}_{ts}.png"
    path = os.path.join(base_dir, filename)

    pil_img.save(path, format="PNG")
    return path

def save_debug_screenshot(pil_img: Image.Image, base_dir: str, prefix: str = "shot") -> str:
    """
    Save a PIL image to a timestamped PNG file inside base_dir.
    Returns the full file path.
    """
    os.makedirs(base_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{prefix}_{ts}.png"
    path = os.path.join(base_dir, filename)

    pil_img.save(path, format="PNG")
    return path


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


@dataclass
class TokenMatch:
    """
    A semantic match: an OCR hit that matched a token you care about.
    token_name is your intent label, like TOKEN_AUTO_BUTTON.
    hit is the actual OCR data (text, confidence, bbox).
    """
    token_name: str
    hit: OcrHit


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
# TOKEN MATCHING
# =========================

def _normalize(s: str) -> str:
    """Simple normalization for matching OCR text."""
    return "".join(ch.lower() for ch in s.strip())


def match_tokens(hits: List[OcrHit], tokens: Dict[str, List[str]]) -> Dict[str, List[TokenMatch]]:
    """
    Convert raw OCR hits into semantic matches keyed by token name.
    Output is a dictionary:
      matches["TOKEN_AUTO_BUTTON"] = [TokenMatch(...), TokenMatch(...)]
    """
    matches: Dict[str, List[TokenMatch]] = {k: [] for k in tokens.keys()}

    for hit in hits:
        hit_norm = _normalize(hit.text)

        for token_name, variants in tokens.items():
            for v in variants:
                v_norm = _normalize(v)

                # Simple placeholder matching:
                # - exact match OR substring match
                # You can replace this later with fuzzy matching if you want.
                if hit_norm == v_norm or v_norm in hit_norm:
                    matches[token_name].append(TokenMatch(token_name=token_name, hit=hit))
                    break

    # Optional: sort each token's matches in a stable "reading order"
    for token_name in matches:
        matches[token_name].sort(key=lambda m: (m.hit.bbox[1], m.hit.bbox[0]))

    return matches


# =========================
# TINY HELPER FUNCTION (anchor cache)
# =========================

def get_anchor(
    token_name: str,
    matches: Dict[str, List[TokenMatch]],
    anchor_cache: Dict[str, OcrHit],
    min_conf: int = 70
) -> Optional[OcrHit]:
    """
    Tiny helper:
    - If we already found this token before and cached it, return the cached OcrHit
    - Otherwise find the best match now (highest confidence), cache it, and return it

    Why this helps:
    - Your logic tree can ask for "AUTO button location" and not worry about OCR details
    - You can clear anchor_cache after a crash or reset to force re-discovery
    """
    # 1) Return cached anchor if available
    if token_name in anchor_cache:
        return anchor_cache[token_name]

    # 2) If no matches exist, no anchor
    token_matches = matches.get(token_name, [])
    if not token_matches:
        return None

    # 3) Pick the best match by confidence
    best = max(token_matches, key=lambda m: m.hit.conf)

    if best.hit.conf < min_conf:
        return None

    # 4) Cache and return
    anchor_cache[token_name] = best.hit
    return best.hit


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

        # Anchor cache (token_name -> OcrHit)
        self.anchor_cache: Dict[str, OcrHit] = {}

        # Thread-safe queue to send text output to the GUI
        self.ui_queue: "queue.Queue[str]" = queue.Queue()



        self._build_ui()

        # Hotkeys
        # F5: Start
        # F8: Stop
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

        ttk.Button(tools, text="Clear Output", command=self._clear_output).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(tools, text="Clear Anchor Cache", command=self._clear_cache).grid(row=0, column=1, padx=(0, 12))

        ttk.Label(tools, text="Filter OCR contains:").grid(row=0, column=2, sticky="w", padx=(0, 6))

        filter_entry = ttk.Entry(tools, textvariable=self.debug_filter, width=18)
        filter_entry.grid(row=0, column=3, sticky="w")

        ttk.Button(tools, text="Clear Filter", command=lambda: self.debug_filter.set("")).grid(row=0, column=4, sticky="w", padx=(8, 0))

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
        self.anchor_cache.clear()
        self._append_output("[cache] Anchor cache cleared")

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
        threading.Thread(target=self._scan_once, daemon=True).start()

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
            
            # =========================
            # DEBUG SAVE START (comment out later)
            # =========================
            pil_img = grab_full_desktop_pil()
            if DEBUG_SAVE_SCREENSHOTS:
                should_save = DEBUG_SAVE_EVERY_SCAN or (not self.is_running.get())
                if should_save:
                    out_dir = os.path.join(os.getcwd(), DEBUG_SCREENSHOT_DIR)
                    saved_path = save_debug_screenshot(pil_img, out_dir, prefix="desktop")
                    self._log(f"[debug] saved screenshot: {saved_path}")
            # =========================
            # DEBUG SAVE END
            # =========================

            
            dt = time.time() - t0
            target = self.refresh_ms.get() / 1000.0

            # If OCR takes longer than the target, we do not "queue scans".
            # We just run again as soon as possible (with a tiny minimum sleep).
            sleep_s = max(0.05, target - dt)
            time.sleep(sleep_s)

        self._log("[run] stopped")

    def _scan_once(self):
        """
        One scan iteration.
        This is the heart of the learning harness.
        """
        try:
            t0 = time.time()

            # 1) Capture
            pil_img = grab_full_desktop_pil()

            # 2) OCR -> hits
            hits = ocr_image_to_hits(pil_img, conf_threshold=int(self.conf_threshold.get()))

            # 3) Token matching
            matches = match_tokens(hits, TOKENS)

            # 4) Tiny helper example: get anchors for tokens you care about
            auto_anchor = get_anchor("TOKEN_AUTO_BUTTON", matches, self.anchor_cache, min_conf=70)
            end_run_anchor = get_anchor("TOKEN_END_RUN", matches, self.anchor_cache, min_conf=70)

            # 5) Build signals (screen snapshot facts)
            signals = {
                "has_auto": auto_anchor is not None,
                "has_end_run": end_run_anchor is not None,
                "has_death": bool(matches.get("TOKEN_DEATH")),
            }

            dt_ms = int((time.time() - t0) * 1000)

            # =========================
            # DEBUG SECTION START
            # This output is intentionally verbose so you can learn how OCR behaves.
            # You can later comment this out or reduce it.
            # =========================
            now = time.strftime("%H:%M:%S")
            self._log(f"[scan {now}] hits={len(hits)}  dt={dt_ms}ms  signals={signals}")

            # Print top hits by confidence
            flt = self.debug_filter.get().strip().lower()

            top = sorted(hits, key=lambda h: h.conf, reverse=True)

            # If a filter is set, show only hits containing that substring (case-insensitive)
            if flt:
                top = [h for h in top if flt in h.text.lower()]
                self._log(f"  [filter] showing only OCR hits containing '{flt}'")

            top = top[:30]

            for h in top:
                x, y, w, hh = h.bbox
                self._log(f"  OCR: conf={h.conf:>3}  text='{h.text}'  bbox=({x},{y},{w},{hh})")

            # Print matches per token
            for token_name, lst in matches.items():
                if not lst:
                    continue

                # If filter set, only show match lines where the matched OCR text contains it
                if flt:
                    if not any(flt in m.hit.text.lower() for m in lst):
                        continue

                best = max(lst, key=lambda m: m.hit.conf)
                bx, by, bw, bh = best.hit.bbox
                self._log(f"  MATCH: {token_name}  best='{best.hit.text}' conf={best.hit.conf} bbox=({bx},{by},{bw},{bh})")


            # Print cached anchors (what is currently "sticky" across scans)
            if self.anchor_cache:
                self._log(f"  CACHE: {list(self.anchor_cache.keys())}")
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
