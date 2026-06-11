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
     |                            |   hit  → use instantly     |
     |                            |   miss → call ElevenLabs   |
     |                            |                            |
     |<-- audio: opening msg -----|  "Hello, am I speaking     |
     |   (near-zero delay on hit) |   with {name}?"            |
     |                            |                            |
     |                            | [availability TTS          |
     |                            |  pre-fetched in bg thread] |
     |                            |                            |
     |-- event: "media" (audio) ->|                            |
     |   (candidate speaking)     |-- Deepgram STT ----------->|
     |                            |<- transcript text ----------|
     |                            |                            |
     |            [echo filter applied first — see §A]         |
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
     |            [echo filter applied first — see §A]         |
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
     |            [echo filter applied first — see §A]         |
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
`active_call_data[call_sid]["opening_audio"]`. When the WebSocket "start" event fires,
`call_manager.py` reads the cached bytes and sends them immediately. If the candidate
answers before the thread finishes (rare), it falls back to generating on the spot.

---

## §A. Echo Filter (applied before every transcript handler)

Any transcript that contains one of these phrases is **silently dropped** — they are
AI-generated phrases that sometimes get picked up by the mic:

| Phrase |
|---|
| `"let me think"` |
| `"tell me about"` |
| `"could you tell"` |
| `"thank you for"` |
| `"that is interesting"` |
| `"great question"` |

---

## §B. Repeat Request Detection (used in all phases)

`is_repeat_request()` returns true if the transcript contains **any** of these phrases:

| English | Hindi |
|---|---|
| `"repeat"` | `"phir se"` |
| `"say that again"` | `"dobara"` |
| `"say again"` | `"ek baar"` |
| `"come again"` | `"samajh nahi"` |
| `"pardon"` | `"sunayi nahi"` |
| `"what was that"` | |
| `"didn't catch"` | |
| `"didn't hear"` | |
| `"couldn't hear"` | |
| `"didn't get"` | |
| `"didn't understand"` | |
| `"don't understand"` | |
| `"not clear"` | |
| `"not getting"` | |
| `"can you say"` | |
| `"could you say"` | |
| `"what did you say"` | |
| `"once more"` | |
| `"one more time"` | |

---

## §C. Reschedule / Unavailability Detection (used in availability + live interview)

`_is_reschedule_request()` returns true if the transcript contains **any** of these:

| Reschedule intent | Physically unavailable |
|---|---|
| `"reschedule"` | `"driving"` |
| `"re-schedule"` | `"in a meeting"` |
| `"call back"` | `"in a call"` |
| `"call me back"` | `"on a call"` |
| `"another time"` | `"can't talk"` |
| `"different time"` | `"cannot talk"` |
| `"some other time"` | `"can't speak"` |
| `"other time"` | `"cannot speak"` |
| `"not a good time"` | `"in traffic"` |
| `"bad time"` | `"behind the wheel"` |
| `"busy"` | `"not free"` |
| `"schedule later"` | `"tied up"` |
| `"convenient time"` | |
| `"baad mein"` | |
| `"baad me"` | |
| `"phir karo"` | |

When matched, GPT-4o-mini is also called to extract any time phrase from the reply
(e.g. `"tomorrow 3pm"`, `"Monday morning"`). If a time is found the call ends with
a confirmation; if not, `reschedule_pending = True` and the AI asks for a time.

**Time hint words used as fallback** (if GPT returns empty):
`today · tomorrow · yesterday · monday–sunday · morning · afternoon · evening · night ·
next · week · month · am · pm · o'clock · kal · parso · aaj · subah · shaam · hour · minute`

---

## 4. Identity Confirmation Branch

AI says: **"Hello, am I speaking with {name}?"**

```
Candidate reply
      |
      |-- repeat request? (§B) ────── YES ──> replay "Hello, am I speaking with {name}?"
      |                                        [no state change]
      |
      |-- negative word? ──────────── YES ──> is_complete = True
      |                                        "I'm sorry for the confusion. Have a good day."
      |                                        [call ends]
      |
      |   NEGATIVE WORDS:
      |     "no"  "wrong number"  "not"  "nahi"  "nhi"
      |
      |-- positive word? ──────────── YES ──> identity_confirmed = True
      |                                        return availability question
      |
      |   POSITIVE WORDS:
      |     "yes"  "yeah"  "yep"  "yup"  "speaking"  "this is"
      |     "that's me"  "thats me"  "i am"  "i'm"
      |     "haan"  "han"  "ji"
      |
      └── neither ───────────────────────>  ask again:
                                            "Sorry, just to confirm —
                                             am I speaking with {name}?"
```

---

## 5. Availability Check Branch

AI asks: **"Is this a good time to speak for about 10 minutes?"**

