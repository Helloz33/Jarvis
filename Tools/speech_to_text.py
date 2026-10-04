from __future__ import annotations

import speech_recognition as sr

_recognizer = sr.Recognizer()


def listen(timeout: int = 5, phrase_time_limit: int = 15) -> str:
    """Record one phrase from the default microphone and return the
    recognized text.

    Returns an empty string if nothing was heard in time, or if speech was
    heard but could not be understood. Raises RuntimeError if the speech
    recognition service itself can't be reached (e.g. no internet).

    timeout: how many seconds to wait for speech to *start* before giving up.
    phrase_time_limit: max seconds of speech to capture once it starts.
    """
    try:
        with sr.Microphone() as source:
            print("Listening... (speak now)")
            _recognizer.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = _recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
            except sr.WaitTimeoutError:
                return ""
    except OSError as exc:
        raise RuntimeError(f"No microphone available: {exc}") from exc

    try:
        return _recognizer.recognize_google(audio)
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as exc:
        raise RuntimeError(f"Speech recognition service error: {exc}") from exc