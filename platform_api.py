import asyncio
import threading
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()
import config

# ── Request / Response models ──────────────────────────

class ScreenRequest(BaseModel):
    candidate_id: int = Field(..., description="DB id from Spring Boot")
    resume_url: str = Field(..., description="S3 URL or direct PDF URL")
    job_description: str = Field(..., description="Full JD text")
    job_id: int = Field(..., description="Job DB id")
    company_id: int = Field(..., description="Company DB id")

class ScreenResponse(BaseModel):
    candidate_id: int
    fit: bool
    score: int
    match_percentage: int
    fit_reasons: list[str]
    concerns: list[str]
    missing_skills: list[str]

class InterviewRequest(BaseModel):
    candidate_id: int
    phone: str = Field(..., description="E.164 format e.g. +919876543210")
    candidate_name: str
    resume_url: str
    job_description: str
    job_id: int
    company_id: int

class InterviewTriggerResponse(BaseModel):
    candidate_id: int
    call_sid: str
    status: str = "initiated"

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str = "1.0.0"

# ── FastAPI app ─────────────────────────────────────────

app = FastAPI(
    title="AI Interview Platform — Python AI Service",
    description="Screening and voice interview AI endpoints",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080",
                   config.SPRING_BOOT_URL],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ── Endpoints ───────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        service="ai-interview-python"
    )


@app.post("/screen", response_model=ScreenResponse)
async def screen_resume(req: ScreenRequest):
    """
    Screens a resume against a job description.
    Called by Spring Boot pipeline orchestrator.
    Runs synchronously — Spring Boot awaits the result.
    """
    print(f"[Platform API] Screen request for candidate {req.candidate_id}")

    try:
        from screening.pdf_parser import PDFParser
        from screening.screener import Screener

        parser = PDFParser()
        resume_text = parser.extract_text(req.resume_url)

        if not parser.is_valid_pdf(resume_text):
            print(f"[Platform API] Could not extract resume text for {req.candidate_id}")
            raise HTTPException(
                status_code=422,
                detail="Could not extract text from resume PDF"
            )

        screener = Screener()
        result = screener.screen(resume_text, req.job_description)

        print(f"[Platform API] Screening complete: {result.score}/10 | fit={result.fit}")

        return ScreenResponse(
            candidate_id=req.candidate_id,
            fit=result.fit,
            score=result.score,
            match_percentage=result.match_percentage,
            fit_reasons=result.fit_reasons,
            concerns=result.concerns,
            missing_skills=result.missing_skills
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Platform API] Screening error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/interview", response_model=InterviewTriggerResponse)
async def trigger_interview(
    req: InterviewRequest,
    background_tasks: BackgroundTasks
):
    """
    Triggers an outbound AI voice interview call.
    Returns immediately with call_sid.
    The interview runs in the background.
    When complete, posts report back to Spring Boot.
    """
    print(f"[Platform API] Interview request for candidate {req.candidate_id}")

    call_sid = str(uuid.uuid4())

    background_tasks.add_task(
        run_interview_background,
        req=req,
        call_sid=call_sid
    )

    return InterviewTriggerResponse(
        candidate_id=req.candidate_id,
        call_sid=call_sid,
        status="initiated"
    )


async def run_interview_background(
    req: InterviewRequest,
    call_sid: str
):
    """
    Runs the full interview pipeline in the background.
    Places the call, waits for completion,
    then posts the report back to Spring Boot.
    """
    print(f"[Platform API] Starting background interview for {req.candidate_name}")

    try:
        from screening.pdf_parser import PDFParser
        from interview.dialer import place_call

        parser = PDFParser()
        resume_text = parser.extract_text(req.resume_url)

        real_call_sid = place_call(
            to_phone=req.phone,
            candidate_name=req.candidate_name,
            resume_text=resume_text,
            job_description=req.job_description,
            candidate_id=req.candidate_id
        )

        print(f"[Platform API] Call placed: {real_call_sid}")
        print(f"[Platform API] Waiting for interview to complete...")

        timeout = 900  # 15 min max
        elapsed = 0
        poll_interval = 10

        from interview.call_manager import interview_reports

        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            if real_call_sid in interview_reports:
                report = interview_reports[real_call_sid]
                print(f"[Platform API] Interview complete for {req.candidate_name}")
                await post_report_to_spring_boot(req, report, real_call_sid)
                return

            print(f"[Platform API] Still waiting... ({elapsed}s)")

        print(f"[Platform API] Interview timed out for {req.candidate_name}")
        await post_timeout_to_spring_boot(req, real_call_sid)

    except Exception as e:
        print(f"[Platform API] Interview background error: {e}")
        await post_error_to_spring_boot(req, str(e))


async def post_report_to_spring_boot(req, report, call_sid: str):
    """
    Posts the completed interview report back to Spring Boot.
    Spring Boot stores it and notifies HR.
    """
    payload = {
        "candidateId": req.candidate_id,
        "jobId": req.job_id,
        "companyId": req.company_id,
        "callSid": call_sid,
        "score": report.score,
        "strengths": report.strengths,
        "weaknesses": report.weaknesses,
        "recommendation": report.recommendation,
        "summary": report.summary,
        "fullTranscript": getattr(report, "full_transcript", ""),
        "rawJson": report.raw_json,
        "status": "completed"
    }

    spring_url = config.SPRING_BOOT_URL

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post(
                f"{spring_url}/api/callbacks/interview-complete",
                json=payload
            )
            print(f"[Platform API] Callback sent: {response.status_code}")
        except Exception as e:
            print(f"[Platform API] Callback failed: {e}")


async def post_timeout_to_spring_boot(req, call_sid: str):
    payload = {
        "candidateId": req.candidate_id,
        "jobId": req.job_id,
        "companyId": req.company_id,
        "callSid": call_sid,
        "status": "timeout"
    }
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(
                f"{config.SPRING_BOOT_URL}/api/callbacks/interview-complete",
                json=payload
            )
        except Exception as e:
            print(f"[Platform API] Timeout callback failed: {e}")


async def post_error_to_spring_boot(req, error: str):
    payload = {
        "candidateId": req.candidate_id,
        "jobId": req.job_id,
        "companyId": req.company_id,
        "status": "error",
        "errorMessage": error
    }
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(
                f"{config.SPRING_BOOT_URL}/api/callbacks/interview-complete",
                json=payload
            )
        except Exception as e:
            print(f"[Platform API] Error callback failed: {e}")


# ── Entry point ─────────────────────────────────────────

if __name__ == "__main__":
    import os
    port = int(os.getenv("PLATFORM_API_PORT", "8001"))
    print(f"[Platform API] Starting on port {port}")
    print(f"[Platform API] Spring Boot URL: {config.SPRING_BOOT_URL}")
    uvicorn.run(app, host="0.0.0.0", port=port)
