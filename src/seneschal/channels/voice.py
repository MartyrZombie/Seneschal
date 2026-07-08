"""Voice channel stub — conversational layer + async orchestrator (plan §18)."""

from __future__ import annotations

AI_DISCLOSURE = (
    "Hello. This is an AI assistant. I'm an artificial intelligence, not a human. "
    "How can I help you today?"
)

THIRD_PARTY_DISCLOSURE = (
    "This message is from an AI assistant acting on the owner's behalf."
)


class VoiceChannel:
    """Build step 13: STT/TTS/VAD on GPU 2, disclosure at call start."""

    def opening_disclosure(self) -> str:
        return AI_DISCLOSURE

    def third_party_disclosure(self) -> str:
        return THIRD_PARTY_DISCLOSURE
