import json
import base64
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
import config
from interview.transcriber import Transcriber

app = FastAPI()
twilio_client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)

def place_call(to_phone: str, candidate_name: str) -> str:
    """
    Places an outbound Twilio call to the candidate.
    Returns the Twilio call SID.

    When the call connects, Twilio hits our /twiml endpoint
    which tells it to stream audio to our WebSocket.
    """
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
    print("[WebSocket] Twilio connected to media stream")

    stream_sid = None
    packet_count = 0
    transcripts = []

    async def on_transcript(text: str):
        transcripts.append(text)
        print(f"[Live] Candidate said: {text}")

    transcriber = Transcriber(on_transcript=on_transcript)
    await transcriber.connect()

    try:
        async for message in websocket.iter_text():
            data = json.loads(message)
            event = data.get("event")

            if event == "connected":
                print("[WebSocket] Stream connected")

            elif event == "start":
                stream_sid = data["start"]["streamSid"]
                print(f"[WebSocket] Stream started — SID: {stream_sid}")

            elif event == "media":
                packet_count += 1
                audio_payload = data["media"]["payload"]
                audio_bytes = base64.b64decode(audio_payload)
                await transcriber.send_audio(audio_bytes)

                if packet_count % 100 == 0:
                    print(f"[WebSocket] {packet_count} packets sent to Deepgram")

            elif event == "stop":
                print(f"[WebSocket] Stream stopped. Packets: {packet_count}")
                break

    except WebSocketDisconnect:
        print("[WebSocket] Twilio disconnected")
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
    finally:
        await transcriber.disconnect()
        print(f"\n[Session] Full transcript ({len(transcripts)} utterances):")
        for i, t in enumerate(transcripts, 1):
            print(f"  {i}. {t}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
