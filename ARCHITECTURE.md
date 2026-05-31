# AI Interview Pipeline — Full Project Documentation

---

## Overview

This system is a fully automated, end-to-end AI hiring pipeline. It reads candidate data from a Google Sheet, screens each resume against a job description using GPT, and — if the candidate is a fit — places a live phone call and conducts a real-time voice interview with no human involvement.

The pipeline has two distinct phases:

- **Phase 1 — Screening** (`main.py`): batch job, runs on demand
- **Phase 2 — Interview** (`interview/`): real-time, runs as a long-lived FastAPI server

---

## Tech Stack

| Layer | Tool | Purpose |
|---|---|---|
| Resume source | Google Sheets + Google Drive | Candidate list and resume storage |
| PDF parsing | `pdfplumber` + `httpx` | Extract text from resume PDFs |
| Resume screening | OpenAI GPT-4o-mini | Score candidate fit against JD |
| Call provider | Plivo or Twilio (switchable) | Outbound phone call + audio streaming |
| Speech-to-text | Deepgram Nova-2 | Live transcription of candidate speech |
| AI interviewer | OpenAI GPT-4o-mini | Generate dynamic interview questions |
| Text-to-speech | ElevenLabs Flash v2.5 | Synthesise interviewer voice |
| Web server | FastAPI + Uvicorn | WebSocket server for real-time audio |
| Config | `.env` + `python-dotenv` | API keys and environment config |

---

## Project Structure

```
ai-codegen/
│
├── main.py                        # Phase 1 entry point — batch screening loop
├── config.py                      # All env vars, JD text, thresholds
├── run_log.txt                    # Appended after each pipeline run
│
├── models/
│   ├── candidate.py               # Candidate dataclass (name, phone, email, resume_url)
│   └── result.py                  # ScreeningResult + InterviewReport dataclasses
│
├── sheets/
│   ├── base.py                    # Google Sheets auth and connection
│   ├── reader.py                  # Read pending candidates from Sheet
│   └── writer.py                  # Write screening results + interview reports
│
├── screening/
│   ├── pdf_parser.py              # Download + extract text from resume PDFs
│   └── screener.py                # GPT-based resume scorer
│
└── interview/
    ├── dialer.py                  # Thin wrapper — delegates to active provider
    ├── call_manager.py            # FastAPI WebSocket server — real-time call loop
    ├── interviewer.py             # GPT interview brain + all state
    ├── transcriber.py             # Deepgram streaming STT client
    ├── voice.py                   # ElevenLabs TTS → mulaw audio
    └── providers/
        ├── __init__.py            # Provider singleton factory
        ├── base.py                # Abstract CallProvider interface
        ├── plivo_provider.py      # Plivo implementation
        └── twilio_provider.py     # Twilio implementation
```

---

## Phase 1 — Screening Pipeline (`main.py`)

### How it runs

```bash
python main.py              # Full run
python main.py --dry-run    # Simulate without API calls or Sheet writes
python main.py --reset      # Clear all screening columns and exit
```

### Step-by-step flow

```
Google Sheet
     │
     ▼
SheetReader.get_pending_candidates()
     │  reads rows where Status column (col E) is blank
     ▼
For each Candidate:
     │
     ├─► PDFParser.extract_text(resume_url)
     │       converts Drive/Dropbox/direct URLs → raw PDF bytes
     │       extracts text with pdfplumber
     │
     ├─► Screener.screen(resume_text, JOB_DESCRIPTION)
     │       sends resume + JD to GPT-4o-mini
     │       receives JSON: { fit, score, match_percentage,
     │                        fit_reasons, concerns, missing_skills }
     │       fit = True if score >= SCREENING_FIT_THRESHOLD (default 3)
     │
     ├─► SheetWriter.write_screening(candidate, result)
     │       writes score, fit verdict, reasons, concerns to cols E–I
     │
     └─► if fit:
             dialer.place_call(phone, name)
                 → triggers Phase 2
             SheetWriter.mark_status("Interview Scheduled")
         else:
             SheetWriter.mark_no_fit()  → "Rejected"
```

### Google Sheet column layout

| Col | Field | Written by |
|---|---|---|
| A | Name | Input |
| B | Phone | Input |
| C | Email | Input |
| D | Resume URL | Input |
| E | Status | Writer (Screened / Interviewed / Rejected / Error) |
| F | Score | Writer (e.g. `7/10 (82%)`) |
| G | Fit verdict | Writer (Fit / No Fit) |
| H | Fit reasons | Writer |
| I | Concerns | Writer |
| J | Interview score | Writer (post-interview) |
| K | Strengths | Writer |
| L | Weaknesses | Writer |
| M | Summary | Writer |

