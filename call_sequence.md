# Call Sequence — AI Interview Flow

## Overview

The system has two independent pipelines that share the same Python process:

- **Screening** — synchronous, Spring Boot waits for result.
- **Interview** — asynchronous, Spring Boot gets `call_sid` immediately and receives the report via callback when the call ends.

---

## 1. Screening Flow

```
Spring Boot                    platform_api.py               screener.py
    |                               |                              |
    |-- POST /screen --------------->|                              |
    |   { candidate_id, resume_url, |                              |
    |     job_description, ... }    |                              |
    |                               |-- PDFParser.extract_text() ->|
    |                               |<- resume_text ---------------|
    |                               |                              |
    |                               |-- Screener.screen() -------->|
    |                               |       (GPT-4o-mini call)     |
    |                               |<- ScreenResult --------------|
    |                               |                              |
    |<-- 200 ScreenResponse ---------|                              |
    |   { fit, score,               |                              |
    |     match_percentage, ... }   |
```

Spring Boot blocks until the result arrives (typically 2–5 seconds).

---

## 2. Interview Flow — High Level

```
Spring Boot          platform_api.py              dialer.py / Twilio     Candidate Phone
    |                      |                              |                     |
    |-- POST /interview --->|                              |                     |
    |                       |-- place_call() ------------->|                     |
    |                       |<- call_sid -----------------|                     |
    |<- 200 { call_sid } ---|                              |-- RING ------------>|
    |                       |                              |                     |
    |                       | [background thread]          |                     |
    |                       | pre-generate opening TTS     |                     |
    |                       | during ring time             |                     |
    |                       |                              |                     |
    |   (background task)   |<====== WebSocket media-stream ===================>|
    |                       |           (audio bridge, live call)                |
    |                       |                              |                     |
    |                       |-- POST /api/callbacks/interview-complete ---------->
    |<-- callback received  |
```

`platform_api.py` polls `interview_reports[call_sid]` every 10 seconds with a 15-minute timeout.

---

## 3. WebSocket Call Session — Detailed Sequence

Once Twilio/Plivo connects the candidate, it opens a WebSocket to `/media-stream`.

```
Twilio/Plivo                call_manager.py              interviewer.py
     |                            |                            |
     |-- event: "connected" ----->|                            |
     |                            |                            |
     |-- event: "start" --------->|                            |
     |   { stream_sid, call_sid,  |-- new Interviewer() ------>|
     |     customParameters }     |<- interviewer instance ----|
     |                            |                            |
     |                            | check active_call_data     |
     |                            | for pre-cached audio       |
     |                            |   ↓ ready → use instantly  |
     |                            |   ↓ miss  → call ElevenLabs|
     |                            |                            |
     |<-- audio: opening msg -----|  "Hello, am I speaking     |
     |   (near-zero delay if      |   with {name}?"            |
     |    pre-cache hit)          |                            |
     |                            | [availability TTS          |
     |                            |  pre-fetched in bg thread] |
     |                            |                            |
     |-- event: "media" (audio) ->|                            |
     |   (candidate speaking)     |-- Deepgram STT ----------->|
     |                            |<- transcript text ----------|
     |                            |                            |
     |                  [identity check — see §4]              |
     |                            |                            |
     |<-- audio: availability Q --|                            |
     |   "Is this a good time?"   |                            |
     |                            |                            |
     |-- event: "media" (audio) ->|                            |
     |   (candidate responds)     |-- Deepgram STT ----------->|
     |                            |<- transcript text ----------|
     |                            |                            |
     |                  [availability check — see §5]          |
     |                            |                            |
     |<-- audio: first question --|-- interview_started = True |
     |                            |   (stored in history)      |
     |                            |                            |
     |         ~~~ interview loop (up to 5 questions) ~~~      |
     |                            |                            |
     |-- event: "media" (audio) ->|                            |
     |   (candidate answers)      |-- Deepgram STT ----------->|
     |                            |<- transcript text ----------|
     |                            |                            |
     |                  [answer routing — see §6]              |
     |                            |                            |
     |<-- audio: next question ---|                            |
     |                            |                            |
     |         ~~~ repeats until question_count == 5 ~~~       |
     |                            |                            |
     |<-- audio: closing line ----|-- is_complete = True       |
     |                            |                            |
     |-- event: "stop" ---------->|                            |
     |   (call ended)             |-- transcriber.disconnect() |
     |                            |-- interviewer              |
     |                            |   .get_full_transcript()   |
     |                            |-- Reporter.generate()      |
     |                            |   (GPT-4o-mini scoring)    |
     |                            |-- interview_reports[sid]   |
     |                            |   = report                 |
```

