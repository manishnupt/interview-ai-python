import asyncio
from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from deepgram.listen.v1.socket_client import ListenV1Results, ListenV1UtteranceEnd
import config


class Transcriber:
    def __init__(self, on_transcript, on_interim=None):
        """
        on_transcript: async callback called with (text: str) for each final transcript.
        on_interim: optional async callback called on any active interim — used to
                    cancel debounce timers so the AI doesn't cut in mid-sentence.
        """
        self.client = AsyncDeepgramClient(api_key=config.DEEPGRAM_API_KEY)
        self.on_transcript = on_transcript
        self.on_interim = on_interim
        self.connection = None
        self._ctx = None
        self._listen_task = None
        self.is_connected = False
        self._all_transcripts = []
        self._warned_not_connected = False

    async def connect(self):
        """Opens the Deepgram streaming connection optimised for Twilio mulaw phone audio."""
        self._ctx = self.client.listen.v1.connect(
            model="nova-2",
            language="en-US",
            encoding="mulaw",
            sample_rate=8000,
            channels=1,
            punctuate=True,
            interim_results=True,
            endpointing=600,
            utterance_end_ms=1200,
        )
        self.connection = await self._ctx.__aenter__()

        self.connection.on(EventType.MESSAGE, self._on_message)
        self.connection.on(EventType.ERROR, self._on_error)
        self.connection.on(EventType.CLOSE, self._on_close)

        self._listen_task = asyncio.create_task(self.connection.start_listening())
        self.is_connected = True
        print("[Deepgram] Connected to streaming STT")

    async def send_audio(self, audio_bytes: bytes):
        """Send a raw audio chunk to Deepgram. Auto-reconnects if the connection dropped."""
        if not self.is_connected:
            print("[Deepgram] Reconnecting after idle timeout...")
            await self.connect()
        if self.is_connected and self.connection:
            await self.connection.send_media(audio_bytes)

    async def disconnect(self):
        """Cleanly close the Deepgram connection."""
        if self.connection and self.is_connected:
            self.is_connected = False
            await self.connection.send_close_stream()
            if self._listen_task:
                self._listen_task.cancel()
                try:
                    await self._listen_task
                except asyncio.CancelledError:
                    pass
            if self._ctx:
                await self._ctx.__aexit__(None, None, None)
            print("[Deepgram] Disconnected")

    def get_full_transcript(self) -> str:
        """Returns all transcribed utterances joined as a single string."""
        return "\n".join(self._all_transcripts)

    async def _on_message(self, data):
        """Routes incoming Deepgram messages to the appropriate handler."""
        if isinstance(data, ListenV1UtteranceEnd):
            await self._on_utterance_end(data)
            return

        if not isinstance(data, ListenV1Results):
            return

        try:
            is_final = data.is_final
            transcript = data.channel.alternatives[0].transcript
            if transcript and transcript.strip() and is_final:
                text = transcript.strip()
                self._all_transcripts.append(text)
                print(f"[Deepgram] Final: {text}")
                await self.on_transcript(text)
            elif transcript and not is_final:
                print(f"[Deepgram] Interim: {transcript}", end="\r")
                if self.on_interim:
                    await self.on_interim()
        except Exception as e:
            print(f"[Deepgram] Parse error: {e}")

    async def _on_utterance_end(self, data):
        print("[Deepgram] Utterance end detected")

    async def _on_error(self, error):
        print(f"[Deepgram] Error: {error}")

    async def _on_close(self, _):
        print("[Deepgram] Connection closed")
        self.is_connected = False
