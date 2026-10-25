"""Always-on wake word: say "Jarvis wake up" to launch Jarvis.

Run by launchd (see the README) or by hand:  python Wake_Jarvis.py
"""
import os
import re
import subprocess
import sys
import time

import numpy as np
import pyaudio
from faster_whisper import WhisperModel

HERE = os.path.dirname(os.path.abspath(__file__))

PHRASE = "jarviswakeup"      # compared with spaces/punctuation stripped
RATE = 16000
CHUNK_SEC = 2
THRESHOLD = 0.01             # tune: print(volume) while quiet vs talking
DEBUG = True                 # prints what Whisper heard; set False when happy

# First run needs internet to download the model. After that, add
# local_files_only=True so it never touches the network again.
model = WhisperModel("tiny.en", compute_type="int8")

stream = pyaudio.PyAudio().open(
    format=pyaudio.paInt16, channels=1, rate=RATE,
    input=True, frames_per_buffer=1024,
)


def heard_phrase(audio) -> bool:
    segments, _ = model.transcribe(audio, language="en", beam_size=1)
    text = "".join(s.text for s in segments)
    if DEBUG:
        print(f"heard: {text!r}")
    return PHRASE in re.sub(r"[^a-z]", "", text.lower())


def wake() -> None:
    # Only launch if Jarvis isn't already running.
    running = subprocess.run(["pgrep", "-f", "App.py"], capture_output=True).returncode == 0
    if not running:
        subprocess.Popen([sys.executable, os.path.join(HERE, "App.py")], cwd=HERE)
    time.sleep(10)           # cooldown so one phrase doesn't trigger twice


print("Listening for 'Jarvis wake up'...")
previous = np.zeros(0, dtype=np.float32)

while True:
    raw = stream.read(RATE * CHUNK_SEC, exception_on_overflow=False)
    chunk = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    audio = np.concatenate([previous, chunk])
    previous = chunk[-RATE:]                       # keep last second (overlap)

    volume = np.abs(chunk).mean()
    if DEBUG:
        print(f"volume: {volume:.4f}", end="\r")

    if volume > THRESHOLD and heard_phrase(audio):
        wake()