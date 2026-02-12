"""
config_loader.py

Loads and validates configuration from config.yaml
"""

import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass


@dataclass
class Config:
    """Main configuration object"""

    # Paths
    app_dir: Path
    assets_dir: Path
    tesseract_exe_path: Optional[str]

    # Window config
    target_window_title: str
    activate_before_capture: bool
    enforce_window_before_scan: bool
    target_monitor_index: int
    target_client_w: int
    target_client_h: int
    window_exe_path: Optional[str]
    launch_if_not_found: bool
    wait_after_launch_s: float

    # Scan config
    default_refresh_ms: int
    min_refresh_ms: int
    max_refresh_ms: int
    refresh_step: int
    min_sleep_s: float

    # OCR config
    default_conf_threshold: int
    min_conf: int
    max_conf: int
    conf_step: int

    # Template config
    default_template_confidence: float
    template_timeout_s: float

    # Automation config
    pyautogui_failsafe: bool
    pyautogui_pause: float

    # Debug config
    debug_save_screenshots: bool
    debug_save_every_scan: bool
    debug_screenshot_subfolder: str
    debug_enable_ui: bool
    debug_window_print: bool

    # Detectors and templates (raw dicts)
    detectors: Dict[str, Any]
    template_paths_map: Dict[str, List[str]]


def load_config(config_path: Optional[Path] = None) -> Config:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to config.yaml. If None, uses default location.

    Returns:
        Config object

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    # Determine config path
    if config_path is None:
        app_dir = Path(__file__).resolve().parent
        config_path = app_dir / "config.yaml"
    else:
        app_dir = config_path.parent

    # Load YAML
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError("Config file is empty")

    # Parse configuration
    try:
        # Paths
        assets_dir = app_dir / data["assets"]["directory"]
        tesseract_path = data["tesseract"].get("exe_path")

        # Window config
        window = data["window"]

        # Scan config
        scan = data["scan"]

        # OCR config
        ocr = data["ocr"]

        # Template config
        templates_cfg = data["templates"]

        # Automation config
        automation = data["automation"]

        # Debug config
        debug = data["debug"]

        # Build template paths map
        template_paths_map = {}
        for key, paths in data["assets"]["templates"].items():
            if isinstance(paths, list):
                template_paths_map[key] = [str(app_dir / p) for p in paths]
            else:
                template_paths_map[key] = [str(app_dir / paths)]

        # Build detectors dict with resolved paths
        detectors = {}
        for name, detector_cfg in data["detectors"].items():
            detector = detector_cfg.copy()

            # If it's an image detector, resolve template paths
            if detector.get("kind") == "image":
                template_key = detector.get("template_key")
                if template_key and template_key in template_paths_map:
                    detector["paths"] = template_paths_map[template_key]
                    # Remove template_key from detector config
                    del detector["template_key"]

            detectors[name] = detector

        return Config(
            app_dir=app_dir,
            assets_dir=assets_dir,
            tesseract_exe_path=tesseract_path,

            target_window_title=window["title_contains"],
            activate_before_capture=window["activate_before_capture"],
            enforce_window_before_scan=window["enforce_before_scan"],
            target_monitor_index=window["monitor_index"],
            target_client_w=window["target_client_width"],
            target_client_h=window["target_client_height"],
            window_exe_path=window.get("exe_path"),
            launch_if_not_found=window.get("launch_if_not_found", False),
            wait_after_launch_s=window.get("wait_after_launch_s", 5.0),

            default_refresh_ms=scan["default_refresh_ms"],
            min_refresh_ms=scan["min_refresh_ms"],
            max_refresh_ms=scan["max_refresh_ms"],
            refresh_step=scan["refresh_step"],
            min_sleep_s=scan["min_sleep_between_scans_s"],

            default_conf_threshold=ocr["default_confidence_threshold"],
            min_conf=ocr["min_confidence"],
            max_conf=ocr["max_confidence"],
            conf_step=ocr["confidence_step"],

            default_template_confidence=templates_cfg["default_confidence"],
            template_timeout_s=templates_cfg["timeout_seconds"],

            pyautogui_failsafe=automation["failsafe"],
            pyautogui_pause=automation["pause_between_actions"],

            debug_save_screenshots=debug["save_screenshots"],
            debug_save_every_scan=debug["save_every_scan"],
            debug_screenshot_subfolder=debug["screenshot_subfolder"],
            debug_enable_ui=debug["enable_debug_ui"],
            debug_window_print=debug.get("window_debug_print", False),

            detectors=detectors,
            template_paths_map=template_paths_map,
        )

    except KeyError as e:
        raise ValueError(f"Missing required config key: {e}")
    except Exception as e:
        raise ValueError(f"Error parsing config: {e}")


def validate_template_files(config: Config) -> List[str]:
    """
    Validate that all template files exist.

    Args:
        config: Config object

    Returns:
        List of missing file paths (empty if all exist)
    """
    missing = []

    for detector_name, detector_cfg in config.detectors.items():
        if detector_cfg.get("kind") == "image":
            paths = detector_cfg.get("paths", [])
            for path in paths:
                if not Path(path).exists():
                    missing.append(f"{detector_name}: {path}")

    return missing


def print_config_summary(config: Config):
    """Print a summary of loaded configuration for debugging."""
    print("=" * 60)
    print("Configuration Loaded")
    print("=" * 60)
    print(f"App Directory: {config.app_dir}")
    print(f"Assets Directory: {config.assets_dir}")
    print(f"Target Window: {config.target_window_title}")
    print(f"Window Size: {config.target_client_w}x{config.target_client_h}")
    print(f"Auto-launch: {config.launch_if_not_found}")
    if config.window_exe_path:
        print(f"Executable: {config.window_exe_path}")
    print(f"Default Refresh: {config.default_refresh_ms}ms")
    print(f"OCR Confidence: {config.default_conf_threshold}")
    print(f"Detectors: {len(config.detectors)}")
    print(f"Template Groups: {len(config.template_paths_map)}")
    print("=" * 60)
