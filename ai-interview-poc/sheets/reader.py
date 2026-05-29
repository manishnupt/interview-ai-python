import time
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()

import config
from models.candidate import Candidate

_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


class SheetReader:
    def __init__(self):
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                "service_account.json", _SCOPES
            )
        except FileNotFoundError:
            print("[SheetReader] ERROR: service_account.json not found.")
            raise

        try:
            client = gspread.authorize(creds)
            self._sheet = client.open_by_key(config.GOOGLE_SHEET_ID).sheet1
        except gspread.exceptions.SpreadsheetNotFound:
            print(f"[SheetReader] ERROR: Sheet not found — check GOOGLE_SHEET_ID ({config.GOOGLE_SHEET_ID}).")
            raise
        except gspread.exceptions.APIError as e:
            print(f"[SheetReader] ERROR: API error — {e}")
            raise

    def get_pending_candidates(self) -> list[Candidate]:
        rows = self._sheet.get_all_values()
        candidates = []
        for i, row in enumerate(rows[1:], start=2):  # skip header, 1-indexed
            status = row[4].strip() if len(row) > 4 else ""
            if status:
                continue
            candidates.append(self._row_to_candidate(row, i))
        return candidates

    def get_all_candidates(self) -> list[Candidate]:
        rows = self._sheet.get_all_values()
        return [
            self._row_to_candidate(row, i)
            for i, row in enumerate(rows[1:], start=2)
        ]

    def _row_to_candidate(self, row: list[str], row_index: int) -> Candidate:
        def col(n: int) -> str:
            return row[n - 1].strip() if len(row) >= n else ""

        return Candidate(
            name=col(1),
            phone=col(2),
            email=col(3),
            resume_url=col(4),
            sheet_row_index=row_index,
        )


if __name__ == "__main__":
    reader = SheetReader()
    candidates = reader.get_pending_candidates()
    print(f"Found {len(candidates)} pending candidates")
    for c in candidates[:3]:
        print(c)
