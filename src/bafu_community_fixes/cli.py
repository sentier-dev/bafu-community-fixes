"""Apply community patches to the BAFU EcoSpold 1 database."""

import argparse
import logging
import sys
from pathlib import Path

from bafu_community_fixes.compliance import ComplianceError
from bafu_community_fixes.download import latest_release
from bafu_community_fixes.import_fixes import DEFAULT_PLACEHOLDERS, IMPORT_FIXES, Placeholders
from bafu_community_fixes.pipeline import XSD_CHECKS, PatchError, run
from bafu_community_fixes.registry import available_patches
from bafu_community_fixes.xml import EcoSpoldError


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bafu-fixes", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List import fixes and patches")

    run_p = sub.add_parser("run", help="Import, fix and patch an EcoSpold 1 file or directory")
    run_p.add_argument(
        "source",
        type=Path,
        help="EcoSpold file or folder, or 'latest' for the latest BAFU release (cached)",
    )
    run_p.add_argument("destination", type=Path)
    run_p.add_argument("--only", nargs="+", metavar="ID", help="Apply only these patches")
    run_p.add_argument("--skip", nargs="+", metavar="ID", help="Don't apply these patches")
    run_p.add_argument(
        "--xsd-check",
        choices=list(XSD_CHECKS),
        default="off",
        help="Check against the official XSD: never (default), once at the end, or after "
        "import and every patch (slowest; names the step that broke the data)",
    )
    run_p.add_argument(
        "--strict",
        dest="xsd_check",
        action="store_const",
        const="every-step",
        help="Same as --xsd-check every-step",
    )
    run_p.add_argument(
        "--no-extensions",
        action="store_true",
        help="Leave out our additional fields (bcf: namespace) from the output",
    )
    run_p.add_argument(
        "--report",
        type=Path,
        metavar="HTML",
        help="Write an HTML report of what changed, who authorised it, and how much",
    )
    defaults = DEFAULT_PLACEHOLDERS
    group = run_p.add_argument_group("placeholders for missing required data")
    group.add_argument("--placeholder-year", type=int, default=defaults.year, metavar="YEAR")
    group.add_argument("--placeholder-number", type=int, default=defaults.number, metavar="N")
    group.add_argument("--placeholder-country", default=defaults.country, metavar="CODE")
    group.add_argument(
        "--placeholder-text", default=defaults.text, metavar="TEXT", help="1 to 7 characters"
    )
    run_p.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "list":
        print("Import fixes (always applied, in order):")
        for fix in IMPORT_FIXES:
            print(f"  {fix.id}\t{fix.description}")
        print("Patches:")
        for p in available_patches():
            authorised = p.provenance.authorised_by or "NOT YET AUTHORISED"
            print(f"  {p.id}\t{p.description}\t[{authorised}]")
        return

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    try:
        placeholders = Placeholders(
            year=args.placeholder_year,
            number=args.placeholder_number,
            country=args.placeholder_country,
            text=args.placeholder_text,
        )
    except ValueError as e:
        parser.error(str(e))
    source = args.source
    if str(source) == "latest":
        source = latest_release()
        print(f"Using the latest BAFU release from {source}")
    try:
        log = run(
            source,
            args.destination,
            only=args.only,
            skip=args.skip,
            extensions=not args.no_extensions,
            xsd_check=args.xsd_check,
            report=args.report,
            placeholders=placeholders,
        )
    except (EcoSpoldError, ComplianceError, PatchError) as e:
        if args.report:
            print(f"Report written to {args.report}", file=sys.stderr)
        sys.exit(str(e))
    print(f"Wrote {log.written} file(s) to {args.destination}")
    if args.report:
        print(f"Report written to {args.report}")


if __name__ == "__main__":
    main()