### Opening audio pre-cache

`dialer.py` spawns a background thread the moment the call is placed. The thread generates
`"Hello, am I speaking with {name}?"` via ElevenLabs and stores the bytes in
`active_call_data[call_sid]["opening_audio"]`. The candidate typically takes 5–30 seconds
to answer (ring time), which is enough for the TTS to complete. When the WebSocket "start"
event fires, `call_manager.py` reads the cached bytes and sends them immediately — no
blocking ElevenLabs call on the hot path. If the candidate answers before the thread
finishes (rare), it falls back to generating on the spot.

---

## 4. Identity Confirmation Branch

AI asks: **"Hello, am I speaking with {name}?"**

```
Candidate reply
      |
      |-- repeat request? ─────────── YES ──> replay opening question
      |   (repeat / say that again /           "Hello, am I speaking with {name}?"
      |    pardon / phir se / dobara)          [no state change]
      |
      |-- contains positive word? ──── YES ──> identity_confirmed = True
      |   (yes / yeah / speaking /             return availability question
      |    that's me / haan / ji)
      |
      |-- contains negative word? ──── YES ──> is_complete = True
      |   (no / wrong number / nahi)            return "Sorry for the confusion. Goodbye."
      |                                          [call ends]
      |
      └── neither ──────────────────────────>  ask again:
                                               "Sorry, just to confirm — am I speaking with {name}?"
```

---

## 5. Availability Check Branch

AI asks: **"Is this a good time to speak for about 10 minutes?"**

Evaluation order matters — each check runs only if the ones above it did not match.

```
Candidate reply
      |
      |-- reschedule_pending == True? ── YES ──> repeat request?
      |   (we already asked for a time)               |
      |                                               |-- YES ──> replay "What time is convenient?"
      |                                               |           [no state change]
      |                                               |
      |                                               └── NO  ──> extract time phrase
      |                                                           confirm reschedule
      |                                                           is_complete = True
      |                                                           [call ends]
      |
      |-- repeat request? ─────────────── YES ──> replay availability question
      |   (repeat / say again / pardon)              "Is this a good time to speak?"
      |                                              [no state change]
      |
      |-- unavailability / reschedule? ── YES ──> does reply contain a time phrase?
      |   (reschedule / call me back /                   |
      |    not a good time / busy /                      |-- YES ──> confirm reschedule time
      |    driving / in a meeting /                      |           is_complete = True
      |    on a call / in a call /                       |           [call ends]
      |    can't talk / cannot talk /                    |
      |    in traffic / not free /                       └── NO  ──> reschedule_pending = True
      |    baad mein / phir karo)                                    ask "What time is convenient?"
      |                                                              [waits for next reply → confirm]
      |
      |-- negative word? ──────────────── YES ──> is_complete = True
      |   (no / not now / nahi)                    return "We will reach out to reschedule. Goodbye."
      |                                             [call ends]
      |
      |-- positive word? ──────────────── YES ──> interview_started = True
      |   (yes / yeah / sure / okay /               generate first question
      |    ok / yep / go ahead /                    append to conversation_history
      |    absolutely / of course /                 return "Perfect. Let us get started. {Q1}"
      |    lets go / haan / bilkul /
      |    theek hai)
      |
      └── unclear ───────────────────────────>  ask again:
                                               "Is this a good time to proceed?"
```

**Note on removed positive words:** `"fine"`, `"ready"`, `"start"`, `"begin"`, `"please"`,
`"proceed"` were removed from the positive list because they appear naturally in
unavailability sentences (e.g. *"I'm driving, it's fine"*, *"start calling me later"*).
The unavailability check runs before the positive check, so phrases like
*"I'm driving but okay"* are still caught correctly via the keyword list.

---

## 6. Answer Routing During Interview

Called by `generate_response()` for every candidate utterance after `interview_started = True`.

