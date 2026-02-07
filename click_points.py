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
    "START_RUN": (1050, 650),
    "CONFIRM_OK": (640, 500),
    "CLOSE_POPUP_X": (1230, 40),

    # Routine navigation examples
    "DEATH_CONTINUE": (640, 620),
    "DEATH_RETRY": (640, 680),

    # Click routine example
    "AUTO_BUTTON": (1150, 640),
}
