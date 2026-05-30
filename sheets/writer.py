import time
from dotenv import load_dotenv

load_dotenv()

import gspread
from sheets.base import SheetBase
from models.candidate import Candidate
from models.result import ScreeningResult, InterviewReport


class SheetWriter(SheetBase):

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
        rows = self._sheet.get_all_values()
        data_rows = rows[1:]
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
