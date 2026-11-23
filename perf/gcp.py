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


# cmd.exe metacharacters. Outside double quotes, cmd.exe interprets them
# when it runs a .cmd wrapper — '^' is its escape character, so gcloud's
# "^~^KEY=v~KEY=v" substitution syntax would lose its carets.
_CMD_SPECIAL = set(' \t"^&|<>(),;=%')


def _is_batch(path: str) -> bool:
    """Whether ``path`` is a Windows batch wrapper (``gcloud.cmd``, ``bq.cmd``)."""
    return path.lower().endswith((".cmd", ".bat"))


def windows_cmd_line(command: list[str]) -> str:
    """Build a command line that passes arguments intact through cmd.exe.

    Every argument containing a cmd.exe metacharacter is wrapped in double
    quotes, inside which cmd.exe leaves it alone; the Python process the
    wrapper starts then strips the quotes when it parses its own argv.

    Args:
        command: Executable and arguments.

    Returns:
        The command line string.
    """
    parts = []
    for arg in command:
        if arg and not (_CMD_SPECIAL & set(arg)):
            parts.append(arg)
        else:
            parts.append('"' + arg.replace('"', '\\"') + '"')
    return " ".join(parts)


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
    result = subprocess.run(
        windows_cmd_line(command) if _is_batch(command[0]) else command,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
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


# SQL always goes to `bq query` on standard input, never as an argument:
# on Windows `bq` is a .cmd wrapper, and cmd.exe cuts a multi-line argument
# at its first newline — a multi-statement script then silently runs only
# its first statement.


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
        ],
        stdin=sql,
    )
    return json.loads(out) if out else []


def bq_execute(project_id: str, sql: str) -> None:
    """Run a standard-SQL statement or multi-statement script with ``bq``.

    Args:
        project_id: Project that runs (and is billed for) the script.
        sql: Standard SQL; several statements separated by ``;`` are fine.
    """
    run_text(
        [
            "bq",
            f"--project_id={project_id}",
            "query",
            "--use_legacy_sql=false",
            "--format=none",
        ],
        stdin=sql,
    )


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
