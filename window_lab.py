import time
import tkinter as tk
from tkinter import ttk, messagebox

import pyautogui
import win32gui
import win32con
import win32api

# -------------- helpers --------------

def list_visible_windows():
    """Return list of (hwnd, title) for visible top-level windows with non-empty titles."""
    items = []

    def enum_cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return
        # Skip some common non-app windows if you want, but keep it simple for now
        items.append((hwnd, title))

    win32gui.EnumWindows(enum_cb, None)
    # Sort alphabetically for easier selection
    items.sort(key=lambda t: t[1].lower())
    return items


def get_window_rect(hwnd):
    """Return (left, top, right, bottom) in screen coords."""
    return win32gui.GetWindowRect(hwnd)


def bring_to_front(hwnd):
    """
    Bring window to foreground. Windows can be picky; this is a best-effort sequence.
    """
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        # Fallback: attach thread input to bypass foreground restrictions sometimes
        try:
            fg = win32gui.GetForegroundWindow()
            cur_tid = win32api.GetCurrentThreadId()
            fg_tid = win32gui.GetWindowThreadProcessId(fg)[0]
            win32api.AttachThreadInput(cur_tid, fg_tid, True)
            win32gui.SetForegroundWindow(hwnd)
            win32api.AttachThreadInput(cur_tid, fg_tid, False)
        except Exception:
            pass


def move_resize(hwnd, left, top, width, height):
    """
    Move + resize a window. This uses the full window rect, not strictly client area.
    """
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetWindowPos(
        hwnd,
        None,
        int(left),
        int(top),
        int(width),
        int(height),
        win32con.SWP_NOZORDER | win32con.SWP_SHOWWINDOW
    )


def get_monitors():
    """
    Returns list of monitor rects as dicts:
    [{'left':..., 'top':..., 'right':..., 'bottom':..., 'width':..., 'height':...}, ...]
    """
    mons = []
    for hmon, hdc, rect in win32api.EnumDisplayMonitors():
        l, t, r, b = rect
        mons.append({
            "left": l,
            "top": t,
            "right": r,
            "bottom": b,
            "width": r - l,
            "height": b - t,
        })
    return mons



def toggle_alt_enter():
    """
    Sends Alt+Enter to toggle windowed/fullscreen for many games.
    Must have the target window in the foreground.
    """
    pyautogui.keyDown("alt")
    pyautogui.press("enter")
    pyautogui.keyUp("alt")


# -------------- tiny UI --------------

class WindowLab(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Window Lab (Win32 + Alt+Enter Test)")
        self.geometry("780x520")

        self.windows = []
        self.selected_hwnd = None

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Button(top, text="Refresh Window List", command=self.refresh_windows).pack(side="left")
        ttk.Button(top, text="Use Selected", command=self.use_selected).pack(side="left", padx=(8, 0))

        self.combo = ttk.Combobox(top, width=80, state="readonly")
        self.combo.pack(side="left", padx=(10, 0), fill="x", expand=True)

        actions = ttk.LabelFrame(self, text="Actions", padding=10)
        actions.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Button(actions, text="Bring To Front", command=self.do_front).grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text="Print Rect", command=self.do_rect).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(actions, text="Alt+Enter Toggle", command=self.do_alt_enter).grid(row=0, column=2, sticky="w", padx=(8, 0))

        ttk.Separator(actions, orient="horizontal").grid(row=1, column=0, columnspan=6, sticky="ew", pady=10)

        ttk.Label(actions, text="Move/Resize:").grid(row=2, column=0, sticky="w")

        self.monitors = get_monitors()
        mon_labels = [f"Monitor {i+1} ({m['width']}x{m['height']}, origin {m['left']},{m['top']})" for i, m in enumerate(self.monitors)]
        self.mon_combo = ttk.Combobox(actions, values=mon_labels, state="readonly", width=55)
        self.mon_combo.grid(row=2, column=1, columnspan=2, sticky="w", padx=(8, 0))
        if mon_labels:
            self.mon_combo.current(0)

        ttk.Button(actions, text="Move to Monitor (Max-ish)", command=self.do_move_monitor).grid(row=2, column=3, sticky="w", padx=(8, 0))

        ttk.Label(actions, text="Custom W/H:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.w_var = tk.IntVar(value=2560)
        self.h_var = tk.IntVar(value=1440)
        ttk.Spinbox(actions, from_=400, to=6000, increment=50, textvariable=self.w_var, width=8).grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Spinbox(actions, from_=300, to=4000, increment=50, textvariable=self.h_var, width=8).grid(row=3, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Button(actions, text="Apply Size (keep top-left)", command=self.do_apply_size).grid(row=3, column=3, sticky="w", padx=(8, 0), pady=(8, 0))

        dbg = ttk.LabelFrame(self, text="Debug Log", padding=10)
        dbg.pack(fill="both", expand=True, padx=10, pady=10)

        self.log = tk.Text(dbg, height=16, wrap="word")
        self.log.pack(fill="both", expand=True)

        self.refresh_windows()

    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.log.insert("end", f"[{ts}] {msg}\n")
        self.log.see("end")

    def refresh_windows(self):
        self.windows = list_visible_windows()
        labels = [title for _, title in self.windows]
        self.combo["values"] = labels
        if labels:
            self.combo.current(0)
        self._log(f"Found {len(labels)} visible windows.")

    def use_selected(self):
        idx = self.combo.current()
        if idx < 0 or idx >= len(self.windows):
            messagebox.showerror("Select a window", "Pick a window from the list first.")
            return
        hwnd, title = self.windows[idx]
        self.selected_hwnd = hwnd
        self._log(f"Selected: {title} (hwnd={hwnd})")

    def _require_hwnd(self):
        if not self.selected_hwnd:
            self.use_selected()
        if not self.selected_hwnd:
            raise RuntimeError("No window selected")

    def do_front(self):
        self._require_hwnd()
        bring_to_front(self.selected_hwnd)
        self._log("Bring to front requested.")

    def do_rect(self):
        self._require_hwnd()
        l, t, r, b = get_window_rect(self.selected_hwnd)
        self._log(f"Rect: left={l}, top={t}, right={r}, bottom={b}, w={r-l}, h={b-t}")

    def do_alt_enter(self):
        self._require_hwnd()
        bring_to_front(self.selected_hwnd)
        time.sleep(0.15)
        toggle_alt_enter()
        self._log("Sent Alt+Enter. (Window must support this toggle.)")

    def do_move_monitor(self):
        self._require_hwnd()
        idx = self.mon_combo.current()
        if idx < 0 or idx >= len(self.monitors):
            messagebox.showerror("Monitor", "No monitor selected.")
            return

        m = self.monitors[idx]
        # "Max-ish": keep a small inset so it doesn't fight taskbar or borders
        inset = 10
        left = m["left"] + inset
        top = m["top"] + inset
        width = m["width"] - inset * 2
        height = m["height"] - inset * 2

        move_resize(self.selected_hwnd, left, top, width, height)
        self._log(f"Moved/resized to {idx+1}: ({left},{top}) {width}x{height}")

    def do_apply_size(self):
        self._require_hwnd()
        l, t, r, b = get_window_rect(self.selected_hwnd)
        w = int(self.w_var.get())
        h = int(self.h_var.get())
        move_resize(self.selected_hwnd, l, t, w, h)
        self._log(f"Applied size {w}x{h} at top-left ({l},{t}).")


if __name__ == "__main__":
    # PyAutoGUI safety: slam mouse to top-left to abort if it goes nuts
    pyautogui.FAILSAFE = True
    WindowLab().mainloop()
