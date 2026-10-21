"""The integrity checks hold for any input, so the pipeline can run on next
month's file. These tests feed it data that is NOT the 2024 workbook."""

import numpy as np
import pandas as pd
import pytest

import pipeline as p


def fake_year(seed, year=2025, depts=("Ops", "IT", "HR")):
    rng = np.random.default_rng(seed)
    rows = []
    for d in depts:
        for m in range(1, 13):
            b = int(rng.integers(50_000, 500_000))
            a = int(b * (1 + rng.normal(0, 0.05)))
            rows.append({"department": d, "month": f"{year}-{m:02d}-01", "budget": str(b), "actual": str(a)})
    return pd.DataFrame(rows)


def run_frame(raw):
    clean = p.cleanse(raw, verbose=False)
    df = p.flag_material(p.add_variance(clean))
    s = p.summarize(df)
    s["_rows"] = df
    return clean, s


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_checks_pass_on_new_data(seed):
    clean, s = run_frame(fake_year(seed))
    checks = p.check_integrity(clean, s, verbose=False)
    assert all(ok for _, ok in checks)
    assert s["headline"]["total_budget"] != 28_221_717  # really is different data


def test_partial_year_works():
    raw = fake_year(4)
    raw = raw[raw["month"] < "2025-10-01"]  # actuals through September only
    clean, s = run_frame(raw)
    p.check_integrity(clean, s, verbose=False)
    assert s["headline"]["months"] == 9


def test_checks_catch_a_broken_summary():
    clean, s = run_frame(fake_year(5))
    s["by_dept"].loc[0, "budget"] += 1_000  # simulate a logic bug
    with pytest.raises(AssertionError, match="Department totals"):
        p.check_integrity(clean, s, verbose=False)


def test_material_rule_needs_both_tests():
    df = pd.DataFrame({
        "department": ["A", "B", "C", "D"],
        "month": pd.to_datetime(["2025-01-01"] * 4),
        "budget": [100_000, 1_000_000, 20_000, 600_000],
        "actual": [130_000, 1_045_000, 30_000, 627_000],
    })
    df = p.flag_material(p.add_variance(df))
    # A: $30K and 30% -> material. B: $45K but 4.5% -> near miss.
    # C: 50% but only $10K -> neither. D: $27K and 4.5% -> near miss.
    assert df["material_miss"].tolist() == [True, False, False, False]
    assert df["near_miss"].tolist() == [False, True, False, True]
