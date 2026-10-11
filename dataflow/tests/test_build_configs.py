"""Shell scripts embedded in Cloud Build configs must at least parse.

Two replay runs were lost to shell bugs that only surfaced inside a build:
an unbalanced ``if`` left by an edit, and substitutions written as shell
variables. A build minute is an expensive place to find a syntax error,
and a replay that dies mid-step can leave a streaming Dataflow job
running. These tests render each step's script the way Cloud Build would
and hand it to ``bash -n``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIGS = sorted(
    p
    for p in REPO_ROOT.rglob("*cloudbuild*.yaml")
    if ".venv" not in p.parts and "terraform" not in p.parts
)

# Built-ins Cloud Build fills in; the values do not matter for parsing.
BUILTIN_SUBSTITUTIONS = {
    "PROJECT_ID": "test-project",
    "BUILD_ID": "00000000-0000-0000-0000-000000000000",
    "COMMIT_SHA": "0" * 40,
    "SHORT_SHA": "0000000",
    "BRANCH_NAME": "main",
}

SUBSTITUTION_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _steps_with_scripts(config: Path) -> list[tuple[str, str, str]]:
    """Return (config name, step id, rendered script) for scripted steps."""
    build = yaml.safe_load(config.read_text())
    declared = {k: str(v) for k, v in (build.get("substitutions") or {}).items()}
    substitutions = {**BUILTIN_SUBSTITUTIONS, **declared}

    rendered = []
    for index, step in enumerate(build.get("steps", [])):
        entrypoint = step.get("entrypoint", "")
        if entrypoint not in {"bash", "sh"}:
            continue
        script = step["args"][-1]
        # Cloud Build expands ${_FOO} itself; $$FOO is what reaches the shell.
        expanded = SUBSTITUTION_PATTERN.sub(
            lambda m: substitutions.get(m.group(1), ""), script
        ).replace("$$", "$")
        rendered.append((config.name, step.get("id", str(index)), expanded))
    return rendered


SCRIPTS = [entry for config in CONFIGS for entry in _steps_with_scripts(config)]


def test_configs_were_found():
    assert CONFIGS, "no Cloud Build configs discovered"
    assert SCRIPTS, "no scripted build steps discovered"


@pytest.mark.parametrize(
    "config_name, step_id, script",
    SCRIPTS,
    ids=[f"{name}:{step}" for name, step, _ in SCRIPTS],
)
def test_step_script_parses(config_name: str, step_id: str, script: str):
    result = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True
    )
    assert (
        result.returncode == 0
    ), f"{config_name} step '{step_id}' is not valid bash:\n{result.stderr}"
