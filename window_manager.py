"""
window_manager.py

Purpose
This module provides window discovery and enforcement for a target app window on Windows.

Why this exists
Your automation becomes simpler and faster if the game window is forced into a consistent state:
- windowed mode (not spanning monitors)
- always on a known monitor
- always the same client size (1280x720 by default)

If the window is always the same size and always on the same monitor,
then you can safely use fixed coordinates relative to the window.

This module is designed for learning:
- many comments
- small functions with clear responsibilities
- best effort behavior (games can behave differently)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Tuple

import mss  # used to read monitor geometry in the same coordinate system as screen capture

import win32gui
import win32con
import win32api

# Optional but very helpful for toggling windowed mode (Alt+Enter)
# If you do not want it, you can remove it and skip the toggle function.
import pyautogui


# ----------------------------
# Data models (simple and clear)
# ----------------------------

@dataclass
class WindowStatus:
    """
    A snapshot describing whether the target window is in the desired state.
    This is useful for debug logs and for deciding whether to enforce changes.
    """
    hwnd: int
    title: str

    # Current window position in screen coordinates
    win_rect: Tuple[int, int, int, int]  # (left, top, right, bottom)

    # Current client area size (the inside drawable area)
    client_size: Tuple[int, int]  # (width, height)

    # Where Windows says focus currently is
    is_foreground: bool

    # Monitor checks
    is_on_target_monitor: bool
    looks_spanning_monitors: bool

    # Mode heuristic
    looks_fullscreen_like: bool


@dataclass
class EnforceConfig:
    """
    All settings that define the desired window state.

    monitor_index uses MSS indexing:
    1 = primary monitor
    2 = second monitor
    0 = all monitors (virtual desktop) [we do not use 0 here]
    """
    title_contains: str

    monitor_index: int = 1
    target_client_w: int = 1280
    target_client_h: int = 720

    # Where to position the window within the target monitor
    # This is not a click coordinate, just where the window should sit.
    pad_left: int = 40
    pad_top: int = 40

    # Behavior controls
    try_alt_enter_to_escape_fullscreen: bool = True

    # Tolerances
    # Many apps have a 1 to 2 pixel drift depending on borders and DPI
    size_tolerance_px: int = 2

    # Sleep timing
    # Tiny sleeps help Windows repaint and apply the move/resize reliably.
    post_activate_sleep_s: float = 0.05
    post_move_sleep_s: float = 0.05
    post_resize_sleep_s: float = 0.10
    post_alt_enter_sleep_s: float = 0.25


# ----------------------------
# Window finding
# ----------------------------

def find_window_by_title_contains(title_contains: str) -> Optional[int]:
    """
    Find the first visible top-level window whose title contains the given substring.

    Many games have dynamic titles. Using "contains" is often more reliable than exact match.
    """
    title_contains_lower = title_contains.lower().strip()
    found_hwnd: Optional[int] = None

    def enum_cb(hwnd, _):
        nonlocal found_hwnd
        if found_hwnd is not None:
            return  # already found one

        if not win32gui.IsWindowVisible(hwnd):
            return

        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return

        if title_contains_lower in title.lower():
            found_hwnd = hwnd

    win32gui.EnumWindows(enum_cb, None)
    return found_hwnd


# ----------------------------
# Monitor geometry helpers
# ----------------------------

def get_monitor_rect_mss(monitor_index: int) -> Tuple[int, int, int, int]:
    """
    Return the monitor rectangle (left, top, right, bottom) using MSS.

    Why MSS:
    Your screen capture code uses MSS coordinates.
    If we compute monitor rectangles from MSS, we are speaking the same coordinate language.

    MSS monitor dict:
    - left, top, width, height
    """
    with mss.mss() as sct:
        mon = sct.monitors[monitor_index]
        l = int(mon["left"])
        t = int(mon["top"])
        r = l + int(mon["width"])
        b = t + int(mon["height"])
        return (l, t, r, b)


def rect_center(rect: Tuple[int, int, int, int]) -> Tuple[int, int]:
    l, t, r, b = rect
    return (l + (r - l) // 2, t + (b - t) // 2)


def point_in_rect(x: int, y: int, rect: Tuple[int, int, int, int]) -> bool:
    l, t, r, b = rect
    return (l <= x < r) and (t <= y < b)


def rect_area(rect: Tuple[int, int, int, int]) -> int:
    l, t, r, b = rect
    return max(0, r - l) * max(0, b - t)


def rect_intersect(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    """
    Intersection of rectangles a and b.
    Returns (0,0,0,0) if there is no overlap.
    """
    al, at, ar, ab = a
    bl, bt, br, bb = b
    l = max(al, bl)
    t = max(at, bt)
    r = min(ar, br)
    btm = min(ab, bb)
    if r <= l or btm <= t:
        return (0, 0, 0, 0)
    return (l, t, r, btm)


def window_is_on_monitor(hwnd: int, monitor_rect: Tuple[int, int, int, int]) -> bool:
    """
    Decide if a window is "on" a monitor by checking where its center point lands.
    This is simple and works well for your use case.
    """
    win_rect = win32gui.GetWindowRect(hwnd)
    cx, cy = rect_center(win_rect)
    return point_in_rect(cx, cy, monitor_rect)


def window_looks_spanning_monitors(hwnd: int) -> bool:
    """
    Heuristic check: does the window overlap multiple monitors significantly?

    Why heuristic:
    Windows does not always tell you "spanning" directly.
    We approximate using overlap areas with each monitor rect.

    If overlap on 2nd best monitor is large relative to best, call it spanning.
    """
    win_rect = win32gui.GetWindowRect(hwnd)

    monitors = []
    for hmon, hdc, rect in win32api.EnumDisplayMonitors():
        monitors.append(rect)

    overlaps = [rect_area(rect_intersect(win_rect, m)) for m in monitors]
    overlaps_sorted = sorted(overlaps, reverse=True)

    if len(overlaps_sorted) < 2:
        return False

    best = overlaps_sorted[0]
    second = overlaps_sorted[1]

    # If second overlap is more than 15 percent of best overlap, likely spanning
    if best > 0 and second > 0.15 * best:
        return True

    return False


# ----------------------------
# Window mode and activation
# ----------------------------

def activate_window(hwnd: int) -> bool:
    """
    Bring window to foreground (active).

    Windows can be restrictive about stealing focus.
    This is best-effort and usually works for the same user session.

    Returns True if it ended up as foreground window.
    """
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    except Exception:
        pass

    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        # Fallback: sometimes attaching thread input helps
        try:
            fg = win32gui.GetForegroundWindow()
            cur_tid = win32api.GetCurrentThreadId()
            fg_tid = win32gui.GetWindowThreadProcessId(fg)[0]
            win32api.AttachThreadInput(cur_tid, fg_tid, True)
            win32gui.SetForegroundWindow(hwnd)
            win32api.AttachThreadInput(cur_tid, fg_tid, False)
        except Exception:
            pass

    return win32gui.GetForegroundWindow() == hwnd


def looks_fullscreen_like(hwnd: int, monitor_rect: Tuple[int, int, int, int]) -> bool:
    """
    Heuristic check for fullscreen or borderless fullscreen.

    Many games in borderless fullscreen behave like a giant window that matches monitor size.
    If the window occupies most of the monitor, we treat it as fullscreen-like.

    This is not perfect but it is very effective in practice.
    """
    ml, mt, mr, mb = monitor_rect
    mw = mr - ml
    mh = mb - mt

    wl, wt, wr, wb = win32gui.GetWindowRect(hwnd)
    ww = wr - wl
    wh = wb - wt

    if mw <= 0 or mh <= 0:
        return False

    # How much of the monitor does the window cover
    cover_w = ww / mw
    cover_h = wh / mh

    return (cover_w > 0.95) and (cover_h > 0.95)


def try_alt_enter_toggle(hwnd: int, cfg: EnforceConfig, log_fn) -> None:
    """
    Many games use Alt+Enter to toggle fullscreen <-> windowed mode.

    This only works if the window is active, so we activate first.
    """
    if not cfg.try_alt_enter_to_escape_fullscreen:
        return

    ok = activate_window(hwnd)
    log_fn(f"[window] activate before Alt+Enter ok={ok}")

    time.sleep(0.10)

    try:
        pyautogui.hotkey("alt", "enter")
        log_fn("[window] sent Alt+Enter toggle")
    except Exception as e:
        log_fn(f"[window] Alt+Enter failed: {type(e).__name__}: {e}")

    time.sleep(cfg.post_alt_enter_sleep_s)


# ----------------------------
# Size enforcement
# ----------------------------

def get_client_size(hwnd: int) -> Tuple[int, int]:
    """
    Client size is the inside drawable area, excluding borders and titlebar.
    This is what matters most if you want stable UI positions.
    """
    l, t, r, b = win32gui.GetClientRect(hwnd)
    return (r - l, b - t)


def resize_window_to_target_client(hwnd: int, target_client_w: int, target_client_h: int, x: int, y: int, log_fn) -> None:
    """
    Resize the OUTER window so the CLIENT area becomes (target_client_w, target_client_h).

    Why not just SetWindowPos with 1280x720:
    That would set the OUTER size, and the client area would be smaller due to borders.

    AdjustWindowRectEx lets us compute required outer size based on current window style.
    """
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)

    desired_client_rect = (0, 0, target_client_w, target_client_h)

    try:
        # Returns a rect that includes border and titlebar offsets.
        adj = win32gui.AdjustWindowRectEx(desired_client_rect, style, False, ex_style)
        outer_w = adj[2] - adj[0]
        outer_h = adj[3] - adj[1]
    except Exception:
        # Fallback: use client size as outer size (not perfect, but better than nothing)
        outer_w = target_client_w
        outer_h = target_client_h

    win32gui.SetWindowPos(
        hwnd,
        None,
        int(x), int(y),
        int(outer_w), int(outer_h),
        win32con.SWP_NOZORDER | win32con.SWP_NOOWNERZORDER | win32con.SWP_SHOWWINDOW
    )

    log_fn(f"[window] resized outer to {outer_w}x{outer_h} to aim for client {target_client_w}x{target_client_h}")


# ----------------------------
# Status check and enforcement
# ----------------------------

def get_window_status(hwnd: int, cfg: EnforceConfig) -> WindowStatus:
    """
    Build a structured status object describing current window state.
    This makes debugging and learning easier than juggling many variables.
    """
    title = win32gui.GetWindowText(hwnd).strip()
    win_rect = win32gui.GetWindowRect(hwnd)
    client = get_client_size(hwnd)

    mon_rect = get_monitor_rect_mss(cfg.monitor_index)

    fg = win32gui.GetForegroundWindow()
    is_fg = (fg == hwnd)

    on_mon = window_is_on_monitor(hwnd, mon_rect)
    spanning = window_looks_spanning_monitors(hwnd)
    full_like = looks_fullscreen_like(hwnd, mon_rect)

    return WindowStatus(
        hwnd=hwnd,
        title=title,
        win_rect=win_rect,
        client_size=client,
        is_foreground=is_fg,
        is_on_target_monitor=on_mon,
        looks_spanning_monitors=spanning,
        looks_fullscreen_like=full_like,
    )


def ensure_window(cfg: EnforceConfig, log_fn) -> Optional[WindowStatus]:
    """
    The main entry point you will call from main.py before each scan.

    What it does:
    - find the target window
    - check its current status
    - if anything is wrong, enforce the desired configuration
    - return final status

    It is designed to be safe to call often.
    Most calls will do almost nothing once the window is already correct.
    """
    hwnd = find_window_by_title_contains(cfg.title_contains)
    if not hwnd:
        log_fn(f"[window] NOT FOUND title contains: '{cfg.title_contains}'")
        return None

    # First snapshot
    st = get_window_status(hwnd, cfg)

    # 1) Activate if needed
    if not st.is_foreground:
        ok = activate_window(hwnd)
        log_fn(f"[window] activated ok={ok}")
        time.sleep(cfg.post_activate_sleep_s)

    # Refresh status after activation
    st = get_window_status(hwnd, cfg)

    # 2) If it looks fullscreen or borderless fullscreen, try toggling to windowed mode
    if st.looks_fullscreen_like:
        log_fn("[window] looks fullscreen-like, attempting to toggle to windowed mode")
        try_alt_enter_toggle(hwnd, cfg, log_fn)

    # Refresh status after possible mode toggle
    st = get_window_status(hwnd, cfg)

    # 3) Ensure on target monitor (by center point)
    if not st.is_on_target_monitor or st.looks_spanning_monitors:
        mon_rect = get_monitor_rect_mss(cfg.monitor_index)
        ml, mt, mr, mb = mon_rect

        # We position it near top-left of the desired monitor with padding.
        x = ml + cfg.pad_left
        y = mt + cfg.pad_top

        # Move only (keep current size) using SWP_NOSIZE
        win32gui.SetWindowPos(
            hwnd,
            None,
            int(x), int(y),
            0, 0,
            win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOOWNERZORDER | win32con.SWP_SHOWWINDOW
        )
        log_fn(f"[window] moved to monitor {cfg.monitor_index} at ({x},{y})")
        time.sleep(cfg.post_move_sleep_s)

    # Refresh status after move
    st = get_window_status(hwnd, cfg)

    # 4) Ensure client size matches target
    cw, ch = st.client_size
    tw, th = cfg.target_client_w, cfg.target_client_h
    tol = cfg.size_tolerance_px

    size_ok = (abs(cw - tw) <= tol) and (abs(ch - th) <= tol)

    if not size_ok:
        mon_rect = get_monitor_rect_mss(cfg.monitor_index)
        ml, mt, mr, mb = mon_rect
        x = ml + cfg.pad_left
        y = mt + cfg.pad_top

        resize_window_to_target_client(hwnd, tw, th, x, y, log_fn)
        time.sleep(cfg.post_resize_sleep_s)

    # Final status after enforcement attempts
    st = get_window_status(hwnd, cfg)

    # Log final summary in a readable way
    log_fn(
        f"[window] final title='{st.title}' "
        f"client={st.client_size[0]}x{st.client_size[1]} "
        f"fg={st.is_foreground} "
        f"on_mon={st.is_on_target_monitor} "
        f"spanning={st.looks_spanning_monitors} "
        f"fullscreen_like={st.looks_fullscreen_like}"
    )

    return st
