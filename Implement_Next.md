Next things to implement:

1. Remove Refresh (ms) from UI
    - Move to config.yaml
2. Remove OCR confidence threshold from UI
    - Move to config.yaml
3. Add to UI "Current Status" and to the right of it, display the current machine state status
    - non editable. Updates on scan, but only when status changes from current status
4. Options area right below current status
    - Checkbox - label, "Private Server"
    - Checkbox - label, "Public Server"
    - Checkbox - label, "Enable Move To Private"
    - Textbox (int) - Label "Threshold" to right of this another textbox - Label "Time"
    Only private or public can be checked, not both. "Enable move to private" can only be checked if public is checked.
    Explaination of effects when checked to behaviour of code:
        - Main difference between public and private is what startup sequence is ran during a disconnect, game crash (no longer running) and 
5. Remove OCR auto_text and end_run. OCR is only used to find eaten by on DEAD screen now


6. Game state logic routines
    UNKNOWN - No state matches found
    IN_RUN - Main function of the app. run a click routine every x minutes
    DEAD - Eaten by another player. Use OCR to capture player name. Keep a record of every occurence with player name, timestamp and session id. 
        - Each time Start(F5) is started, a new session id is created, for record purposes. Each session should be identified by the session + start time of that session. 
        - might need a small database to store this data, or I can dedicate a excel spreadsheet file for it.
    NET_REVEAL - Immediately follows DEAD state. No actions required in this state
