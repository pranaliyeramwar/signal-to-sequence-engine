"""Usage: python -m scoring [--input PATH] [--output PATH] [--as-of YYYY-MM-DD]"""

import argparse
from collections import Counter
from datetime import date
from pathlib import Path

from .pipeline import score_file, write_results

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="Score company records (ICP, contact and campaign readiness).")
    parser.add_argument("--input", default=ROOT / "data" / "input" / "sample_companies.csv")
    parser.add_argument("--output", default=ROOT / "data" / "output" / "scored_companies.csv")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today(),
                        help="Reference date for 90-day recency checks (default: today).")
    args = parser.parse_args()

    results = score_file(args.input, args.as_of)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    write_results(results, args.output)

    print(f"Scored {len(results)} records as of {args.as_of.isoformat()} -> {args.output}")
    for field in ("icp_outcome", "contact_readiness", "campaign_readiness"):
        counts = Counter(result[field] for result in results)
        print(f"  {field}: " + ", ".join(f"{key} {value}" for key, value in sorted(counts.items())))
    if any(result["is_synthetic"] == "true" for result in results):
        print("  NOTE: input contains synthetic records; they cannot be exported for sequencing.")


if __name__ == "__main__":
    main()
