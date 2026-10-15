"""Deciding, inside the engine, when the user has finished speaking.

Transcription starts the moment the pause is long enough, with no round trip through the
desktop app. Natural speech has pauses, so the wait is longer while the request is still
short ("Vico, can you... open my notes").
"""

from __future__ import annotations

SPEECH_LEVEL = 0.03  # the lowest level that counts as speech, even in a silent room
NOISE_MARGIN = 2.5  # speech must be this many times louder than the room
ROOM_MAX = 0.06  # louder than this is never just the room
SILENCE_S = 1.5  # pause after the last word that ends the request
SILENCE_SHORT_S = 2.1  # ...while less than SHORT_SPEECH_S has been said
SHORT_SPEECH_S = 1.6


class Endpointer:
    def __init__(self) -> None:
        self.floor = 0.0  # the room's background level, learned while the user is quiet
        self.heard = False
        self.speech_since = 0.0
        self.quiet_since = 0.0

    def feed(self, level: float, now: float) -> bool:
        """True once the user has spoken and then paused long enough."""
        if not self.heard and level < ROOM_MAX:
            self.floor = level if self.floor == 0 else min(self.floor * 1.02 + 0.001, level)
        if level > max(SPEECH_LEVEL, self.floor * NOISE_MARGIN):
            if not self.heard:
                self.speech_since = now
            self.heard = True
            self.quiet_since = now
        if not self.heard:
            return False
        spoken = self.quiet_since - self.speech_since  # how long the user has talked so far
        pause = SILENCE_SHORT_S if spoken < SHORT_SPEECH_S else SILENCE_S
        return now - self.quiet_since > pause
