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
from datetime import datetime
import threading
import cv2
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

from process_manager import ensure_process_running
from window_manager import EnforceConfig, ensure_window

from click_points import CLICK_POINTS
from clicker import click_point, scroll_view
from state_machine import resolve_state

import states

# =========================
# DEBUGGING IMPORTS
# =========================
import debugging

# =========================
# CONFIG LOADER
# =========================
from config_loader import load_config, validate_template_files, print_config_summary

# Load configuration at module level
try:
    CONFIG = load_config()
    print_config_summary(CONFIG)
except Exception as e:
    print(f"[FATAL] Failed to load config: {e}")
    import sys
    sys.exit(1)

# Configure Tesseract from config
if CONFIG.tesseract_exe_path:
    pytesseract.pytesseract.tesseract_cmd = CONFIG.tesseract_exe_path

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


# Detectors are now loaded from CONFIG
# Access via: CONFIG.detectors

# Configure PyAutoGUI from config
pyautogui.FAILSAFE = CONFIG.pyautogui_failsafe
pyautogui.PAUSE = CONFIG.pyautogui_pause

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
    frame_bgr: np.ndarray,
    bank: "TemplateBank",
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

        paths = cfg.get("paths") or [cfg["path"]]
        threshold = float(cfg.get("confidence", 0.85))

        try:
            bbox, extra = find_any_template_in_frame(
                frame_bgr=frame_bgr,
                template_paths=paths,
                bank=bank,
                threshold=threshold,
            )
        except Exception as e:
            return DetectResult(
            name=name,
            kind="image",
            found=False,
            extra={"error": f"{type(e).__name__}: {e}"}
        )

        if not bbox:
            return DetectResult(name=name, kind="image", found=False)

        return DetectResult(
            name=name,
            kind="image",
            found=True,
            bbox=bbox,
            extra=extra,
        )

    raise ValueError(f"Unknown detector kind: {kind}")


def run_detectors(
    detector_names: List[str],
    hits: List["OcrHit"],
    frame_bgr: np.ndarray,
    bank: "TemplateBank",
    detectors_dict: Dict[str, Dict[str, Any]],
) -> Dict[str, DetectResult]:
    out: Dict[str, DetectResult] = {}
    for name in detector_names:
        cfg = detectors_dict[name]
        out[name] = run_detector(name, cfg, hits, frame_bgr, bank)
    return out

    
# =========================
# FAST TEMPLATE MATCHING MODULES
# =========================
class TemplateBank:
    """
    Loads template images once and keeps them in memory as cv2 BGR arrays.
    """
    def __init__(self):
        self._cache = {}  # path -> cv2 image (BGR)

    def get(self, path: str):
        if path in self._cache:
            return self._cache[path]

        img = cv2.imread(path, cv2.IMREAD_COLOR)  # BGR
        if img is None:
            raise FileNotFoundError(f"Template could not be read: {path}")
        self._cache[path] = img
        return img

    def clear(self):
        self._cache.clear()


