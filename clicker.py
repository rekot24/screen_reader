"""
clicker.py

Converts window relative points into absolute screen coordinates,
then uses pyautogui to click.

Important:
We need the window top-left in screen coordinates.
That comes from WindowStatus.win_rect returned by ensure_window().
"""

from typing import Tuple
import pyautogui

Point = Tuple[int, int]

def window_to_screen(win_rect: Tuple[int, int, int, int], pt: Point) -> Point:
    """
    Convert a window relative point into a screen coordinate.

    win_rect: (left, top, right, bottom) in screen coords
    pt: (x,y) inside the window capture
    """
    wl, wt, wr, wb = win_rect
    x, y = pt
    return (wl + x, wt + y)

def click_point(win_rect, pt: Point, clicks: int = 1, interval_s: float = 0.0):
    """
    Click at a window relative point.
    """
    sx, sy = window_to_screen(win_rect, pt)

    # move the mouse first, then click.
    pyautogui.moveTo(sx, sy)
    pyautogui.click(x=sx, y=sy, clicks=clicks, interval=interval_s)
