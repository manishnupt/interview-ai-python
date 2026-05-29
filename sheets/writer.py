import time
from dotenv import load_dotenv

load_dotenv()

import gspread
from oauth2client.service_account import ServiceAccountCredentials

import config
from models.candidate import Candidate
from models.result import ScreeningResult, InterviewReport

_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


class SheetWriter:
    def __init__(self):
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                "service_account.json", _SCOPES
            )
        except FileNotFoundError:
            print("[SheetWriter] ERROR: service_account.json not found — add it to the project root.")
            raise

        try:
            client = gspread.authorize(creds)
            self._sheet = client.open_by_key(config.GOOGLE_SHEET_ID).sheet1
        except gspread.exceptions.SpreadsheetNotFound:
            print(
                f"[SheetWriter] ERROR: Sheet not found — verify GOOGLE_SHEET_ID "
                f"({config.GOOGLE_SHEET_ID}) and that the service account has editor access."
            )
            raise
        except gspread.exceptions.APIError as e:
            print(f"[SheetWriter] ERROR: Google Sheets API error — {e}")
            raise

    def write_screening(self, candidate: Candidate, result: ScreeningResult) -> None:
        row = candidate.sheet_row_index
        updates = [
            {"range": f"E{row}", "values": [["Screened"]]},
            {"range": f"F{row}", "values": [[f"{result.score}/10 ({result.match_percentage}%)"]]},
            {"range": f"G{row}", "values": [["Fit" if result.fit else "No Fit"]]},
            {"range": f"H{row}", "values": [[" | ".join(result.fit_reasons)]]},
            {"range": f"I{row}", "values": [[" | ".join(result.concerns)]]},
        ]
        self._batch_update(updates)
        print(f"[Sheet] Written screening result for {candidate.name}")

    def write_interview(self, candidate: Candidate, report: InterviewReport) -> None:
        row = candidate.sheet_row_index
        updates = [
            {"range": f"E{row}", "values": [["Interviewed"]]},
            {"range": f"J{row}", "values": [[report.score]]},
            {"range": f"K{row}", "values": [[" | ".join(report.strengths)]]},
            {"range": f"L{row}", "values": [[" | ".join(report.weaknesses)]]},
            {"range": f"M{row}", "values": [[report.summary]]},
        ]
        self._batch_update(updates)
        print(f"[Sheet] Written interview report for {candidate.name}")

    def reset_all(self) -> int:
        """Clear columns E-M for every data row. Returns the number of rows cleared."""
        rows = self._sheet.get_all_values()
        data_rows = rows[1:]  # skip header
        if not data_rows:
            return 0
        updates = []
        for i, _ in enumerate(data_rows, start=2):
            for col_letter in ("E", "F", "G", "H", "I", "J", "K", "L", "M"):
                updates.append({"range": f"{col_letter}{i}", "values": [[""]]})
        self._batch_update(updates)
        return len(data_rows)

    def mark_status(self, candidate: Candidate, status: str) -> None:
        try:
            self._sheet.update_cell(candidate.sheet_row_index, 5, status)
        except gspread.exceptions.APIError as e:
            print(f"[Sheet] API error, retrying in 5s — {e}")
            time.sleep(5)
            self._sheet.update_cell(candidate.sheet_row_index, 5, status)
        print(f"[Sheet] Marked {candidate.name} as {status}")

    def mark_no_fit(self, candidate: Candidate) -> None:
        self.mark_status(candidate, "Rejected")

    def _batch_update(self, updates: list[dict]) -> None:
        try:
            self._sheet.batch_update(updates)
        except gspread.exceptions.APIError as e:
            print(f"[Sheet] API error, retrying in 5s — {e}")
            time.sleep(5)
            self._sheet.batch_update(updates)
