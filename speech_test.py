"""Quick manual test for speech_to_text.listen().

Run this from inside the Jarvis/ directory:
    python test_voice_5s.py

You'll get 5 seconds to start talking once it says "Listening...".
"""
from Tools import listen

if __name__ == "__main__":
    print("Say something, you have 5 seconds to start talking...")
    text = listen(timeout=5, phrase_time_limit=5)

    if text:
        print(f"Heard: {text}")
    else:
        print("Didn't catch anything.")