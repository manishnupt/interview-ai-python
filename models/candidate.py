from dataclasses import dataclass


@dataclass
class Candidate:
    name: str
    phone: str
    email: str
    resume_url: str
    sheet_row_index: int

    def __str__(self) -> str:
        return f"Candidate(name={self.name}, phone={self.phone})"
