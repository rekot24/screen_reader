"""
clicker.py - Win32 API implementation

Uses Windows API SendInput for more reliable game interaction.
This is the most compatible method for games like Roblox.
"""

from typing import Tuple
import time
import ctypes
from ctypes import windll, Structure, c_long, c_ulong, sizeof, Union, pointer

Point = Tuple[int, int]

# Win32 API constants
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

# Structures for SendInput
class MOUSEINPUT(Structure):
    _fields_ = [
        ("dx", c_long),
        ("dy", c_long),
        ("mouseData", c_ulong),
        ("dwFlags", c_ulong),
        ("time", c_ulong),
        ("dwExtraInfo", ctypes.POINTER(c_ulong))
    ]

class INPUT_UNION(Union):
    _fields_ = [("mi", MOUSEINPUT)]

class INPUT(Structure):
    _fields_ = [
        ("type", c_ulong),
        ("union", INPUT_UNION)
    ]

def window_to_screen(win_rect: Tuple[int, int, int, int], pt: Point) -> Point:
    """Convert a window relative point into a screen coordinate."""
    wl, wt, wr, wb = win_rect
    x, y = pt
    return (wl + x, wt + y)

def move_mouse_absolute(x: int, y: int):
    """
    Move mouse using Win32 API SendInput.
    Coordinates are in screen pixels.
    """
    # Get screen dimensions
    screen_width = windll.user32.GetSystemMetrics(0)
    screen_height = windll.user32.GetSystemMetrics(1)

    # Convert to absolute coordinates (0-65535 range)
    abs_x = int(x * 65535 / screen_width)
    abs_y = int(y * 65535 / screen_height)

    # Create input structure
    inp = INPUT()
    inp.type = 0  # INPUT_MOUSE
    inp.union.mi = MOUSEINPUT()
    inp.union.mi.dx = abs_x
    inp.union.mi.dy = abs_y
    inp.union.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE

    # Send the input
    windll.user32.SendInput(1, pointer(inp), sizeof(INPUT))

def click_mouse():
    """Send a mouse click using Win32 API."""
    # Mouse down
    inp_down = INPUT()
    inp_down.type = 0
    inp_down.union.mi = MOUSEINPUT()
    inp_down.union.mi.dwFlags = MOUSEEVENTF_LEFTDOWN

    # Mouse up
    inp_up = INPUT()
    inp_up.type = 0
    inp_up.union.mi = MOUSEINPUT()
    inp_up.union.mi.dwFlags = MOUSEEVENTF_LEFTUP

    # Send both events
    windll.user32.SendInput(1, pointer(inp_down), sizeof(INPUT))
    time.sleep(0.01)
    windll.user32.SendInput(1, pointer(inp_up), sizeof(INPUT))

def click_point(
        win_rect,
        pt: Point,
        clicks: int = 1,
        delay_ms: int | None = None,
        wiggle: bool = True):
    """
    Click using Win32 API - most reliable for games.

    Args:
        win_rect: (left, top, right, bottom) of window in screen coords
        pt: (x, y) point relative to the window
        clicks: Number of clicks
        delay_ms: Delay between clicks in milliseconds
        wiggle: Whether to wiggle mouse to trigger hover detection
    """
    sx, sy = window_to_screen(win_rect, pt)

    # Move to target position
    move_mouse_absolute(sx, sy)
    time.sleep(0.05)

    if wiggle:
        # Small wiggle to trigger game detection
        move_mouse_absolute(sx + 2, sy + 2)
        time.sleep(0.02)
        move_mouse_absolute(sx - 1, sy - 1)
        time.sleep(0.02)
        move_mouse_absolute(sx, sy)
        time.sleep(0.05)

    # Perform clicks
    delay_s = (delay_ms / 1000.0) if delay_ms else 0.05

    for i in range(clicks):
        click_mouse()
        if i < clicks - 1:  # Don't delay after last click
            time.sleep(delay_s)
