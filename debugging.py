"""
debugging.py

All debug related helpers live here so main.py stays readable.

What this module provides:
- toggles for saving screenshots
- save_debug_screenshot: save PIL images into a project folder subdir
- draw_ocr_boxes: draw OCR bounding boxes + labels onto an image copy
- log_detectors: optional helper to print detector results in a consistent way

This module intentionally has no Tkinter code.
It only deals with images and formatting text for logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Any, Dict
from PIL import ImageDraw


# =========================
# DEBUG SETTINGS
# =========================

DEBUG_SAVE_SCREENSHOTS = True                 # Set to False to disable all screenshot saving.
DEBUG_SCREENSHOT_DIRNAME = "debug_shots"      # folder inside your project
# If True, save every scan while scanning continuously.
# If False, save only on Single Scan (or when not running).
DEBUG_SAVE_EVERY_SCAN = False


def project_dir() -> Path:
    """
    Returns the folder where this debugging.py file lives.
    Since debugging.py sits next to main.py, this is your project folder.
    """
    return Path(__file__).resolve().parent


def save_debug_screenshot(pil_img, subfolder: str = DEBUG_SCREENSHOT_DIRNAME, prefix: str = "desktop") -> str:
    """
    Save a PIL image to: <project>/<subfolder>/<prefix>_<timestamp>.png

    Returns:
        The full saved path as a string.

    Notes:
        - Uses mkdir(parents=True, exist_ok=True) so the folder is auto created.
        - Raises exception if saving fails, caller should catch and log.
    """
    base_dir = project_dir() / subfolder
    base_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out_path = base_dir / f"{prefix}_{ts}.png"

    pil_img.save(str(out_path), format="PNG")
    return str(out_path)


def draw_ocr_boxes(pil_img, hits, max_boxes: Optional[int] = None):
    """
    Return a COPY of the image with OCR bounding boxes drawn on top.

    Args:
        pil_img: PIL.Image
        hits: list of OcrHit like objects (must have .text .conf .bbox)
              bbox must be (x, y, w, h)
        max_boxes: If None, draw all. If int, draw only top N by confidence.

    Why this exists:
        OCR can be confusing. Seeing what Tesseract thinks it sees is huge for learning.

    Notes:
        - We avoid importing your OcrHit type here to prevent circular imports.
        - We just rely on attributes at runtime.
    """

    out = pil_img.copy()
    draw = ImageDraw.Draw(out)

    # Sort so the best confidence boxes are drawn first
    hits_sorted = sorted(hits, key=lambda h: h.conf, reverse=True)
    if max_boxes is not None:
        hits_sorted = hits_sorted[:max_boxes]

    for h in hits_sorted:
        x, y, w, hh = h.bbox
        x2, y2 = x + w, y + hh

        # Draw rectangle
        draw.rectangle([x, y, x2, y2], outline="yellow", width=2)

        # Draw label
        label = f"{h.text} ({h.conf})"
        text_y = y - 14 if y - 14 > 0 else y + 2
        draw.text((x, text_y), label, fill="yellow")

    return out


def log_detectors(results: Dict[str, Any], log_fn, filter_text: str = "") -> None:
    """
    Print detector results in a consistent way.

    Args:
        results: dict detector_name -> DetectResult like object
        log_fn: function that accepts a string, usually self._log
        filter_text: optional substring filter, case-insensitive

    This is optional, but it keeps main.py clean.
    """
    flt = (filter_text or "").strip().lower()

    for name, r in results.items():
        if flt:
            hay = (name + " " + (getattr(r, "text", "") or "")).lower()
            if flt not in hay:
                continue

        log_fn(
            f"  DETECT: {name} kind={getattr(r, 'kind', None)} found={getattr(r, 'found', None)} "
            f"bbox={getattr(r, 'bbox', None)} text='{getattr(r, 'text', None)}' conf={getattr(r, 'conf', None)}"
        )
