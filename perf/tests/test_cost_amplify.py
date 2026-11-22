from datetime import UTC, date, datetime, timedelta

import pytest

from perf.amplify import render_sql
from perf.cost import estimate, load_prices, replica_hours

PRICES = {
    "dataflow": {
        "TotalVcpuTime": {"divisor": 3600, "unit": "vCPU-hour", "price": 0.1},
        "TotalMemoryUsage": {"divisor": 3686400, "unit": "GB-hour", "price": 0.01},
        "TotalPdUsage": {"divisor": 3600, "unit": "GB-hour", "price": None},
    },
    "vertex": {"replica_hour_price": 0.5},
}


def test_estimate_prices_each_used_component():
    total, lines = estimate(
        {"TotalVcpuTime": 7200, "TotalMemoryUsage": 3686400}, 2.0, PRICES
    )

    assert total == pytest.approx(2 * 0.1 + 1 * 0.01 + 2 * 0.5)
    assert {line.component for line in lines} == {
        "TotalVcpuTime",
        "TotalMemoryUsage",
        "VertexReplicaHours",
    }


def test_estimate_refuses_a_total_when_a_used_component_has_no_price():
    total, _ = estimate({"TotalVcpuTime": 3600, "TotalPdUsage": 100}, 0.0, PRICES)

    assert total is None


def test_estimate_ignores_unpriced_components_that_were_not_used():
    total, _ = estimate({"TotalVcpuTime": 3600, "TotalPdUsage": 0}, 0.0, PRICES)

    assert total == pytest.approx(0.1)


def test_shipped_price_table_prices_a_vcpu_hour():
    prices = load_prices()
    total, _ = estimate({"TotalVcpuTime": 3600}, 0.0, prices)

    assert prices["checked_on"]
    assert total == pytest.approx(prices["dataflow"]["TotalVcpuTime"]["price"])


def test_replica_hours_integrates_a_step_function():
    t0 = datetime(2026, 11, 22, 10, tzinfo=UTC)
    points = [
        (t0 + timedelta(minutes=30), 2.0),
        (t0, 1.0),
        (t0 + timedelta(minutes=90), 2.0),
    ]

    # 1 replica for 30 min + 2 replicas for 60 min = 2.5 replica-hours
    assert replica_hours(points) == pytest.approx(2.5)


def test_render_sql_copies_with_suffixed_ids_and_never_writes_real_staging():
    sql = render_sql("p", "d", 10)

    assert "TRUNCATE TABLE `p.d.raw_staging_perf`" in sql
    assert "INSERT INTO `p.d.raw_staging_perf`" in sql
    assert "GENERATE_ARRAY(0, 9)" in sql
    assert "'#perf'" in sql
    assert "INTO `p.d.raw_staging`" not in sql
    assert "WHERE" not in sql


def test_render_sql_with_window():
    sql = render_sql("p", "d", 2, date(2025, 4, 24), date(2025, 4, 25))

    assert "s.created_utc >= TIMESTAMP('2025-04-24')" in sql
    assert "s.created_utc < TIMESTAMP('2025-04-25')" in sql


@pytest.mark.parametrize("copies", [0, 101])
def test_render_sql_rejects_copy_counts_out_of_range(copies):
    with pytest.raises(ValueError):
        render_sql("p", "d", copies)


def test_render_sql_rejects_empty_window():
    with pytest.raises(ValueError):
        render_sql("p", "d", 2, date(2025, 4, 25), date(2025, 4, 24))