def match_template_once(frame_bgr: np.ndarray, templ_bgr: np.ndarray) -> tuple[float, tuple[int, int]]:
    """
    Returns: (max_score, (x, y)) where (x, y) is top-left in frame coords.
    Uses normalized correlation coefficient.
    """
    result = cv2.matchTemplate(frame_bgr, templ_bgr, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    return float(max_val), (int(max_loc[0]), int(max_loc[1]))


def find_any_template_in_frame(
    frame_bgr: np.ndarray,
    template_paths: list[str],
    bank: TemplateBank,
    threshold: float = 0.82,
) -> tuple[tuple[int, int, int, int] | None, dict | None]:
    """
    Try multiple templates against the SAME frame.
    Returns:
      bbox (x,y,w,h) if found else None,
      extra info dict (matched_path, score) if found else None
    """
    best_score = -1.0
    best_bbox = None
    best_path = None

    for path in template_paths:
        templ = bank.get(path)
        score, (x, y) = match_template_once(frame_bgr, templ)
        if score > best_score:
            best_score = score
            best_path = path
            h, w = templ.shape[:2]
            best_bbox = (x, y, w, h)

    if best_score >= threshold and best_bbox is not None:
        return best_bbox, {"matched_path": best_path, "score": best_score}

    return None, None


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

def grab_rect_pil(left: int, top: int, width: int, height: int) -> Image.Image:
    """
    Capture a specific rectangle of the desktop using MSS and return a PIL Image.

    This is much faster than capturing all monitors.
    Coordinates are in global screen space (same as MSS monitor coords).
    """
    with mss.mss() as sct:
        region = {"left": int(left), "top": int(top), "width": int(width), "height": int(height)}
        frame = sct.grab(region)
        return Image.frombytes("RGB", frame.size, frame.rgb)


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


def bbox_center(bbox: Tuple[int, int, int, int]) -> Tuple[int, int]:
    """
    Calculate the center point of a bounding box.
    Args:
        bbox: (x, y, w, h)
    Returns:
        (center_x, center_y)
    """
    x, y, w, h = bbox
    return (x + w // 2, y + h // 2)
        

# =========================
# GUI APP
# =========================

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Screen Reader")

        # Window enforcement config
        self.window_cfg = EnforceConfig(
            title_contains=CONFIG.target_window_title,
            monitor_index=CONFIG.target_monitor_index,
            target_client_w=CONFIG.target_client_w,
            target_client_h=CONFIG.target_client_h,
        )
        # Thread control
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        # UI variables
        self.refresh_ms = tk.IntVar(value=CONFIG.default_refresh_ms)
        self.conf_threshold = tk.IntVar(value=CONFIG.default_conf_threshold)
        self.is_running = tk.BooleanVar(value=False)

        # Click timing config (in milliseconds)
        self.click_timer_ms = tk.IntVar(value=300000)  # Default: 5 minutes (5 * 60 * 1000)
        self.double_click_delay_ms = tk.IntVar(value=500)  # Default: 0.5 seconds
        self.last_click_time = 0  # Track when last click occurred

        # Current state tracking
        self.current_state = tk.StringVar(value="UNKNOWN")
        self.last_state = "UNKNOWN"
        self.state_start_time = time.time()

        # Server selection (mutually exclusive)
        self.public_server = tk.BooleanVar(value=True)
        self.private_server = tk.BooleanVar(value=False)

        # Debug filter Safe to remove later
        self.debug_filter = tk.StringVar(value="")

        # Thread-safe queue to send text output to the GUI
        self.ui_queue: "queue.Queue[str]" = queue.Queue()

        # Template bank
        self.templates = TemplateBank()

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

        # Click Timer (below buttons)
        click_timer_frame = ttk.Frame(controls)
        click_timer_frame.grid(row=1, column=0, sticky="w", pady=(10, 0))

        ttk.Label(click_timer_frame, text="Click Timer:").grid(row=0, column=0, sticky="w", padx=(0, 6))

        # Spinbox for click timer in milliseconds
        self.spin_click_timer = ttk.Spinbox(
            click_timer_frame,
            from_=1000,
            to=3600000,  # Up to 1 hour
            increment=1000,
            textvariable=self.click_timer_ms,
            width=10
        )
        self.spin_click_timer.grid(row=0, column=1, sticky="w")

        ttk.Label(click_timer_frame, text="(values in ms)").grid(row=0, column=2, padx=(8, 0))

        # Double Click Delay (below click timer)
        double_click_frame = ttk.Frame(controls)
        double_click_frame.grid(row=2, column=0, sticky="w", pady=(8, 0))

        ttk.Label(double_click_frame, text="Double Click Delay:").grid(row=0, column=0, sticky="w", padx=(0, 6))

        self.spin_double_click_delay = ttk.Spinbox(
            double_click_frame,
            from_=100,
            to=2000,
            increment=100,
            textvariable=self.double_click_delay_ms,
            width=10
        )
        self.spin_double_click_delay.grid(row=0, column=1, sticky="w")

        ttk.Label(double_click_frame, text="(ms between clicks)").grid(row=0, column=2, padx=(8, 0))

        # Current State Display (below double click delay)
        state_frame = ttk.Frame(controls)
        state_frame.grid(row=3, column=0, sticky="w", pady=(8, 0))

        ttk.Label(state_frame, text="Current State:").grid(row=0, column=0, sticky="w", padx=(0, 6))

        self.state_display = ttk.Entry(state_frame, textvariable=self.current_state, state="readonly", width=20)
        self.state_display.grid(row=0, column=1, sticky="w")

        # Server Selection (below current state)
        server_frame = ttk.Frame(controls)
        server_frame.grid(row=4, column=0, sticky="w", pady=(8, 0))

        ttk.Label(server_frame, text="Server Type:").grid(row=0, column=0, sticky="w", padx=(0, 6))

        self.chk_public = ttk.Checkbutton(
            server_frame,
            text="Public Server",
            variable=self.public_server,
            command=self._on_public_toggle
        )
        self.chk_public.grid(row=0, column=1, sticky="w", padx=(0, 12))

        self.chk_private = ttk.Checkbutton(
            server_frame,
            text="Private Server",
            variable=self.private_server,
            command=self._on_private_toggle
        )
        self.chk_private.grid(row=0, column=2, sticky="w")

        # =========================
        # DEBUG UI SECTION START
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

    def _on_public_toggle(self):
        """When public server is toggled on, turn off private server."""
        if self.public_server.get():
            self.private_server.set(False)

    def _on_private_toggle(self):
        """When private server is toggled on, turn off public server."""
        if self.private_server.get():
            self.public_server.set(False)

    def _log(self, msg: str):
        """Thread-safe logging: worker threads call this."""
        # Check if actions logging is enabled
        if not CONFIG.enable_actions_logging:
            return

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.ui_queue.put(f"[{ts}] {msg}")

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
            sleep_s = max(CONFIG.min_sleep_s, target - dt)
            time.sleep(sleep_s)

        self._log("[run] stopped")

    def _scan_once(self, force_refresh: bool = False):
        """
        One scan iteration.
        This is the heart of the learning harness.
        """
        try:
            t0 = time.time()

            # ENSURE PROCESS IS RUNNING
            process_running = ensure_process_running(
                title_contains=CONFIG.target_window_title,
                exe_path=CONFIG.window_exe_path,
                wait_after_launch_s=CONFIG.wait_after_launch_s,
                log_fn=self._log,
                launch_enabled=CONFIG.launch_if_not_found,
            )

            if not process_running:
                self._log("[scan] Target application not running, skipping scan")
                return

            # ENSURE WINDOW EXISTS
            if CONFIG.enforce_window_before_scan:
                # This does fast checks first and only enforces if something is wrong.
                # Safe to call before every scan.
                st = ensure_window(self.window_cfg, log_fn=self._log)
                if not st:
                    self._log("[scan] window not found, skipping scan")
                    return

            # Setup capture region and capture screenshot
            wl, wt, wr, wb = st.win_rect
            w = wr - wl
            h = wb - wt

            pil_img = grab_rect_pil(wl, wt, w, h)

            # Convert PIL screenshot (RGB) -> OpenCV frame (BGR) once per scan
            frame_rgb = np.array(pil_img)
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            
            # OCR -> hits
            hits = ocr_image_to_hits(pil_img, conf_threshold=int(self.conf_threshold.get()))

            # Run detectors (choose which ones you care about for now)
            # run all detectors in the registry
            detector_names = list(CONFIG.detectors.keys())
            """
            detector_names = [
                "AUTO_RED_ICON",
                "AUTO_GREEN_ICON",
                "END_RUN_TEXT",
                "AUTO_TEXT",
                "END_RUN_BUTTON",
            ]"""

            # For state_machine detection to determine state, we want to run all detectors fresh every scan (no cache).
            results = run_detectors(
                detector_names=detector_names,
                hits=hits,
                frame_bgr=frame_bgr,
                bank=self.templates,
                detectors_dict=CONFIG.detectors,
            )

            # 4) Build signals from detector results (for backward compatibility or custom logic)
            signals = {
                "has_auto_red": results["AUTO_RED_ICON"].found,
                "has_auto_green": results["AUTO_GREEN_ICON"].found,
                "has_end_run": results["END_RUN_BUTTON"].found,
                "has_to_lobby": results["TO_LOBBY_BUTTON"].found,
                "has_switch_fish": results["SWITCH_FISH_ICON"].found,
                "has_leave": results["LEAVE_BUTTON"].found,
                "has_disconnected": results["DISCONNECTED_ICON"].found,
                "has_home_screen": results["HOME_SCREEN_ICON"].found,
            }

            # 5) Resolve state from detector results using state machine
            current_state = resolve_state(results)
            # self._log(f"[state] {current_state}")  # Disabled - shown in UI

            # Update UI state display
            self.current_state.set(current_state)

            # Track state duration
            if current_state != self.last_state:
                self.last_state = current_state
                self.state_start_time = time.time()

            state_duration = time.time() - self.state_start_time

            # 6) Take actions based on state
            # State-based action handler
            if current_state == states.STATE_DEAD:
                # Dead state - click center of to_lobby button
                if results["TO_LOBBY_BUTTON"].found and results["TO_LOBBY_BUTTON"].bbox:
                    center = bbox_center(results["TO_LOBBY_BUTTON"].bbox)
                    self._log(f"[action] DEAD detected - clicking to_lobby at {center}")
                    click_point(st.win_rect, center, clicks=1)

            elif current_state == states.STATE_AUTO_STOPPED:
                # Auto has stopped - click AUTO_BUTTON once to restart it
                self._log(f"[action] AUTO_STOPPED detected - clicking AUTO_BUTTON to restart")
                click_point(st.win_rect, CLICK_POINTS["AUTO_BUTTON"], clicks=1)

            elif current_state == states.STATE_IN_RUN:
                current_time = time.time()
                # Check if timer has elapsed (convert ms to seconds)
                timer_interval_s = self.click_timer_ms.get() / 1000.0

                if self.last_click_time == 0:
                    # First time in IN_RUN state, click immediately
                    click_point(st.win_rect, CLICK_POINTS["AUTO_BUTTON"], clicks=2, delay_ms=self.double_click_delay_ms.get())
                    self.last_click_time = current_time
                elif (current_time - self.last_click_time) >= timer_interval_s:
                    # Timer has elapsed, run click routine
                    time_since_last = current_time - self.last_click_time
                    click_point(st.win_rect, CLICK_POINTS["AUTO_BUTTON"], clicks=2, delay_ms=self.double_click_delay_ms.get())
                    # Reset timer
                    self.last_click_time = current_time
                """ else:
                    # Log the timer countdown occasionally (every 10 seconds worth of scans)
                    time_remaining = timer_interval_s - (current_time - self.last_click_time)
                    if int(current_time - self.last_click_time) % 10 < (self.refresh_ms.get() / 1000.0):
                        self._log(f"[click] IN_RUN - Next click in {time_remaining:.1f}s") """

            elif current_state == states.STATE_DISCONNECTED:
                # Disconnected - click the center of the disconnected icon to reconnect
                if results["DISCONNECTED_ICON"].found and results["DISCONNECTED_ICON"].bbox:
                    center = bbox_center(results["DISCONNECTED_ICON"].bbox)
                    self._log(f"[action] DISCONNECTED detected - clicking center of disconnected icon at {center}")
                    click_point(st.win_rect, center, clicks=1)

            elif current_state == states.STATE_HOME_SCREEN:
                # Home screen - click the center of the fish menu icon
                if results["HOME_SCREEN_ICON"].found and results["HOME_SCREEN_ICON"].bbox:
                    center = bbox_center(results["HOME_SCREEN_GAME_ICON"].bbox)
                    self._log(f"[action] HOME_SCREEN detected - clicking fish menu at {center}")
                    click_point(st.win_rect, center, clicks=1)

            elif current_state == states.STATE_FISH_MENU:
                # Fish menu screen - behavior depends on server type
                if self.public_server.get():
                    # Public server: click quick join button
                    if results["QUICK_JOIN_ICON"].found and results["QUICK_JOIN_ICON"].bbox:
                        center = bbox_center(results["QUICK_JOIN_ICON"].bbox)
                        self._log(f"[action] FISH_MENU detected (public) - clicking quick join at {center}")
                        click_point(st.win_rect, center, clicks=1)
                elif self.private_server.get():
                    # Private server: scroll down to find servers button
                    self._log(f"[action] FISH_MENU detected (private) - scrolling down")
                    # Scroll in the center of the window
                    center_x = (st.win_rect[2] - st.win_rect[0]) // 2
                    center_y = (st.win_rect[3] - st.win_rect[1]) // 2
                    scroll_view(st.win_rect, (center_x, center_y), direction="down", clicks=3)

            elif current_state == states.STATE_FISH_MENU_SCROLLED_DOWN:
                # Fish menu scrolled down - behavior depends on server type
                if self.public_server.get():
                    # Public server: scroll back up
                    self._log(f"[action] FISH_MENU_SCROLLED_DOWN detected (public) - scrolling up")
                    center_x = (st.win_rect[2] - st.win_rect[0]) // 2
                    center_y = (st.win_rect[3] - st.win_rect[1]) // 2
                    scroll_view(st.win_rect, (center_x, center_y), direction="up", clicks=3)
                elif self.private_server.get():
                    # Private server: look for servers_button
                    if results["SERVERS_BUTTON"].found and results["SERVERS_BUTTON"].bbox:
                        center = bbox_center(results["SERVERS_BUTTON"].bbox)
                        self._log(f"[action] FISH_MENU_SCROLLED_DOWN detected (private) - clicking servers_button at {center}")
                        click_point(st.win_rect, center, clicks=1)
                    else:
                        # If not found, scroll down more
                        self._log(f"[action] FISH_MENU_SCROLLED_DOWN detected (private) - servers_button not found, scrolling down")
                        center_x = (st.win_rect[2] - st.win_rect[0]) // 2
                        center_y = (st.win_rect[3] - st.win_rect[1]) // 2
                        scroll_view(st.win_rect, (center_x, center_y), direction="down", clicks=3)

            elif current_state == states.STATE_STUCK_IN_LOBBY:
                # Stuck in lobby - only take action after 15 seconds
                if state_duration >= 15.0:
                    if results["MENU_ICON"].found and results["MENU_ICON"].bbox:
                        center = bbox_center(results["MENU_ICON"].bbox)
                        self._log(f"[action] STUCK_IN_LOBBY for {state_duration:.1f}s - clicking menu icon at {center}")
                        click_point(st.win_rect, center, clicks=1)
                else:
                    # Log countdown occasionally (every 5 seconds)
                    if int(state_duration) % 5 < (self.refresh_ms.get() / 1000.0):
                        remaining = 15.0 - state_duration
                        self._log(f"[action] STUCK_IN_LOBBY - waiting {remaining:.1f}s before action")

            elif current_state == states.STATE_MENU:
                # Menu screen - click the center of the leave button
                if results["LEAVE_BUTTON"].found and results["LEAVE_BUTTON"].bbox:
                    center = bbox_center(results["LEAVE_BUTTON"].bbox)
                    self._log(f"[action] MENU detected - clicking leave button at {center}")
                    click_point(st.win_rect, center, clicks=1)

            elif current_state == states.STATE_LEAVE_MENU:
                # Leave menu confirmation - click the center of the leave confirm button
                if results["LEAVE_BUTTON_CONFIRM"].found and results["LEAVE_BUTTON_CONFIRM"].bbox:
                    center = bbox_center(results["LEAVE_BUTTON_CONFIRM"].bbox)
                    self._log(f"[action] LEAVE_MENU detected - clicking leave confirm at {center}")
                    click_point(st.win_rect, center, clicks=1)

            elif current_state == states.STATE_PRIVATE_SERVERS_MENU:
                # Private servers menu - click center and 10px up from bottom
                window_width = st.win_rect[2] - st.win_rect[0]
                window_height = st.win_rect[3] - st.win_rect[1]
                center_x = window_width // 2
                click_y = window_height - 10  # 10px up from bottom
                click_pos = (center_x, click_y)
                self._log(f"[action] PRIVATE_SERVERS_MENU detected - clicking at {click_pos}")
                click_point(st.win_rect, click_pos, clicks=1)

            else:
                # Reset timer when not in IN_RUN state
                if self.last_click_time != 0:
                    self._log(f"[click] State changed from IN_RUN to {current_state}, resetting timer")
                self.last_click_time = 0

            dt_ms = int((time.time() - t0) * 1000)


            # =========================
            # DEBUG OUTPUT
            # Safe to comment out later
            # =========================

            # Annotated Screen Shot Save
            if debugging.DEBUG_SAVE_SCREENSHOTS and (debugging.DEBUG_SAVE_EVERY_SCAN or (not self.is_running.get())):
                try:
                    annotated = debugging.draw_ocr_boxes(pil_img, hits, max_boxes=None)
                    saved_path = debugging.save_debug_screenshot(annotated, subfolder="debug_shots", prefix="annotated")
                    self._log(f"[debug] saved annotated screenshot: {saved_path}")
                except Exception as e:
                    self._log(f"[debug] annotated save FAILED: {type(e).__name__}: {e}")

            # Print detector results
            # Option A: keep your loop (works fine)
            # Option B: use helper so main.py stays clean
            
            # debugging.log_detectors(results, self._log, filter_text=self.debug_filter.get())

            # Save raw screenshot if enabled
            try:
                if debugging.DEBUG_SAVE_SCREENSHOTS and (debugging.DEBUG_SAVE_EVERY_SCAN or (not self.is_running.get())):
                    saved_path = debugging.save_debug_screenshot(pil_img, subfolder="debug_shots", prefix="desktop")
                    self._log(f"[debug] saved screenshot: {saved_path}")
            except Exception as e:
                self._log(f"[debug] screenshot save FAILED: {type(e).__name__}: {e}")

            # =========================
            # DEBUG OUTPUT END
            # Safe to comment out later
            # =========================

        except Exception as e:
            self._log(f"[error] {type(e).__name__}: {e}")


def main():
    """
    Main entry point.
    Validates configuration and starts the GUI.
    """
    # Fix #3: Validate that all template files exist
    missing_files = validate_template_files(CONFIG)
    if missing_files:
        print("\n" + "=" * 60)
        print("ERROR: Missing template files!")
        print("=" * 60)
        for missing in missing_files:
            print(f"  - {missing}")
        print("=" * 60)
        print("\nPlease ensure all template files exist before starting.")
        print("Check your config.yaml and assets folder.\n")
        import sys
        sys.exit(1)

    print(f"[startup] All {len(CONFIG.template_paths_map)} template groups validated")
    print("[startup] Starting GUI...\n")

    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
