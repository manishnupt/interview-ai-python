import argparse
from dotenv import load_dotenv

load_dotenv()

from sheets.reader import SheetReader
from sheets.writer import SheetWriter
from models.candidate import Candidate


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Interview Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Run without making any API calls or Sheet writes")
    args = parser.parse_args()

    print("Starting AI Interview Pipeline...")

    reader = SheetReader()
    candidates: list[Candidate] = reader.get_pending_candidates()
    print(f"Found {len(candidates)} pending candidate(s)")

    for candidate in candidates:
        print(f"Processing: {candidate.name} | {candidate.email}")

        if args.dry_run:
            print(f"[DRY RUN] Would screen and interview {candidate.name}")
            continue

        print("[TODO] Screening and interview logic goes here")


if __name__ == "__main__":
    main()
