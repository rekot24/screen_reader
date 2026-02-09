"""
click_points.py

All click targets are expressed in WINDOW RELATIVE coordinates.
That means (0,0) is the top left of the game window client capture.

You can keep these stable if:
- window is always the same client size (1280x720)
- window is always positioned predictably
"""

from typing import Dict, Tuple

Point = Tuple[int, int]

# Name each click target like a button or UI element.
# Use placeholder values now, replace them as you measure.
CLICK_POINTS: Dict[str, Point] = {
    # Example placeholders
    "AUTO_BUTTON": (1202, 328),
    "DEATH_TO_LOBBY": (641, 409),
    "END_RUN_BUTTON": (1054, 667),
    "MENU_BUTTON": (46, 68),
    "MENU_LEAVE_BUTTON": (362, 614),
    "MENU_CONFIRM_BUTTON": (640, 500)
}
