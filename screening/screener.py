import json
import time
from dotenv import load_dotenv

load_dotenv()

import openai
from openai import OpenAI

import config
from models.result import ScreeningResult

_SYSTEM_PROMPT = """
You are an expert technical recruiter. Given a job description
and a candidate resume, evaluate the candidate's fit.

Return ONLY a valid JSON object with this exact structure,
no preamble, no markdown, no explanation:
{
  "fit": true or false,
  "score": integer from 0 to 10,
  "match_percentage": integer from 0 to 100,
  "fit_reasons": ["reason 1", "reason 2"],
  "concerns": ["concern 1", "concern 2"],
  "missing_skills": ["skill 1", "skill 2"]
}

Scoring guide:
0-3: Poor fit, missing core requirements
4-5: Partial fit, has some but not all requirements
6-7: Good fit, meets most requirements
8-9: Strong fit, exceeds most requirements
10: Perfect fit, exceeds all requirements

fit should be true if score >= 6, false otherwise.
match_percentage is how much of the JD requirements the resume covers.
"""


class Screener:

    def __init__(self):
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.model = "gpt-4o-mini"

    def screen(self, resume_text: str, job_description: str) -> ScreeningResult:
        user_message = f"""
JOB DESCRIPTION:
{job_description}

CANDIDATE RESUME:
{resume_text}

Evaluate this candidate and return the JSON verdict.
"""
        response = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    max_tokens=1000,
                    response_format={"type": "json_object"},
                )
                break
            except openai.RateLimitError:
                if attempt < 2:
                    wait = 2 ** attempt
                    print(f"[Screener] Rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise
            except openai.APITimeoutError:
                if attempt < 2:
                    print(f"[Screener] Timeout, retrying (attempt {attempt+2}/3)...")
                else:
                    raise
            except openai.APIConnectionError:
                if attempt < 2:
                    print(f"[Screener] Connection error, retrying...")
                    time.sleep(1)
                else:
                    raise

        if response is None:
            raise RuntimeError("Screener failed after 3 attempts")

        raw = response.choices[0].message.content
        parsed = json.loads(raw)

        fit = parsed["fit"]
        score = parsed["score"]
        match_percentage = parsed["match_percentage"]

        print(f"[Screener] Score: {score}/10 | Match: {match_percentage}% | Fit: {fit}")

        return ScreeningResult(
            fit=fit,
            score=score,
            match_percentage=match_percentage,
            fit_reasons=parsed.get("fit_reasons", []),
            concerns=parsed.get("concerns", []),
            missing_skills=parsed.get("missing_skills", []),
            raw_json=raw,
        )


if __name__ == "__main__":
    import sys
    from screening.pdf_parser import PDFParser

    if len(sys.argv) < 2:
        print("Usage: python -m screening.screener <resume_url>")
        sys.exit(1)

    parser = PDFParser()
    resume_text = parser.extract_text(sys.argv[1])

    screener = Screener()
    result = screener.screen(resume_text, config.JOB_DESCRIPTION)

    print(f"Fit: {result.fit}")
    print(f"Score: {result.score}/10")
    print(f"Match: {result.match_percentage}%")
    print(f"Fit Reasons: {result.fit_reasons}")
    print(f"Concerns: {result.concerns}")
    print(f"Missing Skills: {result.missing_skills}")
