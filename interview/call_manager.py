import json
import base64
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import config
from interview.providers import get_provider
from interview.transcriber import Transcriber
from interview.voice import VoiceSynthesiser
from interview.interviewer import Interviewer

provider = get_provider()
app = FastAPI()
app.include_router(provider.router)


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    print("[WebSocket] Call connected — starting interview session")

    stream_sid = None
    call_id = None

    async def send_audio_to_provider(mulaw_bytes: bytes):
        await provider.send_full_audio(websocket, stream_sid, mulaw_bytes)

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

            if interviewer.interview_started and len(full_utterance.split()) < 5:
                print(f"[Interview] Too short, waiting: '{full_utterance}'")
                return

            print(f"[Interview] Full utterance: {full_utterance}")

            ai_is_speaking = True
            try:
                if interviewer.is_complete:
                    return

                if not interviewer.interview_started:
                    response_text = interviewer.handle_availability_response(
                        full_utterance
                    )
                else:
                    response_text = interviewer.generate_response(full_utterance)
                response_audio = synth.text_to_mulaw(response_text)
                await send_audio_to_provider(response_audio)

                if interviewer.is_complete:
                    print("[Interview] Interview complete — closing call")
                    await asyncio.sleep(2)
                    provider.end_call(call_id)
            finally:
                import time
                ai_is_speaking = False
                cooldown_until = time.time() + 1.2
                print("[Interview] AI finished speaking — 1.2s cooldown started")

        response_task = asyncio.create_task(delayed_response())

    resume_text = ""
    job_description = config.JOB_DESCRIPTION
    synth = VoiceSynthesiser()
    synth.get_filler_audio()
    interviewer = None

    async def on_interim():
        if response_task and not response_task.done():
            response_task.cancel()

    transcriber = Transcriber(on_transcript=handle_transcript, on_interim=on_interim)

    try:
        async for message in websocket.iter_text():
            data = json.loads(message)
            event = data.get("event")

            if event == "connected":
                print("[WebSocket] Stream connected")

            elif event == "start":
                start_data = data["start"]
                stream_sid = provider.extract_stream_sid(start_data)
                call_id = provider.extract_call_id(start_data)
                candidate_name = (
                    start_data.get("customParameters", {}).get("candidate_name")
                    or websocket.query_params.get("candidate_name", "there")
                )
                interviewer = Interviewer(
                    resume_text=resume_text,
                    job_description=job_description,
                    candidate_name=candidate_name
                )
                print(f"[WebSocket] Stream started — SID: {stream_sid} | Call: {call_id} | Candidate: {candidate_name}")

                async def send_opening():
                    import time
                    nonlocal ai_is_speaking, cooldown_until
                    ai_is_speaking = True
                    try:
                        opening = interviewer.get_opening_message()
                        opening_audio = synth.text_to_mulaw(opening)
                        await send_audio_to_provider(opening_audio)
                        print("[Interview] Opening message sent")
                    except Exception as e:
                        print(f"[Interview] ERROR in opening task: {e}")
                        raise
                    finally:
                        ai_is_speaking = False
                        cooldown_until = time.time() + 1.2

                asyncio.create_task(send_opening())

            elif event == "media":
                audio_bytes = base64.b64decode(data["media"]["payload"])
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