---

## Phase 2 — Live Voice Interview (`interview/`)

### Architecture

The interview is a **real-time bidirectional audio pipeline** over WebSockets:

```
Candidate's phone
       │  (PSTN)
       ▼
Plivo / Twilio
       │  (WebSocket — mulaw 8kHz audio stream)
       ▼
FastAPI /media-stream  (call_manager.py)
       │
       ├──► Transcriber (Deepgram)        audio bytes → text
       │
       ├──► Interviewer (GPT-4o-mini)     text → next question text
       │
       └──► VoiceSynthesiser (ElevenLabs) text → mulaw audio bytes
                                                │
                                                ▼
                                    back to Plivo/Twilio → candidate's phone
```

### Provider selection

`CALL_PROVIDER` env var controls which telephony provider loads at startup:

```
CALL_PROVIDER=plivo   → PlivoProvider
CALL_PROVIDER=twilio  → TwilioProvider  (default)
```

Both implement the same `CallProvider` abstract interface (`providers/base.py`):
`place_call`, `end_call`, `send_full_audio`, `extract_stream_sid`, `extract_call_id`.

### Call initiation flow

**Twilio path:**
1. `dialer.place_call()` → Twilio REST API creates outbound call with `url=/twiml?candidate_name=...`
2. Twilio calls the candidate, then fetches `/twiml` from the server
3. TwiML response tells Twilio to open a WebSocket to `/media-stream?candidate_name=...`
4. WebSocket opens → `call_manager.media_stream()` takes over

**Plivo path:**
1. `dialer.place_call()` → Plivo REST API creates outbound call with `answer_url=/plivo-answer?candidate_name=...`
2. Plivo calls the candidate, then fetches `/plivo-answer`
3. XML response contains `<Stream>` pointing to `wss://.../media-stream?candidate_name=...`
4. WebSocket opens → same `call_manager.media_stream()` takes over

### WebSocket event loop (`call_manager.py`)

The FastAPI WebSocket handler receives a stream of JSON events:

```
event: "connected"  → log only

event: "start"      → extract stream_sid, call_id, candidate_name
                       create Interviewer instance
                       synthesise and send opening message

event: "media"      → decode base64 audio payload
                       send raw bytes to Deepgram

event: "stop"       → break loop, print transcript
```

### Debounce and cooldown system

The call manager has two guards to prevent the AI from interrupting itself or responding to mid-sentence fragments:

- **Debounce** — every new interim transcript resets a 1-second timer. GPT is only called once the candidate has been silent for 1 full second.
- **Cooldown** — after the AI finishes speaking, a 1.2-second cooldown blocks incoming transcripts. Prevents the AI's own voice from triggering a response.
- **Word-count gate** — after `interview_started`, utterances under 5 words are discarded as noise. Bypassed before the interview starts so "Yes" correctly triggers availability confirmation.

### Interview state machine (`interviewer.py`)

```
Call connects
     │
     ▼
get_opening_message()
"Hello, am I speaking with [name]? This is a telephonic
 interview round... Is this a good time?"
     │
     ▼  (candidate's first reply)
handle_availability_response(text)
     │
     ├─ negative keyword (no / busy / nahi) ──► goodbye, is_complete = True
     │
     ├─ positive keyword (yes / sure / haan) ──► interview_started = True
     │                                            _generate_first_question()
     │                                            "Perfect. Let us get started. [Q1]"
     │
     └─ no match ──► "Sorry, I missed that. Is this a good time?"

     │  (each subsequent candidate reply)
     ▼
generate_response(text)
     │
     ├─ is_dont_know_response() → True
     │       skip filler + _generate_next_question() on different topic
     │       question_count += 1
     │       if count >= 5 → is_complete = True, closing line
     │
     ├─ is_sufficient_answer() → False
     │       "Could you tell me a bit more about that?"
     │       (question_count not incremented)
     │
     └─ normal answer
             append to conversation_history
             question_count += 1
             call GPT with _build_system_prompt()
             │
             ├─ GPT returns INTERVIEW_COMPLETE
             │       is_complete = True, return closing line
             │
             └─ normal question returned
                     _get_filler() → non-repeating prefix ("Got it.", "Alright.", ...)
                     reply = f"{filler} {question}"
                     _extract_topic(question) → 3-word label → covered_topics
                     append reply to conversation_history

     │
     ▼  (call_manager checks is_complete after each response)

is_complete = True
     │
     ▼
asyncio.sleep(2) → provider.end_call(call_id)
print get_full_transcript()
```

