import json

from openai import OpenAI

import config
from models.result import InterviewReport

_SYSTEM_PROMPT = """
You are a senior technical recruiter evaluating a candidate based on a voice interview transcript.
Analyse the conversation and return ONLY a valid JSON object with this exact structure,
no preamble, no markdown, no explanation:

{
  "score": integer from 0 to 10,
  "strengths": ["strength 1", "strength 2"],
  "weaknesses": ["weakness 1", "weakness 2"],
  "recommendation": "hire" or "reject" or "consider",
  "summary": "2-3 sentence summary of the candidate's performance"
}

Scoring guide:
0-3: Poor — unable to answer basic questions
4-5: Weak — some relevant knowledge but significant gaps
6-7: Good — solid answers, meets most requirements
8-9: Strong — impressive answers, exceeds expectations
10: Outstanding — exceptional across all areas

recommendation must be exactly one of: "hire", "reject", "consider"
"""


class Reporter:
    def __init__(self):
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.model = "gpt-4o-mini"

    def generate(self, transcript: str, resume_text: str = "", job_description: str = "") -> InterviewReport:
        user_message = f"""INTERVIEW TRANSCRIPT:\n{transcript}"""
        if resume_text:
            user_message += f"\n\nCANDIDATE RESUME:\n{resume_text}"
        if job_description:
            user_message += f"\n\nJOB DESCRIPTION:\n{job_description}"
        user_message += "\n\nEvaluate this candidate and return the JSON verdict."

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        parsed = json.loads(raw)

        report = InterviewReport(
            score=parsed["score"],
            strengths=parsed.get("strengths", []),
            weaknesses=parsed.get("weaknesses", []),
            recommendation=parsed.get("recommendation", "consider"),
            summary=parsed.get("summary", ""),
            full_transcript=transcript,
            raw_json=raw,
        )
        print(f"[Reporter] Score: {report.score}/10 | Recommendation: {report.recommendation}")
        return report
