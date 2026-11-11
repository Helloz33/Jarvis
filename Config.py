"""Settings in one place. Change them here (or in .env) instead of hunting through the code.
The V0.9 Settings tab will edit these for you."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()  # reads .env in the current directory, if present

NAME = "Iris"                 # the assistant's name: used in the persona, the UI, notifications and the wake phrase
USER_ADDRESS = "sir"          # how the assistant addresses you; "" to never address you
# The voice: the first one installed on this computer is used (macOS: `say -v '?'` lists them;
# better-sounding Premium/Enhanced voices are in System Settings > Accessibility > Spoken Content >
# System Voice > Manage Voices). If none is installed, the system's default voice is used.
VOICES_MAC = ["Serena (Premium)", "Serena (Enhanced)", "Serena", "Kate (Enhanced)", "Kate", "Samantha (Enhanced)", "Samantha"]
VOICES_WINDOWS = ["Microsoft Hazel Desktop", "Microsoft Zira Desktop"]
AUTO_LISTEN_ON_START = True   # greet when the window opens, then go straight to listening

# The model: change it here, or without editing code with IRIS_MODEL=qwen3:8b in .env
MODEL = os.getenv("IRIS_MODEL") or os.getenv("JARVIS_MODEL") or "qwen3.5:9b"


_voice: str | None = None


def voice() -> str:
    """The voice to speak with (checked once, then remembered)."""
    global _voice
    if _voice is None:
        from Tools import system
        _voice = system.pick_voice(VOICES_WINDOWS if system.IS_WIN else VOICES_MAC)
    return _voice


def wake_phrases() -> set[str]:
    """What counts as the wake phrase, with spaces and punctuation removed. Speech recognition
    sometimes mishears a name, so a few close spellings count too."""
    name = "".join(ch for ch in NAME.lower() if ch.isalpha())
    spellings = {name} | ({"iris", "irish", "iriss", "irus", "irys", "eyeris", "ires"} if name == "iris" else set())
    return {f"{s}wakeup" for s in spellings}
