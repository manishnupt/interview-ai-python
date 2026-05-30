import argparse
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from sheets.reader import SheetReader
from sheets.writer import SheetWriter
from screening.pdf_parser import PDFParser
from screening.screener import Screener
from models.candidate import Candidate
from interview.dialer import place_call
from config import JOB_DESCRIPTION


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Interview Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Run without making any API calls or Sheet writes")
    parser.add_argument("--reset", action="store_true", help="Clear all screening results in the Sheet and exit")
    args = parser.parse_args()

    print("Starting AI Interview Pipeline...")

    reader = SheetReader()
    writer = SheetWriter()

    if args.reset:
        cleared = writer.reset_all()
        print(f"[Reset] Cleared {cleared} candidate row(s)")
        sys.exit(0)
    candidates: list[Candidate] = reader.get_pending_candidates()
    print(f"Found {len(candidates)} pending candidate(s)")

    total = 0
    fit_count = 0
    rejected_count = 0
    skipped_count = 0
    error_count = 0
    log_lines: list[str] = []

    for candidate in candidates:
        print(f"\n--- Processing {candidate.name} ---")
        total += 1

        try:
            if args.dry_run:
                print(f"[DRY RUN] Would screen and interview {candidate.name}")
                log_lines.append(f"{candidate.name} | Dry Run")
                continue

            if not candidate.resume_url:
                print(f"[Skip] {candidate.name} has no resume URL")
                writer.mark_status(candidate, "No Resume")
                skipped_count += 1
                log_lines.append(f"{candidate.name} | No Resume | Skipped")
                continue

            pdf_parser = PDFParser()
            resume_text = pdf_parser.extract_text(candidate.resume_url)

            if not pdf_parser.is_valid_pdf(resume_text):
                print(f"[Skip] Could not extract text from {candidate.name}'s resume")
                skipped_count += 1
                log_lines.append(f"{candidate.name} | PDF Parse Failed | Skipped")
                continue

            screener = Screener()
            result = screener.screen(resume_text, JOB_DESCRIPTION)

            writer.write_screening(candidate, result)

            if result.fit:
                print(f"[✓ FIT] {candidate.name} — Score: {result.score}/10 | {result.match_percentage}% match")
                fit_count += 1
                log_lines.append(f"{candidate.name} | Score: {result.score}/10 | {result.match_percentage}% | Fit")
                if not candidate.phone:
                    print(f"  → No phone number — skipping call")
                    writer.mark_status(candidate, "No Phone")
                else:
                    place_call(candidate.phone, candidate.name)
                    writer.mark_status(candidate, "Interview Scheduled")
                    print(f"  → Call initiated to {candidate.phone}")
            else:
                print(f"[✗ NO FIT] {candidate.name} — Score: {result.score}/10 | {result.match_percentage}% match")
                print(f"  → Rejected")
                writer.mark_no_fit(candidate)
                rejected_count += 1
                log_lines.append(f"{candidate.name} | Score: {result.score}/10 | {result.match_percentage}% | Rejected")

        except Exception as e:
            print(f"[ERROR] Failed to process {candidate.name}: {e}")
            print(f"  → Skipping to next candidate")
            error_count += 1
            log_lines.append(f"{candidate.name} | Error: {e}")
            try:
                writer.mark_status(candidate, "Error")
            except:
                pass
            continue

    print(f"\n--- PIPELINE COMPLETE ---")
    print(f"Processed: {total} candidates")
    print(f"Fit: {fit_count} | Rejected: {rejected_count} | Skipped: {skipped_count} | Errors: {error_count}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("run_log.txt", "a") as f:
        f.write(f"=== RUN: {timestamp} ===\n")
        f.write(f"Total candidates: {total}\n")
        f.write(f"Fit: {fit_count} | Rejected: {rejected_count} | Skipped: {skipped_count} | Errors: {error_count}\n")
        f.write("---\n")
        for line in log_lines:
            f.write(f"{line}\n")
        f.write("===\n\n")
    print("[Log] Run saved to run_log.txt")


if __name__ == "__main__":
    main()
