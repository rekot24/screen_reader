"""
process_manager.py

Manages application processes - checking if they're running and launching them if needed.

This module works alongside window_manager.py:
- process_manager: Ensures the application process is running
- window_manager: Ensures the window is positioned and sized correctly

Usage:
    from process_manager import ensure_process_running
    
    # Check if process is running, launch if needed
    success = ensure_process_running(
        title_contains="Roblox",
        exe_path="C:\\Program Files\\Roblox\\RobloxPlayerLauncher.exe",
        wait_after_launch_s=5.0,
        log_fn=print
    )
"""

from __future__ import annotations

import time
import subprocess
from pathlib import Path
from typing import Optional, Callable

import win32gui
import win32process
import psutil


def find_window_by_title_contains(title_contains: str) -> Optional[int]:
    """
    Find the first visible top-level window whose title contains the given substring.
    
    Args:
        title_contains: Substring to search for (case-insensitive)
        
    Returns:
        Window handle (hwnd) if found, None otherwise
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


def get_process_name_from_window(hwnd: int) -> Optional[str]:
    """
    Get the process name (executable name) from a window handle.
    
    Args:
        hwnd: Window handle
        
    Returns:
        Process name (e.g., "RobloxPlayerBeta.exe") or None if unable to determine
    """
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)
        return process.name()
    except Exception:
        return None


def is_process_running_by_name(process_name: str) -> bool:
    """
    Check if a process with the given name is currently running.
    
    Args:
        process_name: Name of the process (e.g., "RobloxPlayerBeta.exe")
        
    Returns:
        True if at least one instance is running, False otherwise
    """
    process_name_lower = process_name.lower()
    
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'].lower() == process_name_lower:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    
    return False


def launch_application(exe_path: str, log_fn: Callable[[str], None]) -> bool:
    """
    Launch an application from the given executable path.
    
    Args:
        exe_path: Full path to the executable
        log_fn: Logging function to call with status messages
        
    Returns:
        True if launch was attempted successfully, False if failed
        
    Note:
        This only verifies that the launch command was executed.
        It does not wait for the window to appear - that's handled separately.
    """
    exe_path_obj = Path(exe_path)
    
    # Validate that the executable exists
    if not exe_path_obj.exists():
        log_fn(f"[process] ERROR: Executable not found: {exe_path}")
        return False
    
    if not exe_path_obj.is_file():
        log_fn(f"[process] ERROR: Path is not a file: {exe_path}")
        return False
    
    log_fn(f"[process] Launching application: {exe_path}")
    
    try:
        # Launch the application
        # Using subprocess.Popen to avoid blocking
        # We don't need to track the process handle - we'll find it by window title
        subprocess.Popen([str(exe_path)], shell=False)
        log_fn("[process] Launch command sent successfully")
        return True
        
    except FileNotFoundError:
        log_fn(f"[process] ERROR: Executable not found: {exe_path}")
        return False
    except PermissionError:
        log_fn(f"[process] ERROR: Permission denied when launching: {exe_path}")
        return False
    except Exception as e:
        log_fn(f"[process] ERROR: Failed to launch application: {type(e).__name__}: {e}")
        return False


def ensure_process_running(
    title_contains: str,
    exe_path: Optional[str],
    wait_after_launch_s: float = 5.0,
    log_fn: Callable[[str], None] = print,
    launch_enabled: bool = True,
) -> bool:
    """
    Ensure that the target application is running.
    
    This is the main function you'll call from your scan loop.
    
    Workflow:
    1. Check if a window with matching title exists
    2. If yes -> return True (process is running)
    3. If no and launch is enabled and exe_path provided -> launch it
    4. Wait for the configured time
    5. Return True if successful, False otherwise
    
    Args:
        title_contains: Substring of the window title to search for
        exe_path: Path to the executable to launch if process not found
        wait_after_launch_s: How long to wait after launching before continuing
        log_fn: Function to call for logging messages
        launch_enabled: Whether to actually launch the app (allows disabling feature)
        
    Returns:
        True if process is running (or was successfully launched), False otherwise
        
    Examples:
        >>> # Basic usage with auto-launch
        >>> ensure_process_running(
        ...     title_contains="Roblox",
        ...     exe_path="C:\\Program Files\\Roblox\\RobloxPlayerLauncher.exe",
        ...     log_fn=self._log
        ... )
        True
        
        >>> # Check only, don't launch
        >>> ensure_process_running(
        ...     title_contains="Roblox",
        ...     exe_path=None,
        ...     launch_enabled=False,
        ...     log_fn=self._log
        ... )
        False  # If not running
    """
    # Check if window already exists
    hwnd = find_window_by_title_contains(title_contains)
    
    if hwnd:
        log_fn(f"[process] Window found with title containing '{title_contains}'")
        return True
    
    # Window not found
    log_fn(f"[process] No window found with title containing '{title_contains}'")
    
    # If launching is disabled or no exe path provided, we can't do anything
    if not launch_enabled:
        log_fn("[process] Auto-launch is disabled")
        return False
    
    if not exe_path:
        log_fn("[process] No executable path configured for auto-launch")
        return False
    
    # Try to launch the application
    log_fn("[process] Attempting to launch application...")
    
    launch_success = launch_application(exe_path, log_fn)
    
    if not launch_success:
        log_fn("[process] Failed to launch application")
        return False
    
    # Wait for the application to start
    log_fn(f"[process] Waiting {wait_after_launch_s}s for application to start...")
    time.sleep(wait_after_launch_s)
    
    # Check if the window appeared
    hwnd = find_window_by_title_contains(title_contains)
    
    if hwnd:
        log_fn(f"[process] SUCCESS: Application launched and window detected")
        return True
    else:
        log_fn(f"[process] WARNING: Application may have launched, but window not detected yet")
        log_fn(f"[process] The application might need more time to start")
        # We return True here because the launch was successful, even if window isn't visible yet
        # The window_manager will handle waiting for the window in the next scan
        return True


def get_process_info(title_contains: str, log_fn: Callable[[str], None]) -> dict:
    """
    Get detailed information about a process by its window title.
    
    Useful for debugging and understanding what's running.
    
    Args:
        title_contains: Substring of the window title to search for
        log_fn: Function to call for logging messages
        
    Returns:
        Dictionary with process information, or empty dict if not found
        
    Example:
        >>> info = get_process_info("Roblox", print)
        >>> print(info)
        {
            'hwnd': 12345,
            'title': 'Roblox',
            'pid': 67890,
            'process_name': 'RobloxPlayerBeta.exe',
            'exe_path': 'C:\\Program Files\\Roblox\\Versions\\...',
        }
    """
    hwnd = find_window_by_title_contains(title_contains)
    
    if not hwnd:
        log_fn(f"[process] No window found with title containing '{title_contains}'")
        return {}
    
    try:
        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)
        
        info = {
            'hwnd': hwnd,
            'title': title,
            'pid': pid,
            'process_name': process.name(),
            'exe_path': process.exe(),
            'status': process.status(),
            'create_time': process.create_time(),
        }
        
        log_fn(f"[process] Found process: {info['process_name']} (PID: {pid})")
        log_fn(f"[process] Executable: {info['exe_path']}")
        
        return info
        
    except Exception as e:
        log_fn(f"[process] Error getting process info: {type(e).__name__}: {e}")
        return {'hwnd': hwnd}