Checks run in this exact order — first match wins.

```
Candidate reply
      |
      |── reschedule_pending == True? ─ YES ──> repeat request? (§B)
      |   (already asked for a time)                 |
      |                                              |── YES ──> replay "What time is convenient?"
      |                                              |           [no state change]
      |                                              |
      |                                              └── NO  ──> GPT extracts time phrase
      |                                                          confirm reschedule → call ends
      |
      |── repeat request? (§B) ──────── YES ──> replay "Is this a good time to speak
      |                                          for about 10 minutes?"
      |                                          [no state change]
      |
      |── reschedule / unavailable? ─── YES ──> see §C
      |   (§C keyword matched)                   GPT extracts time phrase
      |                                          |── time found ──> confirm + call ends
      |                                          └── no time ───> reschedule_pending = True
      |                                                            "What time is convenient?"
      |
      |── negative word? ─────────────── YES ──> is_complete = True
      |                                           "We will reach out to reschedule. Goodbye."
      |                                           [call ends]
      |
      |   NEGATIVE WORDS:
      |     "no"  "not now"  "later"  "cant"  "cannot"
      |     "nahi"  "nhi"  "abhi nahi"
      |
      |── positive word? ─────────────── YES ──> interview_started = True
      |                                           generate first question
      |                                           append to conversation_history
      |                                           "Perfect. Let us get started. {Q1}"
      |
      |   POSITIVE WORDS:
      |     "yes"  "yeah"  "sure"  "okay"  "ok"  "yep"
      |     "go ahead"  "good time"  "absolutely"  "of course"
      |     "lets go"  "let's go"
      |     "haan"  "han"  "bilkul"  "theek"  "theek hai"
      |
      └── unclear ────────────────────────────>  "Sorry, I missed that.
                                                  Is this a good time to proceed?"
```

---

## 6. Answer Routing During Interview

Called by `generate_response()` for every utterance after `interview_started = True`.

```
Candidate utterance
      |
      |── repeat request? (§B) ──────── YES ──> "Of course. {last_question}"
      |                                          [no turn consumed]
      |
      |── reschedule / unavailable? ─── YES ──> see §C  (same flow as §5 reschedule)
      |   (§C keyword matched)
      |
      |── don't-know / skip? ──────────  YES ──> question_count += 1
      |                                           play skip filler
      |                                           |── count >= 5 ──> closing + call ends
      |                                           └── else ──────> GPT: new topic question
      |
      |   DON'T-KNOW PHRASES:
      |     "don't know"  "dont know"  "do not know"  "not aware"  "not sure"
      |     "no idea"  "i forgot"  "can't remember"  "cannot remember"
      |     "cant remember"  "i forget"  "not familiar"  "never used"
      |     "never worked"  "no experience with"  "haven't used"  "havent used"
      |     "not worked on"  "not worked with"  "blank"  "skip"
      |     "next question"  "pass"
      |     "nahi pata"  "nahi malum"  "pata nahi"  "malum nahi"  "yaad nahi"
      |
      |── answer too short? ─────────── YES ──> "Could you tell me a bit more about that?"
      |                                          [no turn consumed]
      |
      |   SHORT ANSWER RULE:
      |     total words < 5  OR  non-filler words < 4
      |     filler words ignored: yes · no · okay · ok · sure · yeah · um · uh · hmm · right · fine
      |
      └── sufficient answer ─────────────────> append to conversation_history
                                               question_count += 1
                                               GPT generates next question
                                               |
                                               |── OFF_TOPIC ──> undo increment, redirect
                                               |── INTERVIEW_COMPLETE ──> closing + call ends
                                               └── normal ──> filler + question + topic logged
```

---

## 7. Call Teardown

```
WebSocket "stop" event OR WebSocketDisconnect
      |
      |── transcriber.disconnect()     (close Deepgram connection)
      |
      |── interviewer.get_full_transcript()
      |   Formats conversation_history as:
      |     Interviewer: "Perfect. Let us get started. {Q1}"
      |     Candidate:   {answer 1}
      |     Interviewer: {filler + Q2}
      |     ...
      |
      |── is_complete == True?
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
- **Echo phrase filter**: see §A — AI-like phrases are dropped before any handler runs.

---

## 10. Repeat Request Handling — Summary Table

| Phase | What gets replayed | State change |
|---|---|---|
| Identity confirmation | `"Hello, am I speaking with {name}?"` | None |
| Availability check | `"Is this a good time to speak for about 10 minutes?"` | None |
| Reschedule pending | `"What time would be convenient for you?"` | None |
| Live interview | `"Of course. {last_question}"` | None |

No turn is consumed in any case — `question_count` does not increment.
