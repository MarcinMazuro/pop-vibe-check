"""Thin wrappers around the ``gcloud`` and ``bq`` command-line tools.

The rest of the project drives GCP from shell scripts with the same CLIs,
so the experiments use them too: no extra client libraries, and whatever
account ``gcloud`` is logged in as is the account that runs them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


class CommandError(RuntimeError):
    """A CLI call exited non-zero."""


def _resolve(tool: str) -> str:
    """Return the executable path for ``tool``.

    On Windows the Cloud SDK ships ``gcloud.cmd`` / ``bq.cmd``, which
    ``subprocess`` only finds through an explicit lookup.

    Args:
        tool: Executable name, e.g. ``gcloud``.

    Returns:
        The resolved path.

    Raises:
        CommandError: If the tool is not on PATH.
    """
    path = shutil.which(tool)
    if path is None:
        raise CommandError(f"'{tool}' is not on PATH; install the Google Cloud SDK.")
    return path


def run_text(args: list[str], *, stdin: str | None = None) -> str:
    """Run a CLI command and return its standard output.

    Args:
        args: Command and arguments; the first item is resolved on PATH.
        stdin: Optional text fed to the command's standard input.

    Returns:
        Standard output, stripped of surrounding whitespace.

    Raises:
        CommandError: If the command exits non-zero.
    """
    command = [_resolve(args[0]), *args[1:]]
    # A list of arguments, never a shell string.
    result = subprocess.run(
        command, input=stdin, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise CommandError(
            f"{' '.join(args[:3])} … failed ({result.returncode}):\n{result.stderr}"
        )
    return result.stdout.strip()


def run_json(args: list[str]) -> Any:
    """Run a CLI command with ``--format=json`` output and parse it.

    Args:
        args: Command and arguments, without the format flag.

    Returns:
        The parsed JSON value (``None`` for empty output).
    """
    out = run_text([*args, "--format=json"])
    return json.loads(out) if out else None


def bq_query(project_id: str, sql: str) -> list[dict[str, Any]]:
    """Run a standard-SQL query with ``bq`` and return the rows.

    Args:
        project_id: Project that runs (and is billed for) the query.
        sql: Standard SQL.

    Returns:
        Rows as dictionaries of strings, as ``bq --format=json`` prints them.
    """
    out = run_text(
        [
            "bq",
            f"--project_id={project_id}",
            "query",
            "--use_legacy_sql=false",
            "--format=json",
            "--max_rows=100000",
            sql,
        ]
    )
    return json.loads(out) if out else []


def bq_dry_run_bytes(project_id: str, sql: str) -> int:
    """Return how many bytes a query would process, without running it.

    Args:
        project_id: Project that would run the query.
        sql: Standard SQL.

    Returns:
        Bytes processed, as estimated by BigQuery.
    """
    out = run_text(
        [
            "bq",
            f"--project_id={project_id}",
            "query",
            "--use_legacy_sql=false",
            "--dry_run",
            "--format=json",
            sql,
        ]
    )
    stats = json.loads(out).get("statistics", {})
    return int(stats.get("totalBytesProcessed", 0))


def current_project() -> str:
    """Return the project ``gcloud`` is configured for.

    Raises:
        CommandError: If no project is configured.
    """
    project = run_text(["gcloud", "config", "get-value", "project"])
    if not project:
        raise CommandError(
            "No gcloud project configured (gcloud config set project …)."
        )
    return project


def access_token() -> str:
    """Return an OAuth access token for the logged-in ``gcloud`` account."""
    return run_text(["gcloud", "auth", "print-access-token"])
