import base64
from urllib.parse import quote
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
import config
from .base import CallProvider


class TwilioProvider(CallProvider):
    def __init__(self):
        if not config.TWILIO_ACCOUNT_SID or not config.TWILIO_AUTH_TOKEN:
            raise EnvironmentError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are required when CALL_PROVIDER=twilio")
        self._client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
        self._router = APIRouter()

        @self._router.get("/twiml")
        async def twiml_handler(request: Request):
            response = VoiceResponse()
            connect = Connect()
            stream = Stream(url=f"wss://{request.headers.get('host')}/media-stream")
            stream.parameter(name="candidate_name", value=request.query_params.get("candidate_name", "Candidate"))
            connect.append(stream)
            response.append(connect)
            print("[Twilio] TwiML served — connecting call to WebSocket")
            return Response(content=str(response), media_type="application/xml")

        @self._router.post("/call-status")
        async def call_status(request: Request):
            form = await request.form()
            status = form.get("CallStatus", "unknown")
            sid = form.get("CallSid", "unknown")
            answered_by = form.get("AnsweredBy", "")
            print(f"[Twilio] Call {sid[:12]}... status: {status}" + (f" (answered_by: {answered_by})" if answered_by else ""))
            return Response(content="OK")

    @property
    def router(self) -> APIRouter:
        return self._router

    def place_call(self, to_phone: str, candidate_name: str) -> str:
        call = self._client.calls.create(
            to=to_phone,
            from_=config.TWILIO_PHONE_NUMBER,
            url=f"{config.APP_BASE_URL}/twiml?candidate_name={quote(candidate_name)}",
            method="GET",
            status_callback=f"{config.APP_BASE_URL}/call-status",
            status_callback_method="POST",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            timeout=60,
        )
        print(f"[Twilio] Call placed to {candidate_name} ({to_phone}) — SID: {call.sid}")
        return call.sid

    def end_call(self, call_id: str) -> None:
        self._client.calls.update(sid=call_id, status="completed")

    def extract_stream_sid(self, start_data: dict) -> str:
        return start_data["streamSid"]

    def extract_call_id(self, start_data: dict) -> str:
        return start_data.get("callSid", "")

    async def send_audio_chunk(self, websocket: WebSocket, stream_sid: str, audio_bytes: bytes) -> None:
        payload = base64.b64encode(audio_bytes).decode("utf-8")
        await websocket.send_json({
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": payload},
        })
