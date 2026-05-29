import argparse
from dotenv import load_dotenv

load_dotenv()

from sheets.reader import SheetReader
from sheets.writer import SheetWriter
from screening.pdf_parser import PDFParser
from screening.screener import Screener
from models.candidate import Candidate
from config import JOB_DESCRIPTION


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Interview Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Run without making any API calls or Sheet writes")
    args = parser.parse_args()

    print("Starting AI Interview Pipeline...")

    reader = SheetReader()
    writer = SheetWriter()
    candidates: list[Candidate] = reader.get_pending_candidates()
    print(f"Found {len(candidates)} pending candidate(s)")

    total = 0
    fit_count = 0
    rejected_count = 0
    skipped_count = 0

    for candidate in candidates:
        print(f"\n--- Processing {candidate.name} ---")
        total += 1

        if args.dry_run:
            print(f"[DRY RUN] Would screen and interview {candidate.name}")
            continue

        if not candidate.resume_url:
            print(f"[Skip] {candidate.name} has no resume URL")
            writer.mark_no_fit(candidate)
            skipped_count += 1
            continue

        pdf_parser = PDFParser()
        resume_text = pdf_parser.extract_text(candidate.resume_url)

        if not pdf_parser.is_valid_pdf(resume_text):
            print(f"[Skip] Could not extract text from {candidate.name}'s resume")
            skipped_count += 1
            continue

        screener = Screener()
        result = screener.screen(resume_text, JOB_DESCRIPTION)

        writer.write_screening(candidate, result)

        if result.fit:
            print(f"[✓ FIT] {candidate.name} — Score: {result.score}/10 | {result.match_percentage}% match")
            print(f"  → Queued for interview")
            fit_count += 1
        else:
            print(f"[✗ NO FIT] {candidate.name} — Score: {result.score}/10 | {result.match_percentage}% match")
            print(f"  → Rejected")
            writer.mark_no_fit(candidate)
            rejected_count += 1

    print(f"\n--- PIPELINE COMPLETE ---")
    print(f"Processed: {total} candidates")
    print(f"Fit: {fit_count} | Rejected: {rejected_count} | Skipped: {skipped_count}")


if __name__ == "__main__":
    main()
