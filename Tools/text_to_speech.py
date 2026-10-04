import pyttsx3

_engine = None

def _get_engine():
    global _engine
    if _engine is None:
        _engine = pyttsx3.init()
        _engine.setProperty("rate", 150) 
        _engine.setProperty("volume", 1.0)  # Set the volume to maximum

    return _engine

def speak(text: str):
   if not isinstance(text, str) or not text.strip():
       return

   engine = _get_engine()
   engine.say(text)
   engine.runAndWait()
