"""
coordinate_finder.py

Interactive tool to find window-relative coordinates for click_points.py

Usage:
1. Run this script
2. The target game window will be positioned and sized consistently
3. Press 'c' to enter capture mode
4. Click anywhere on the game window to capture coordinates
5. Enter a name for the point (or press Enter to skip)
6. Press 'q' to quit and save all captured points

The tool will:
- Show you the coordinates in window-relative format
- Optionally save them to a file you can copy into click_points.py
"""

import sys
import time
from typing import List, Tuple, Optional
import pyautogui
from pynput import mouse, keyboard

# Import your window manager
from window_manager import ensure_window, EnforceConfig

Point = Tuple[int, int]


class CoordinateFinder:
    def __init__(self, cfg: EnforceConfig):
        self.cfg = cfg
        self.captured_points: List[Tuple[str, Point]] = []
        self.capture_mode = False
        self.win_rect: Optional[Tuple[int, int, int, int]] = None
        self.running = True
        
    def log(self, msg: str):
        print(f"[CoordFinder] {msg}")
    
    def screen_to_window(self, screen_x: int, screen_y: int) -> Optional[Point]:
        """Convert screen coordinates to window-relative coordinates."""
        if not self.win_rect:
            return None
        
        wl, wt, wr, wb = self.win_rect
        win_x = screen_x - wl
        win_y = screen_y - wt
        
        # Check if click is within window bounds
        win_width = wr - wl
        win_height = wb - wt
        
        if 0 <= win_x < win_width and 0 <= win_y < win_height:
            return (win_x, win_y)
        return None
    
    def on_click(self, x, y, button, pressed):
        """Mouse click callback."""
        if not pressed or not self.capture_mode:
            return
        
        # Convert to window-relative coordinates
        win_coords = self.screen_to_window(x, y)
        
        if win_coords:
            print(f"\n✓ Captured: Screen ({x}, {y}) -> Window {win_coords}")
            print("Enter a name for this point (or press Enter to skip): ", end="", flush=True)
            
            # Temporarily stop capture mode while getting input
            self.capture_mode = False
            
            try:
                name = input().strip()
                if name:
                    self.captured_points.append((name, win_coords))
                    print(f"✓ Saved as '{name}': {win_coords}")
                else:
                    print("Skipped (no name provided)")
            except (EOFError, KeyboardInterrupt):
                print("\nInput cancelled")
            
            print("\nPress 'c' to capture another point, 'q' to quit")
        else:
            print(f"\n✗ Click at ({x}, {y}) is outside the game window!")
            print("Press 'c' to try again")
    
    def on_key_press(self, key):
        """Keyboard callback."""
        try:
            if hasattr(key, 'char'):
                if key.char == 'c':
                    self.capture_mode = True
                    print("\n>>> CAPTURE MODE: Click on the game window to capture coordinates...")
                elif key.char == 'q':
                    print("\n>>> Quitting...")
                    self.running = False
                    return False  # Stop listener
        except AttributeError:
            pass
    
    def save_points_to_file(self, filename: str = "captured_points.py"):
        """Save captured points to a file."""
        if not self.captured_points:
            self.log("No points captured, nothing to save")
            return
        
        with open(filename, 'w') as f:
            f.write('"""\nCaptured click points - add these to click_points.py\n"""\n\n')
            f.write("CAPTURED_POINTS = {\n")
            for name, (x, y) in self.captured_points:
                f.write(f'    "{name}": ({x}, {y}),\n')
            f.write("}\n")
        
        self.log(f"Saved {len(self.captured_points)} points to {filename}")
    
    def run(self):
        """Main loop."""
        print("=" * 60)
        print("COORDINATE FINDER TOOL")
        print("=" * 60)
        
        # Ensure window is in correct state
        self.log("Finding and positioning game window...")
        st = ensure_window(self.cfg, self.log)
        
        if not st:
            self.log("ERROR: Could not find game window!")
            return
        
        self.win_rect = st.win_rect
        wl, wt, wr, wb = self.win_rect
        
        print(f"\n✓ Game window found: '{st.title}'")
        print(f"  Window position: ({wl}, {wt}) to ({wr}, {wb})")
        print(f"  Client size: {st.client_size[0]} x {st.client_size[1]}")
        print(f"\nControls:")
        print("  'c' = Start capturing (then click on the game window)")
        print("  'q' = Quit and save all captured points")
        print("\nReady! Press 'c' to start capturing coordinates...")
        
        # Set up listeners
        mouse_listener = mouse.Listener(on_click=self.on_click)
        keyboard_listener = keyboard.Listener(on_press=self.on_key_press)
        
        mouse_listener.start()
        keyboard_listener.start()
        
        # Keep running until user quits
        try:
            while self.running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
        
        # Cleanup
        mouse_listener.stop()
        keyboard_listener.stop()
        
        # Show summary
        print("\n" + "=" * 60)
        print(f"CAPTURED {len(self.captured_points)} POINTS:")
        print("=" * 60)
        
        if self.captured_points:
            for name, (x, y) in self.captured_points:
                print(f'  "{name}": ({x}, {y}),')
            
            # Save to file
            self.save_points_to_file()
            print("\n✓ Points saved to 'captured_points.py'")
            print("  Copy them into your click_points.py file!")
        else:
            print("  (none)")
        
        print("=" * 60)


def main():
    # Configure for your game
    # Adjust title_contains to match your game window title
    cfg = EnforceConfig(
        title_contains="Roblox",  # CHANGE THIS to match your game window
        monitor_index=2,
        target_client_w=1280,
        target_client_h=720,
    )
    
    print("\n⚠ IMPORTANT: Update 'title_contains' in coordinate_finder.py")
    print(f"   Current value: '{cfg.title_contains}'")
    print("   Make sure this matches your game window title!\n")
    
    finder = CoordinateFinder(cfg)
    finder.run()


if __name__ == "__main__":
    main()