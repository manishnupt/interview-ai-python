from dataclasses import dataclass


@dataclass
class ScreeningResult:
    fit: bool
    score: int
    match_percentage: int
    fit_reasons: list[str]
    concerns: list[str]
    missing_skills: list[str]
    raw_json: str


@dataclass
class InterviewReport:
    score: int
    strengths: list[str]
    weaknesses: list[str]
    recommendation: str
    summary: str
    raw_json: str
    full_transcript: str = ""
