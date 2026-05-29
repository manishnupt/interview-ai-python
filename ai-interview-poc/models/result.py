from dataclasses import dataclass, field


@dataclass
class ScreeningResult:
    fit: bool
    score: int
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
