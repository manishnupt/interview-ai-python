import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import config

_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


class SheetBase:
    def __init__(self):
        tag = self.__class__.__name__
        try:
            sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
            if sa_json:
                keyfile_dict = json.loads(sa_json)
                creds = ServiceAccountCredentials.from_json_keyfile_dict(keyfile_dict, _SCOPES)
            else:
                creds = ServiceAccountCredentials.from_json_keyfile_name(
                    "service_account.json", _SCOPES
                )
        except FileNotFoundError:
            print(f"[{tag}] ERROR: service_account.json not found and GOOGLE_SERVICE_ACCOUNT_JSON env var not set.")
            raise
        try:
            client = gspread.authorize(creds)
            self._sheet = client.open_by_key(config.GOOGLE_SHEET_ID).sheet1
        except gspread.exceptions.SpreadsheetNotFound:
            print(
                f"[{tag}] ERROR: Sheet not found — verify GOOGLE_SHEET_ID "
                f"({config.GOOGLE_SHEET_ID}) and that the service account has access."
            )
            raise
        except gspread.exceptions.APIError as e:
            print(f"[{tag}] ERROR: Google Sheets API error — {e}")
            raise
