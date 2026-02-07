"""
state_machine.py

Turns detector results into one state string.
"""

from typing import Dict
from state_rules import STATE_RULES
from states import STATE_UNKNOWN

def resolve_state(results: Dict[str, object]) -> str:
    """
    results is your detector results dict:
    results[name].found should be True or False
    """

    # Evaluate rules in priority order
    rules = sorted(STATE_RULES, key=lambda r: r.get("priority", 0), reverse=True)

    for rule in rules:
        state = rule["state"]
        require_all = rule.get("require_all", [])
        require_none = rule.get("require_none", [])

        ok_all = all(results.get(name) and results[name].found for name in require_all)
        ok_none = all((not results.get(name)) or (not results[name].found) for name in require_none)

        if ok_all and ok_none:
            return state

    return STATE_UNKNOWN
