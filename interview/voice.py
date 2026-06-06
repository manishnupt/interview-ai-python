try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
from elevenlabs.client import ElevenLabs as ElevenLabsClient
import config

VOICE_ID = "fPIfC3elMLbN9tNwMXkw"  # Roger — available on free plan; swap for Rachel (21m00Tcm4TlvDq8ikWAM) on paid plan
MODEL_ID = "eleven_flash_v2_5"


class VoiceSynthesiser:
    def __init__(self):
        self.client = ElevenLabsClient(api_key=config.ELEVENLABS_API_KEY)
        self._filler_audio: bytes = None

    def text_to_mulaw(self, text: str) -> bytes:
        print(f"[ElevenLabs] Synthesising: {text[:60]}...")

        audio_generator = self.client.text_to_speech.convert(
            voice_id=VOICE_ID,
            model_id=MODEL_ID,
            text=text,
            output_format="pcm_8000",
            voice_settings={
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": False,
            },
        )

        pcm_bytes = b"".join(audio_generator)
        mulaw_bytes = audioop.lin2ulaw(pcm_bytes, 2)
        print(f"[ElevenLabs] Generated {len(mulaw_bytes)} bytes of audio")
        return mulaw_bytes

    def get_filler_audio(self) -> bytes:
        if self._filler_audio is None:
            print("[ElevenLabs] Pre-generating filler audio...")
            self._filler_audio = self.text_to_mulaw(
                "Let me think about that for a moment."
            )
        return self._filler_audio

    def chunk_audio(self, mulaw_bytes: bytes, chunk_size: int = 3200) -> list[bytes]:
        return [
            mulaw_bytes[i:i + chunk_size]
            for i in range(0, len(mulaw_bytes), chunk_size)
        ]


if __name__ == "__main__":
    synth = VoiceSynthesiser()
    audio = synth.text_to_mulaw(
        "Hello, I am your AI interviewer today. "
        "Can you tell me a little about yourself?"
    )
    print(f"Generated {len(audio)} bytes of mulaw audio")

    with open("test_audio.raw", "wb") as f:
        f.write(audio)
    print("Saved to test_audio.raw")