```
Candidate utterance
      |
      |-- repeat request? ─────────── YES ──> replay _last_question
      |   (repeat / say that again /           "Of course. {last_question}"
      |    pardon / phir se)                   [no turn consumed]
      |
      |-- reschedule request? ─────── YES ──> same branch as §5 reschedule
      |
      |-- don't-know / skip? ──────── YES ──> question_count += 1
      |   (don't know / no idea /              play skip filler
      |    blank / pass / nahi pata)           |
      |                                        |-- question_count >= 5? ──> closing message
      |                                        |                            is_complete = True
      |                                        |                            [call ends]
      |                                        |
      |                                        └── else ──> _generate_next_question()
      |                                                     (GPT on different topic)
      |
      |-- answer too short? ────────── YES ──> ask to elaborate
      |   (< 5 words OR < 4 non-filler)        "Could you tell me a bit more about that?"
      |                                         [no turn consumed]
      |
      └── sufficient answer ──────────────>  append to conversation_history
                                             question_count += 1
                                             GPT generates next question
                                             |
                                             |-- OFF_TOPIC response? ──> undo increment
                                             |                           redirect to interview
                                             |
                                             |-- INTERVIEW_COMPLETE? ──> is_complete = True
                                             |   (after Q5)               strip sentinel
                                             |                            play closing line
                                             |                            [call ends]
                                             |
                                             └── normal ──> prepend filler phrase
                                                            extract topic → covered_topics
                                                            append to conversation_history
                                                            play question audio
```

---

## 7. Call Teardown

```
WebSocket "stop" event OR WebSocketDisconnect
      |
      |-- transcriber.disconnect()      (close Deepgram connection)
      |
      |-- interviewer.get_full_transcript()
      |   Formats conversation_history as:
      |     Interviewer: "Perfect. Let us get started. {Q1}"   ← first turn recorded on start
      |     Candidate:   {answer 1}
      |     Interviewer: {filler + Q2}
      |     ...
      |
      |-- is_complete == True?
      |       |
      |       YES ──> Reporter.generate(transcript, resume, jd)
      |               GPT-4o-mini returns:
      |                 { score, strengths, weaknesses,
      |                   recommendation, summary }
      |               store in interview_reports[call_sid]
      |
      |       NO  ──> skip report (call dropped or identity rejected)
      |
      └── platform_api background task picks up interview_reports[call_sid]
          POST /api/callbacks/interview-complete → Spring Boot
          payload: { candidateId, jobId, score, transcript, recommendation, ... }
```

---

## 8. Timeout / Error Callbacks

| Situation | Callback payload to Spring Boot |
|---|---|
| Interview completed normally | `status: "completed"` + full report fields |
| Call never completes within 15 min | `status: "timeout"` |
| Exception in background task | `status: "error"` + `errorMessage` |

---

## 9. Debounce & Audio Gating

To prevent the AI from cutting in while the candidate is still speaking:

- **Deepgram interim results** cancel the pending `delayed_response` task, resetting the debounce timer.
- **Debounce delay**: 1.0 s once the interview is running, 0.8 s during pre-interview exchanges.
- **`ai_is_speaking` flag**: any transcript that arrives while the AI is playing audio is discarded entirely.
- **`cooldown_until`**: after AI finishes speaking, a 1.2 s cooldown (0.3 s pre-interview) ignores any transcript — prevents echo or mic bleed from the AI's own voice being picked up.
- **Echo phrase filter**: a fixed list of AI-like phrases (`"let me think"`, `"great question"`, etc.) are dropped even if Deepgram transcribes them.

---

## 10. Repeat Request Handling (all phases)

The same `is_repeat_request()` method is used across all three phases of the call.
It matches phrases in English and Hindi (e.g. `repeat`, `say that again`, `pardon`,
`phir se`, `dobara`, `ek baar`).

| Phase | What gets replayed | State change |
|---|---|---|
| Identity confirmation | `"Hello, am I speaking with {name}?"` | None |
| Availability check | `"Is this a good time to speak for about 10 minutes?"` | None |
| Reschedule pending | `"What time would be convenient for you?"` | None |
| Live interview | `"Of course. {last_question}"` | None |

No turn is consumed in any case — the question counter does not increment.
