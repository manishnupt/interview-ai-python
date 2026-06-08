import asyncio
import base64
from urllib.parse import quote
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import Response
import plivo
import config
from .base import CallProvider


class PlivoProvider(CallProvider):
    def __init__(self):
        if not config.PLIVO_AUTH_ID or not config.PLIVO_AUTH_TOKEN:
            raise EnvironmentError("PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN are required when CALL_PROVIDER=plivo")
        self._client = plivo.RestClient(auth_id=config.PLIVO_AUTH_ID, auth_token=config.PLIVO_AUTH_TOKEN)
        self._router = APIRouter()

        @self._router.get("/plivo-answer")
        async def plivo_answer(request: Request):
            candidate_name = request.query_params.get("candidate_name", "Candidate")
            host = request.headers.get("host")
            ws_url = f"wss://{host}/media-stream?candidate_name={quote(candidate_name)}"
            print(f"[Plivo] Answer request — host header: '{host}'")
            print(f"[Plivo] WebSocket URL: '{ws_url}'")
            print(f"[Plivo] All request headers: {dict(request.headers)}")
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<Response>"
                f'<Stream keepCallAlive="true" bidirectional="true" contentType="audio/x-mulaw;rate=8000">'
                f"{ws_url}"
                "</Stream>"
                "</Response>"
            )
            print(f"[Plivo] Answer XML:\n{xml}")
            return Response(content=xml, media_type="application/xml")

        @self._router.post("/plivo-hangup")
        async def plivo_hangup(request: Request):
            form = await request.form()
            call_uuid = form.get("CallUUID", "unknown")
            direction = form.get("Direction", "")
            hangup_cause = form.get("HangupCause", "")
            hangup_source = form.get("HangupSource", "")
            print(f"[Plivo] Hangup — UUID={call_uuid[:12]}... direction={direction!r} cause={hangup_cause!r} source={hangup_source!r}")
            print(f"[Plivo] Full hangup form: {dict(form)}")
            return Response(content="OK")

    @property
    def router(self) -> APIRouter:
        return self._router

    def place_call(self, to_phone: str, candidate_name: str) -> str:
        response = self._client.calls.create(
            from_=config.PLIVO_PHONE_NUMBER,
            to_=to_phone,
            answer_url=f"{config.APP_BASE_URL}/plivo-answer?candidate_name={quote(candidate_name)}",
            answer_method="GET",
            hangup_url=f"{config.APP_BASE_URL}/plivo-hangup",
            hangup_method="POST",
        )
        call_uuid = response["request_uuid"]
        print(f"[Plivo] Call placed to {candidate_name} ({to_phone}) — UUID: {call_uuid}")
        return call_uuid

    def end_call(self, call_id: str) -> None:
        self._client.calls.hangup(call_id)

    def extract_stream_sid(self, start_data: dict) -> str:
        return start_data.get("streamId") or start_data.get("streamSid", "")

    def extract_call_id(self, start_data: dict) -> str:
        return start_data.get("callId", "")

    async def send_audio_chunk(self, websocket: WebSocket, stream_sid: str, audio_bytes: bytes) -> None:
        payload = base64.b64encode(audio_bytes).decode("utf-8")
        await websocket.send_json({
            "event": "playAudio",
            "media": {
                "contentType": "audio/x-mulaw",
                "sampleRate": "8000",
                "payload": payload,
            },
        })

    async def send_full_audio(self, websocket: WebSocket, stream_sid: str, audio_bytes: bytes, **kwargs) -> None:
        """Stream audio in 640-byte chunks at 20ms intervals (Plivo's documented example format)."""
        chunk_size = 640  # 80ms per chunk at 8kHz mulaw
        for i in range(0, len(audio_bytes), chunk_size):
            chunk = audio_bytes[i:i + chunk_size]
            await self.send_audio_chunk(websocket, stream_sid, chunk)
            await asyncio.sleep(0.02)
