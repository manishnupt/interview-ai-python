import re
import tempfile
import os

import httpx
import pdfplumber
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleAuthRequest

_GOOGLE_DOMAINS = ("drive.google.com", "docs.google.com")
_SA_PATH = os.path.join(os.path.dirname(__file__), "..", "service_account.json")
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _google_auth_header() -> dict:
    creds = service_account.Credentials.from_service_account_file(
        os.path.abspath(_SA_PATH), scopes=_DRIVE_SCOPES
    )
    creds.refresh(GoogleAuthRequest())
    return {"Authorization": f"Bearer {creds.token}"}


class PDFParser:

    def convert_to_direct_url(self, url: str) -> str:
        # Google Drive file: /file/d/{id}/
        drive_match = re.search(r"/file/d/([^/]+)/", url)
        if drive_match:
            file_id = drive_match.group(1)
            print("[Parser] Converted Drive URL → direct download")
            return f"https://drive.google.com/uc?export=download&id={file_id}"

        # Google Docs document: /document/d/{id}/
        docs_match = re.search(r"/document/d/([^/]+)", url)
        if docs_match:
            file_id = docs_match.group(1)
            print("[Parser] Converted Google Docs URL → PDF export")
            return f"https://docs.google.com/document/d/{file_id}/export?format=pdf"

        # Dropbox: force direct download by setting dl=1
        if "dropbox.com" in url:
            converted = re.sub(r"[?&]dl=0", lambda m: m.group(0).replace("dl=0", "dl=1"), url)
            if "dl=" not in converted:
                converted += ("&" if "?" in converted else "?") + "dl=1"
            print("[Parser] Converted Dropbox URL → direct download")
            return converted

        # Direct PDF URL — pass through unchanged
        if url.lower().endswith(".pdf"):
            return url

        return url

    def extract_text(self, resume_url: str) -> str:
        url = self.convert_to_direct_url(resume_url)

        headers = {}
        if any(domain in url for domain in _GOOGLE_DOMAINS):
            try:
                headers = _google_auth_header()
            except Exception as e:
                print(f"[Parser] Warning: could not load service account credentials: {e}")

        try:
            response = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
            response.raise_for_status()
        except httpx.TimeoutException as e:
            print(f"[Parser] Timeout downloading PDF: {e}")
            return ""
        except httpx.HTTPStatusError as e:
            print(f"[Parser] HTTP {e.response.status_code} error for URL: {url}")
            return ""

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(response.content)
                tmp_path = tmp.name

            pages = []
            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pages.append(page_text)

            text = "\n\n".join(pages)
            # Collapse 3+ consecutive newlines into 2
            text = re.sub(r"\n{3,}", "\n\n", text).strip()

        except Exception as e:
            print(f"[Parser] pdfplumber error: {e}")
            return ""
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

        if len(text) < 100:
            print("[Parser] Warning: extracted text is very short — PDF may be scanned or image-based")

        print(f"[Parser] Extracted {len(text)} characters from resume")
        return text


    def is_valid_pdf(self, text: str) -> bool:
        return len(text) > 100


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m screening.pdf_parser <resume_url>")
        sys.exit(1)
    parser = PDFParser()
    text = parser.extract_text(sys.argv[1])
    print("--- EXTRACTED TEXT PREVIEW ---")
    print(text[:1000])
    print(f"--- TOTAL: {len(text)} characters ---")
