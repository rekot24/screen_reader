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
        "require_all": ["DEATH_TEXT"],
        "require_none": [],
        "priority": 100,
    },
    {
        "state": "IN_RUN",
        "require_all": ["END_RUN_TEXT"],
        "require_none": ["DEATH_TEXT"],
        "priority": 80,
    },
    {
        "state": "MENU",
        "require_all": ["START_BUTTON_TEXT"],
        "require_none": [],
        "priority": 60,
    },
]
