"""CLI: python -m webretriever "natural language request" [--json]"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .agent import retrieve


def _human(report) -> str:
    lines = [f"Request: {report.request}"]
    lines.append(f"Intent: {report.plan.get('intent')} "
                 f"(looking for {report.plan.get('target')})")
    lines.append("")
    if report.refused:
        lines.append("Could not verify an answer.")
        lines.append(f"Reason: {report.refusal_reason}")
    else:
        lines.append(f"Answer: {report.answer}")
        lines.append(f"Confidence: {report.confidence:.0%}"
                     + (" (verified)" if report.verified else ""))
        lines.append("Sources:")
        for c in report.citations:
            lines.append(f"  - {c}")
    lines.append("")
    lines.append(f"Checked {report.sources_checked} pages "
                 f"in {report.elapsed_s:.1f}s.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="WebRetriever — answer natural-language questions "
                    "from live web sources, with citations.")
    ap.add_argument("request", nargs="?", help="natural-language request")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s")

    if not args.request:
        ap.print_help()
        return 2
    report = retrieve(args.request)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(_human(report))
    return 0 if (report.verified or report.refused) else 1


if __name__ == "__main__":
    sys.exit(main())