### GPT system prompt strategy (`_build_system_prompt`)

The prompt is rebuilt dynamically before every GPT call. It injects:

1. **`covered_topics`** — list of 3-word topic labels already asked (e.g. "REST API design", "database indexing") so GPT cannot revisit them
2. **`job_description`** — full JD text to anchor all questions
3. **`resume_text[:3000]`** — candidate's resume to calibrate difficulty
4. **`question_count` of 5** — progress counter so GPT knows when to close

The prompt instructs GPT to follow a 5-step selection process: read JD → read resume → find gap → pick uncovered topic → ask calibrated question. It also specifies 5 question types to rotate through: Concept, Situational, Design, Trade-off, Tool-specific.

---

## Audio Pipeline Detail

```
ElevenLabs TTS
     │  PCM 8kHz (pcm_8000 format)
     ▼
audioop.lin2ulaw()
     │  mulaw 8kHz — phone-compatible encoding
     ▼
Provider.send_full_audio()
     │  Plivo: 640-byte chunks, 20ms apart
     │  Twilio: base64-encoded JSON { event: "media", ... }
     ▼
Candidate's handset speaker

Candidate speaks
     ▼
Provider streams mulaw audio bytes over WebSocket
     ▼
Transcriber.send_audio(bytes) → Deepgram Nova-2
     │  model: nova-2, encoding: mulaw, sample_rate: 8000
     │  interim_results: True (triggers debounce reset)
     │  endpointing: 600ms, utterance_end_ms: 1200ms
     ▼
on_transcript(text) callback → handle_transcript() in call_manager
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | GPT-4o-mini — screening + interviewing |
| `ELEVENLABS_API_KEY` | Yes | Voice synthesis |
| `DEEPGRAM_API_KEY` | Yes | Live speech-to-text |
| `APP_BASE_URL` | Yes | Public HTTPS URL of this server (ngrok or prod) |
| `GOOGLE_SHEET_ID` | Yes | Google Sheet with candidate data |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Yes* | Service account JSON (or `service_account.json` file) |
| `CALL_PROVIDER` | No | `"plivo"` or `"twilio"` (default: twilio) |
| `TWILIO_ACCOUNT_SID` | Twilio | — |
| `TWILIO_AUTH_TOKEN` | Twilio | — |
| `TWILIO_PHONE_NUMBER` | Twilio | — |
| `PLIVO_AUTH_ID` | Plivo | — |
| `PLIVO_AUTH_TOKEN` | Plivo | — |
| `PLIVO_PHONE_NUMBER` | Plivo | — |
| `SCREENING_FIT_THRESHOLD` | No | Min score to pass screening (default: 3) |

---

## Key Design Decisions

**Why GPT-4o-mini everywhere?** Fast enough for real-time use (sub-2s latency for short prompts), cheap, and more than capable for single-question generation and JSON scoring.

**Why rebuild the system prompt on every turn?** `covered_topics` and `question_count` change after each turn. Rebuilding ensures GPT always has an accurate picture of what's been asked and how far through the interview we are.

**Why `_extract_topic` as a separate GPT call?** Parsing topics from full question text inline in the prompt is unreliable. A dedicated call with `temperature=0` and `max_tokens=10` returns a deterministic 3-word label every time.

**Why Deepgram `interim_results: True`?** Interim transcripts cancel the debounce timer so the AI doesn't respond while the candidate is mid-sentence. Only `is_final: True` results are sent to the interview logic.

**Why mulaw 8kHz?** PSTN phone calls run at 8kHz mulaw. Both Plivo and Twilio stream audio in this format. ElevenLabs outputs PCM which is converted to mulaw with `audioop.lin2ulaw` before sending back to the provider.

**Why is the filler audio pre-generated at startup?** `VoiceSynthesiser.get_filler_audio()` is called once when the WebSocket connects. This means a "Let me think..." placeholder is always ready to play instantly without a TTS round-trip — though the current flow sends GPT-generated fillers as prefixes to questions rather than playing this pre-baked audio.
