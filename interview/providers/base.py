from abc import ABC, abstractmethod
import asyncio
from fastapi import APIRouter, WebSocket


class CallProvider(ABC):
    @property
    @abstractmethod
    def router(self) -> APIRouter: ...

    @abstractmethod
    def place_call(self, to_phone: str, candidate_name: str) -> str: ...

    @abstractmethod
    def end_call(self, call_id: str) -> None: ...

    @abstractmethod
    def extract_stream_sid(self, start_data: dict) -> str: ...

    @abstractmethod
    def extract_call_id(self, start_data: dict) -> str: ...

    @abstractmethod
    async def send_audio_chunk(self, websocket: WebSocket, stream_sid: str, audio_bytes: bytes) -> None: ...

    async def send_full_audio(self, websocket: WebSocket, stream_sid: str, audio_bytes: bytes, chunk_size: int = 3200) -> None:
        """Default: stream audio in chunks. Providers can override for atomic delivery."""
        for i in range(0, len(audio_bytes), chunk_size):
            chunk = audio_bytes[i:i + chunk_size]
            await self.send_audio_chunk(websocket, stream_sid, chunk)
            await asyncio.sleep(0.05)
