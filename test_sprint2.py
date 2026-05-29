from dotenv import load_dotenv
load_dotenv()

from sheets.reader import SheetReader
from screening.pdf_parser import PDFParser

reader = SheetReader()
candidates = reader.get_pending_candidates()
candidate = candidates[0]

print(vars(candidate))
print()

parser = PDFParser()
text = parser.extract_text(candidate.resume_url)

print(f"Candidate: {candidate.name}")
print(f"Resume URL: {candidate.resume_url}")
print(f"Characters extracted: {len(text)}")
print(f"First 500 chars:\n{text[:500]}")

assert len(text) > 100, "Resume text too short — check the PDF URL"
