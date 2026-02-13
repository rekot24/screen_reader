"""
state_rules.py

Each state is determined by detector results.
Detectors are the truth signals.
States are derived from those signals.

Rule format:
- require_all: these detectors must be found
- require_none: these detectors must NOT be found
"""

from typing import Dict, List

STATE_RULES: List[Dict] = [
    {
        "state": "DEAD",
        "require_all": ["TO_LOBBY_BUTTON"],
        "require_none": [],
        "priority": 100,
    },
    {
        "state": "IN_RUN",
        "require_all": ["END_RUN_BUTTON", "AUTO_GREEN_ICON"],
        "require_none": ["TO_LOBBY_BUTTON", "SWITCH_FISH_ICON", "LEAVE_BUTTON", "LEAVE_BUTTON_CONFIRM"],
        "priority": 80,
    },
    {
        "state": "MENU",
        "require_all": ["LEAVE_BUTTON"],
        "require_none": [],
        "priority": 60,
    },
    {
        "state": "NET_REVEAL",
        "require_all": [],
        "require_none": ["TO_LOBBY_BUTTON", "END_RUN_BUTTON", "AUTO_GREEN_ICON"],
        "priority": 50,
    },
    {
        "state": "STUCK_IN_LOBBY",
        "require_all": ["SWITCH_FISH_ICON", "END_RUN_BUTTON"],
        "require_none": ["TO_LOBBY_BUTTON"],
        "priority": 40,
    },
    {
        "state": "MENU_CONFIRMATION",
        "require_all": ["LEAVE_BUTTON_CONFIRM"],
        "require_none": [],
        "priority": 30,
    },
    {   
        "state": "GAME_CLOSED",
        "require_all": [],
        "require_none": ["TO_LOBBY_BUTTON", "END_RUN_BUTTON", "AUTO_GREEN_ICON", "SWITCH_FISH_ICON", "LEAVE_BUTTON", "LEAVE_BUTTON_CONFIRM"],
        "priority": 20,
    },
    {
        "state": "DISCONNECTED",
        "require_all": ["DISCONNECTED_ICON"],
        "require_none": [],
        "priority": 90,
    },
    {
        "state": "HOME_SCREEN",
        "require_all": ["HOME_SCREEN_ICON"],
        "require_none": ["TO_LOBBY_BUTTON", "END_RUN_BUTTON", "AUTO_GREEN_ICON", "SWITCH_FISH_ICON", "LEAVE_BUTTON", "LEAVE_BUTTON_CONFIRM"],
        "priority": 70,
    },
    {
        "state": "FISH_MENU",
        # Menu for "Be Fish"
        "require_all": ["FISH_MENU_SCREEN"],
        "require_none": ["END_RUN_BUTTON", "TO_LOBBY_BUTTON"],
        "priority": 65,
    },
    {
        "state": "SERVER_MENU",
        "require_all": ["SERVER_MENU"],
        "require_none": ["END_RUN_BUTTON", "TO_LOBBY_BUTTON", "SWITCH_FISH_ICON"],
        "priority": 55,
    },
    {
        "state": "AUTO_STOPPED",
        "require_all": ["AUTO_RED_ICON", "END_RUN_BUTTON"],
        "require_none": ["TO_LOBBY_BUTTON", "LEAVE_BUTTON", "LEAVE_BUTTON_CONFIRM"],
        "priority": 75,
    },
    {
        "state": "LEAVE_MENU",
        "require_all": ["LEAVE_BUTTON_CONFIRM"],
        "require_none": [],
        "priority": 35,
    },
    {
        "state": "FISH_MENU_SCROLLED_DOWN",
        "require_all": ["FISH_MENU_SCROLLED_DOWN"],
        "require_none": ["END_RUN_BUTTON", "TO_LOBBY_BUTTON"],
        "priority": 45,
    },
    {
        "state": "PRIVATE_SERVERS_MENU",
        "require_all": ["PRIVATE_SERVERS"],
        "require_none": [],
        "priority": 50,
    }
]
