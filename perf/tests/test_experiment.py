import pytest

from perf.experiment import (
    PERF_LANDING_TABLE,
    PERF_STAGING_TABLE,
    RunSpec,
    SpecError,
    substitutions_arg,
)

TRIGGER = {
    "_DATASET": "co_analytics_dev",
    "_OUTPUT_TABLE": "pop-vibe-check:co_analytics_dev.events_landing",
    "_EVENTS_LANDING_TABLE_ID": "events_landing",
    "_RAW_STAGING_TABLE_ID": "raw_staging",
    "_INPUT_SUBSCRIPTION": "projects/p/subscriptions/co-events-dataflow-sub-dev",
    "_WORKER_SA": "worker@p.iam.gserviceaccount.com",
}


def spec(**overrides):
    return RunSpec(**{"experiment": "e1", "run_id": "e1-w2-s5000", **overrides})


def test_substitutions_redirect_every_table_away_from_real_ones():
    subs = spec(speedup=5000.0).substitutions(TRIGGER, "pop-vibe-check")

    assert (
        subs["_OUTPUT_TABLE"] == f"pop-vibe-check:co_analytics_dev.{PERF_LANDING_TABLE}"
    )
    assert subs["_EVENTS_LANDING_TABLE_ID"] == PERF_LANDING_TABLE
    assert subs["_PROMOTE"] == "false"
    assert subs["_RUN_LOAD"] == "false"


def test_substitutions_keep_trigger_infrastructure_values():
    subs = spec().substitutions(TRIGGER, "pop-vibe-check")

    assert subs["_WORKER_SA"] == TRIGGER["_WORKER_SA"]
    assert subs["_INPUT_SUBSCRIPTION"] == TRIGGER["_INPUT_SUBSCRIPTION"]


def test_substitutions_carry_experiment_parameters():
    subs = spec(
        speedup=5000.0, max_workers=4, max_batch_size=64, model="vertex"
    ).substitutions(TRIGGER, "pop-vibe-check")

    assert subs["_SPEEDUP"] == "5000"
    assert subs["_MAX_WORKERS"] == "4"
    assert subs["_MAX_BATCH_SIZE"] == "64"
    assert subs["_MODEL"] == "vertex"
    assert subs["_LABELS"] == "experiment=e1,run=e1-w2-s5000,purpose=perf"


def test_optional_parameters_are_empty_so_defaults_apply():
    subs = spec().substitutions(TRIGGER, "pop-vibe-check")

    assert subs["_SPEEDUP"] == ""
    assert subs["_MAX_BATCH_SIZE"] == ""
    assert subs["_MAX_SLEEP_SECONDS"] == ""


def test_amplified_runs_point_publisher_and_wait_step_at_perf_staging():
    subs = spec(staging_table=PERF_STAGING_TABLE, copies=10).substitutions(
        TRIGGER, "pop-vibe-check"
    )

    assert subs["_PUBLISHER_STAGING_TABLE"] == PERF_STAGING_TABLE
    assert subs["_RAW_STAGING_TABLE_ID"] == PERF_STAGING_TABLE


@pytest.mark.parametrize(
    "overrides",
    [
        {"run_id": "E1 Run"},
        {"experiment": ""},
        {"model": "gpt"},
        {"speedup": 0.0},
        {"max_workers": 0},
        {"max_batch_size": 0},
        {"staging_table": "events"},
        {"copies": 5},  # copies without the perf staging table
        {"wait_timeout_minutes": 0},
    ],
)
def test_invalid_specs_are_rejected(overrides):
    with pytest.raises(SpecError):
        spec(**overrides)


def test_trigger_without_dataset_is_rejected():
    with pytest.raises(SpecError):
        spec().substitutions({}, "p")


def test_substitutions_arg_uses_alternate_delimiter_for_commas():
    rendered = substitutions_arg({"_LABELS": "a=1,b=2", "_MODEL": "stub"})

    assert rendered == "^~^_LABELS=a=1,b=2~_MODEL=stub"


def test_json_round_trip():
    original = spec(speedup=2.5, notes="first try")

    assert RunSpec.from_json(original.to_json()) == original


def test_windows_cmd_line_quotes_cmd_metacharacters():
    from perf.gcp import windows_cmd_line

    line = windows_cmd_line(
        ["gcloud.cmd", "builds", "--substitutions=^~^_A=a,b~_B=c", ""]
    )

    assert line == 'gcloud.cmd builds "--substitutions=^~^_A=a,b~_B=c" ""'
