import re
from dotenv import load_dotenv

load_dotenv()

from sheets.base import SheetBase
from models.candidate import Candidate


class SheetReader(SheetBase):

    def get_pending_candidates(self) -> list[Candidate]:
        """Return candidates whose Status column (col 5) is blank."""
        rows = self._sheet.get_all_values()
        candidates = []
        for i, row in enumerate(rows[1:], start=2):
            status = row[4].strip() if len(row) > 4 else ""
            if status:
                continue
            candidate = self._row_to_candidate(row, i)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def get_all_candidates(self) -> list[Candidate]:
        """Return every data row regardless of Status."""
        rows = self._sheet.get_all_values()
        return [
            c for i, row in enumerate(rows[1:], start=2)
            if (c := self._row_to_candidate(row, i)) is not None
        ]

    def _row_to_candidate(self, row: list[str], row_index: int) -> Candidate | None:
        def col(n: int) -> str:
            return row[n - 1].strip() if len(row) >= n else ""

        name = col(1)
        if not name:
            print(f"[Reader] Skipping row {row_index} — no name")
            return None

        phone = col(2)
        if not re.match(r"^\+?[0-9\s\-]{7,15}$", phone):
            print(f"[Reader] Warning — {name} has unusual phone: {phone}")

        email = col(3)
        at = email.find("@")
        if at == -1 or "." not in email[at:]:
            print(f"[Reader] Warning — {name} has unusual email: {email}")

        return Candidate(
            name=name,
            phone=phone,
            email=email,
            resume_url=col(4),
            sheet_row_index=row_index,
        )


if __name__ == "__main__":
    reader = SheetReader()
    candidates = reader.get_pending_candidates()
    print(f"Found {len(candidates)} pending candidates")
    for c in candidates[:3]:
        print(c)
