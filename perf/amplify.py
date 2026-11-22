"""Fill ``raw_staging_perf`` with amplified copies of the real data.

For loads the real dataset cannot sustain for long enough (above roughly
300 records/s, see docs/performance-plan.md). Every staged record is
copied ``k`` times with ids suffixed ``#perf<n>`` and its timestamps
unchanged, so the replay carries ``k`` times as many records over the
same timeline — a release ``k`` times as large, with the real
distribution of text lengths and languages. The pipeline deduplicates on
id, so the copies are processed as distinct records, and no part of the
system caches predictions, so each copy costs a real classification.

The real ``raw_staging`` is only read.

Usage:
    python -m perf.amplify --copies 10 [--from 2025-04-24] [--to 2025-04-25]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from perf import gcp
from perf.experiment import PERF_STAGING_TABLE, REAL_STAGING_TABLE

MAX_COPIES = 100


def window_clause(date_from: date | None, date_to: date | None) -> str:
    """Return a ``WHERE`` clause on ``s.created_utc`` (empty without a window).

    Args:
        date_from: First day, inclusive.
        date_to: Last day, exclusive.

    Raises:
        ValueError: If the window is empty.
    """
    if date_from and date_to and date_from >= date_to:
        raise ValueError("--from must be before --to.")
    conditions = []
    if date_from:
        conditions.append(f"s.created_utc >= TIMESTAMP('{date_from.isoformat()}')")
    if date_to:
        conditions.append(f"s.created_utc < TIMESTAMP('{date_to.isoformat()}')")
    return f"WHERE {' AND '.join(conditions)}" if conditions else ""


def render_sql(
    project: str,
    dataset: str,
    copies: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> str:
    """Return the script that rewrites the perf staging table.

    Args:
        project: GCP project id.
        dataset: Analytics dataset id.
        copies: Copies of each record, 1 … ``MAX_COPIES``.
        date_from: Optional first day (inclusive) of ``created_utc``.
        date_to: Optional last day (exclusive) of ``created_utc``.

    Returns:
        A BigQuery multi-statement script.

    Raises:
        ValueError: If ``copies`` is out of range or the window is empty.
    """
    if not 1 <= copies <= MAX_COPIES:
        raise ValueError(f"copies must be between 1 and {MAX_COPIES}.")
    where = window_clause(date_from, date_to)
    target = f"`{project}.{dataset}.{PERF_STAGING_TABLE}`"
    source = f"`{project}.{dataset}.{REAL_STAGING_TABLE}`"
    lines = [
        f"TRUNCATE TABLE {target};",
        f"INSERT INTO {target}",
        "SELECT s.* REPLACE (CONCAT(s.id, '#perf', CAST(copy AS STRING)) AS id)",
        f"FROM {source} AS s, UNNEST(GENERATE_ARRAY(0, {copies - 1})) AS copy",
    ]
    if where:
        lines.append(where)
    return "\n".join(lines) + ";\n"


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Amplify raw_staging into raw_staging_perf."
    )
    parser.add_argument("--copies", type=int, required=True)
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat)
    parser.add_argument("--dataset", default="co_analytics_dev")
    parser.add_argument("--yes", action="store_true", help="Do not ask to confirm.")
    args = parser.parse_args(argv)

    project = gcp.current_project()
    sql = render_sql(project, args.dataset, args.copies, args.date_from, args.date_to)
    source = f"`{project}.{args.dataset}.{REAL_STAGING_TABLE}`"
    where = window_clause(args.date_from, args.date_to)
    source_rows = int(
        gcp.bq_query(project, f"SELECT COUNT(*) AS n FROM {source} AS s {where}")[0][
            "n"
        ]
    )

    print(sql)
    print(
        f"Writes {source_rows} x {args.copies} = {source_rows * args.copies} rows "
        f"into {PERF_STAGING_TABLE}, replacing its contents."
    )
    if not args.yes and input("Run? [y/N] ").strip().lower() != "y":
        print("Aborted.")
        return 1
    gcp.bq_execute(project, sql)
    target = f"`{project}.{args.dataset}.{PERF_STAGING_TABLE}`"
    written = int(gcp.bq_query(project, f"SELECT COUNT(*) AS n FROM {target}")[0]["n"])
    if written != source_rows * args.copies:
        print(
            f"Expected {source_rows * args.copies} rows, found {written}.",
            file=sys.stderr,
        )
        return 1
    print(f"Done: {written} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
