import json
import base64
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
import config
from interview.transcriber import Transcriber
from interview.voice import VoiceSynthesiser
from interview.interviewer import Interviewer

app = FastAPI()
twilio_client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
active_call_sid = None


def place_call(to_phone: str, candidate_name: str) -> str:
    """
    Places an outbound Twilio call to the candidate.
    Returns the Twilio call SID.

    When the call connects, Twilio hits our /twiml endpoint
    which tells it to stream audio to our WebSocket.
    """
    global active_call_sid
    call = twilio_client.calls.create(
        to=to_phone,
        from_=config.TWILIO_PHONE_NUMBER,
        url=f"{config.APP_BASE_URL}/twiml",
        method="GET",
        status_callback=f"{config.APP_BASE_URL}/call-status",
        status_callback_method="POST",
        status_callback_event=["initiated", "ringing", "answered", "completed"],
        timeout=60
    )
    active_call_sid = call.sid
    print(f"[Twilio] Call placed to {candidate_name} ({to_phone})")
    print(f"[Twilio] Call SID: {call.sid}")
    return call.sid


@app.get("/twiml")
async def twiml_handler(request: Request):
    """
    Twilio calls this endpoint when the candidate picks up.
    We return TwiML that connects the call audio to our WebSocket.
    """
    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=f"wss://{request.headers.get('host')}/media-stream")
    stream.parameter(name="candidate_name", value=request.query_params.get("candidate_name", "Candidate"))
    connect.append(stream)
    response.append(connect)
    print("[Twilio] TwiML served — connecting call to WebSocket")
    return Response(content=str(response), media_type="application/xml")


@app.post("/call-status")
async def call_status(request: Request):
    """
    Twilio posts call status updates here.
    Log them so we can debug call flow.
    """
    form = await request.form()
    status = form.get("CallStatus", "unknown")
    sid = form.get("CallSid", "unknown")
    answered_by = form.get("AnsweredBy", "")
    print(f"[Twilio] Call {sid[:12]}... status: {status}" + (f" (answered_by: {answered_by})" if answered_by else ""))
    return Response(content="OK")


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    print("[WebSocket] Call connected — starting interview session")

    stream_sid = None
    params = {}

    async def send_audio_to_twilio(mulaw_bytes: bytes):
        """
        Streams audio chunks back to the candidate over Twilio.
        Each chunk is base64 encoded and sent as a media event.
        """
        chunks = synth.chunk_audio(mulaw_bytes)
        for chunk in chunks:
            audio_payload = base64.b64encode(chunk).decode("utf-8")
            await websocket.send_json({
                "event": "media",
                "streamSid": stream_sid,
                "media": {
                    "payload": audio_payload
                }
            })
            await asyncio.sleep(0.05)

    transcript_buffer = []
    response_task = None
    ai_is_speaking = False
    cooldown_until = 0.0

    IGNORE_PHRASES = [
        "let me think",
        "tell me about",
        "could you tell",
        "thank you for",
        "that is interesting",
        "great question",
    ]

    async def handle_transcript(text: str):
        import time
        nonlocal response_task, ai_is_speaking, cooldown_until

        if time.time() < cooldown_until:
            print(f"[Interview] Cooldown active — ignored: {text}")
            return

        if ai_is_speaking:
            print(f"[Interview] Ignored mid-speech transcript: {text}")
            return

        text_lower = text.lower()
        if any(phrase in text_lower for phrase in IGNORE_PHRASES):
            print(f"[Interview] Ignored echo: {text}")
            return

        print(f"[Candidate] {text}")
        transcript_buffer.append(text)

        if response_task and not response_task.done():
            response_task.cancel()
            print("[Interview] Debounce reset — waiting for more speech")

        async def delayed_response():
            nonlocal ai_is_speaking, cooldown_until
            try:
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                return

            if not transcript_buffer:
                return

            full_utterance = " ".join(transcript_buffer)
            transcript_buffer.clear()

            if len(full_utterance.split()) < 5:
                print(f"[Interview] Too short, waiting: '{full_utterance}'")
                return

            print(f"[Interview] Full utterance: {full_utterance}")

            ai_is_speaking = True
            try:
                if interviewer.is_complete:
                    return

                response_text = interviewer.generate_response(full_utterance)
                response_audio = synth.text_to_mulaw(response_text)
                await send_audio_to_twilio(response_audio)

                if interviewer.is_complete:
                    print("[Interview] Interview complete — closing call")
                    await asyncio.sleep(2)
                    twilio_client.calls.update(
                        sid=active_call_sid,
                        status="completed"
                    )
            finally:
                import time
                ai_is_speaking = False
                cooldown_until = time.time() + 1.2
                print("[Interview] AI finished speaking — 2s cooldown started")

        response_task = asyncio.create_task(delayed_response())

    resume_text = ""
    job_description = config.JOB_DESCRIPTION
    synth = VoiceSynthesiser()
    synth.get_filler_audio()  # pre-generate filler before call starts

    interviewer = Interviewer(
        resume_text=resume_text,
        job_description=job_description
    )

    async def on_interim():
        """Cancels the debounce timer when the candidate resumes speaking mid-sentence."""
        if response_task and not response_task.done():
            response_task.cancel()

    transcriber = Transcriber(on_transcript=handle_transcript, on_interim=on_interim)
    await transcriber.connect()

    try:
        async for message in websocket.iter_text():
            data = json.loads(message)
            event = data.get("event")

            if event == "connected":
                print("[WebSocket] Stream connected")

            elif event == "start":
                stream_sid = data["start"]["streamSid"]
                params = data["start"].get("customParameters", {})
                print(f"[WebSocket] Stream started — SID: {stream_sid}")

                opening = interviewer.get_opening_message()
                opening_audio = synth.text_to_mulaw(opening)
                await send_audio_to_twilio(opening_audio)
                print("[Interview] Opening message sent")

            elif event == "media":
                audio_payload = data["media"]["payload"]
                audio_bytes = base64.b64decode(audio_payload)
                await transcriber.send_audio(audio_bytes)

            elif event == "stop":
                print("[WebSocket] Stream stopped")
                break

    except WebSocketDisconnect:
        print("[WebSocket] Call ended by candidate")
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
        raise
    finally:
        await transcriber.disconnect()
        print("\n[Interview] Full transcript:")
        print(interviewer.get_full_transcript())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
