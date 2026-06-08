import json
import base64
import asyncio
import time
import traceback
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import config
from interview.providers import get_provider
from interview.transcriber import Transcriber
from interview.voice import VoiceSynthesiser
from interview.interviewer import Interviewer

provider = get_provider()
app = FastAPI()
app.include_router(provider.router)

# Keyed by call_sid — populated by dialer.place_call() before the WebSocket connects
active_call_data: dict = {}

# Keyed by call_sid — populated when an interview finishes, polled by platform_api
interview_reports: dict = {}


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    connect_time = time.time()
    print(f"[WebSocket] Incoming connection — headers: {dict(websocket.headers)}")
    print(f"[WebSocket] Query params: {dict(websocket.query_params)}")
    await websocket.accept()
    print(f"[WebSocket] Accepted — t=0.000s")

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
                debounce = 1.0 if interviewer and interviewer.interview_started else 0.8
                await asyncio.sleep(debounce)
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

                if not interviewer.identity_confirmed:
                    response_text = interviewer.handle_identity_response(
                        full_utterance
                    )
                elif not interviewer.interview_started:
                    response_text = interviewer.handle_availability_response(
                        full_utterance
                    )
                else:
                    response_text = interviewer.generate_response(full_utterance)
                response_audio = audio_cache.pop(response_text, None) or synth.text_to_mulaw(response_text)
                await send_audio_to_provider(response_audio)

                if interviewer.is_complete:
                    # Wait for audio to finish playing: streaming runs 4x real-time,
                    # so remaining playback = 3/4 of total duration + buffer.
                    playback_remaining = (len(response_audio) / 8000) * 0.75 + 0.8
                    print(f"[Interview] Interview complete — waiting {playback_remaining:.1f}s for audio to finish")
                    await asyncio.sleep(playback_remaining)
                    provider.end_call(call_id)
            finally:
                import time
                ai_is_speaking = False
                cooldown = 0.3 if not interviewer.interview_started else 1.2
                cooldown_until = time.time() + cooldown
                print(f"[Interview] AI finished speaking — {cooldown}s cooldown started")

        response_task = asyncio.create_task(delayed_response())

    resume_text = ""
    job_description = config.JOB_DESCRIPTION
    synth = VoiceSynthesiser()
    print(f"[WebSocket] Starting filler audio pre-gen — t={time.time()-connect_time:.3f}s")
    synth.get_filler_audio()
    print(f"[WebSocket] Filler audio ready — t={time.time()-connect_time:.3f}s (NOTE: this was a blocking call)")
    interviewer = None
    audio_cache: dict[str, bytes] = {}

    async def on_interim():
        if response_task and not response_task.done():
            response_task.cancel()

    transcriber = Transcriber(on_transcript=handle_transcript, on_interim=on_interim)

    print(f"[WebSocket] Entering message loop — t={time.time()-connect_time:.3f}s")
    try:
        async for message in websocket.iter_text():
            data = json.loads(message)
            event = data.get("event")

            if event == "connected":
                print(f"[WebSocket] Stream connected — full data: {data}")

            elif event == "start":
                start_data = data["start"]
                print(f"[WebSocket] START data: {json.dumps(start_data, indent=2)}")
                stream_sid = provider.extract_stream_sid(start_data)
                call_id = provider.extract_call_id(start_data)
                candidate_name = (
                    start_data.get("customParameters", {}).get("candidate_name")
                    or websocket.query_params.get("candidate_name", "there")
                )
                call_data = active_call_data.get(call_id, {})
                print(f"[WebSocket] active_call_data keys: {list(active_call_data.keys())}")
                print(f"[WebSocket] call_id lookup: '{call_id}' → found={bool(call_data)}")
                if call_data.get("resume_text"):
                    resume_text = call_data["resume_text"]
                if call_data.get("job_description"):
                    job_description = call_data["job_description"]
                interviewer = Interviewer(
                    resume_text=resume_text,
                    job_description=job_description,
                    candidate_name=candidate_name
                )
                print(f"[WebSocket] Stream started — SID: {stream_sid} | Call: {call_id} | Candidate: {candidate_name}")

                async def send_opening():
                    nonlocal ai_is_speaking, cooldown_until
                    t0 = time.time()
                    print(f"[Interview] send_opening() started — t={t0-connect_time:.3f}s from connect")
                    ai_is_speaking = True
                    try:
                        opening = interviewer.get_opening_message()
                        print(f"[Interview] Opening message: '{opening[:80]}...'")

                        print(f"[Interview] Calling ElevenLabs for opening TTS (BLOCKING) — t={time.time()-connect_time:.3f}s")
                        opening_audio = synth.text_to_mulaw(opening)
                        print(f"[Interview] Opening TTS done ({len(opening_audio)} bytes) — t={time.time()-connect_time:.3f}s")

                        loop = asyncio.get_event_loop()
                        availability_text = interviewer.get_availability_question()
                        print(f"[Interview] Pre-fetching availability TTS in executor")
                        prefetch = loop.run_in_executor(
                            None, synth.text_to_mulaw, availability_text
                        )

                        print(f"[Interview] Sending opening audio to provider — stream_sid={stream_sid}")
                        await send_audio_to_provider(opening_audio)
                        print(f"[Interview] Opening audio sent — t={time.time()-connect_time:.3f}s")

                        audio_cache[availability_text] = await prefetch
                        print("[Interview] Opening sent + availability audio pre-cached")
                    except Exception as e:
                        print(f"[Interview] ERROR in opening task: {e}")
                        traceback.print_exc()
                        raise
                    finally:
                        ai_is_speaking = False
                        cooldown_until = time.time() + 0.3

                asyncio.create_task(send_opening())

            elif event == "media":
                audio_bytes = base64.b64decode(data["media"]["payload"])
                await transcriber.send_audio(audio_bytes)

            elif event == "stop":
                print(f"[WebSocket] Stream stopped — t={time.time()-connect_time:.3f}s | full data: {data}")
                break

            else:
                print(f"[WebSocket] Unknown event '{event}' — data: {data}")

    except WebSocketDisconnect:
        print(f"[WebSocket] WebSocketDisconnect at t={time.time()-connect_time:.3f}s")
    except Exception as e:
        print(f"[WebSocket] Unhandled exception at t={time.time()-connect_time:.3f}s: {e}")
        traceback.print_exc()
        raise
    finally:
        await transcriber.disconnect()
        if interviewer is None:
            return
        transcript = interviewer.get_full_transcript()
        print("\n[Interview] Full transcript:")
        print(transcript)

        if interviewer.is_complete and call_id:
            try:
                from interview.reporter import Reporter
                import asyncio as _asyncio
                loop = _asyncio.get_event_loop()
                reporter = Reporter()
                report = await loop.run_in_executor(
                    None,
                    lambda: reporter.generate(
                        transcript=transcript,
                        resume_text=resume_text,
                        job_description=job_description,
                    )
                )
                interview_reports[call_id] = report
                print(f"[Interview] Report stored for call_id: {call_id}")
            except Exception as e:
                print(f"[Interview] Failed to generate report: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
