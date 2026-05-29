Create the CLAUDE.md file at the project root with this exact content:

# AI Interview POC

## What this project does
Python pipeline that reads candidates from Google Sheets,
screens resumes with Claude Haiku, then conducts live phone
interviews using Twilio + Deepgram STT + Claude Haiku +
ElevenLabs TTS. Results are written back to the same Google Sheet.

## Tech stack
- Python 3.11+
- anthropic SDK — model: claude-haiku-4-5 (in-call), claude-sonnet-4-6 (reports only)
- ElevenLabs Flash model for TTS (low latency)
- Deepgram Nova-3 for real-time STT
- Twilio Programmable Voice + WebSocket media streams
- gspread + oauth2client for Google Sheets
- pdfplumber + httpx for resume download and extraction
- FastAPI + uvicorn for WebSocket server
- python-dotenv for env vars

## Folder structure
- config.py          → API keys + hardcoded JD
- main.py            → entry point
- sheets/reader.py   → reads candidates from Sheet
- sheets/writer.py   → writes results back to Sheet
- screening/         → PDF parser + Claude screener
- interview/         → Twilio, Deepgram, Haiku, ElevenLabs
- models/candidate.py → Candidate dataclass
- models/result.py   → ScreeningResult + InterviewReport dataclasses

## Hard rules
- ALWAYS use claude-haiku-4-5 for in-call logic and screening
- ONLY use claude-sonnet-4-6 in reporter.py for final reports
- ALWAYS enable prompt caching on system prompt + JD in every Anthropic API call
- ALWAYS use ElevenLabs Flash model, never Multilingual v2
- ALWAYS use Deepgram Nova-3 streaming endpoint, never batch
- NEVER hardcode API keys — always read from config.py
- ALWAYS validate Claude JSON output before writing to Sheet
- ALWAYS write results back to Sheet before processing next candidate

## Google Sheet column order (1-indexed)
1: Name
2: Phone
3: Email
4: Resume URL
5: Status
6: Screening Score
7: Screening Verdict
8: Fit Reasons
9: Concerns
10: Interview Score
11: Strengths
12: Weaknesses
13: Summary

## Commands
pip install -r requirements.txt
python main.py
python main.py --dry-run
uvicorn interview.call_manager:app --port 8000
ngrok http 8000