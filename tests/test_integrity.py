"""The integrity checks hold for any input, so the pipeline can run on next
month's file. These tests feed it data that is NOT the 2024 workbook, plus the
cases that used to slip through: dropped spend and bad budgets."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import pipeline as p

MESSY = Path(__file__).parent / "fixtures" / "messy_sample.csv"


def fake_year(seed, start="2025-01-01", depts=("Ops", "IT", "HR")):
    rng = np.random.default_rng(seed)
    months = pd.date_range(start, periods=12, freq="MS")
    rows = []
    for d in depts:
        for m in months:
            b = int(rng.integers(50_000, 500_000))
            a = int(b * (1 + rng.normal(0, 0.05)))
            rows.append({"department": d, "month": m.strftime("%Y-%m-%d"), "budget": str(b), "actual": str(a)})
    return pd.DataFrame(rows)


def run_frame(raw, allow=False):
    clean, dropped = p.cleanse(raw, verbose=False)
    df = p.flag_material(p.add_variance(clean))
    s = p.summarize(df)
    s.update(_rows=df, dropped=dropped, rows_read=len(raw))
    return clean, s, p.check_integrity(clean, s, verbose=False, allow_dropped_spend=allow)


# --- works on any clean file ----------------------------------------------

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_checks_pass_on_new_data(seed):
    _, s, checks = run_frame(fake_year(seed))
    assert all(ok is not False and not isinstance(ok, str) for _, ok in checks)
    assert s["headline"]["total_budget"] != 28_221_717  # really is different data


def test_partial_year_works():
    raw = fake_year(4)
    _, s, _ = run_frame(raw[raw["month"] < "2025-10-01"])  # actuals through September
    assert s["headline"]["months"] == 9
    assert s["headline"]["last_month"] == "Sep"


def test_fiscal_year_stays_in_order():
    _, s, _ = run_frame(fake_year(6, start="2024-07-01"))  # Jul 2024 - Jun 2025
    labels = s["by_month"]["month_label"].tolist()
    assert labels[0] == "Jul 2024" and labels[-1] == "Jun 2025"
    assert s["by_month"]["ytd_variance"].iloc[-1] == pytest.approx(s["headline"]["net_variance"])


def test_checks_catch_a_broken_summary():
    raw = fake_year(5)
    clean, dropped = p.cleanse(raw, verbose=False)
    df = p.flag_material(p.add_variance(clean))
    s = p.summarize(df)
    s.update(_rows=df, dropped=dropped, rows_read=len(raw))
    s["by_dept"].loc[0, "budget"] += 1_000  # simulate a logic bug
    with pytest.raises(AssertionError, match="Department totals"):
        p.check_integrity(clean, s, verbose=False)


def test_checks_catch_a_lost_row():
    raw = fake_year(7)
    clean, dropped = p.cleanse(raw, verbose=False)
    df = p.flag_material(p.add_variance(clean))
    s = p.summarize(df)
    s.update(_rows=df, dropped=dropped, rows_read=len(raw) + 1)  # one row vanished unaccounted
    with pytest.raises(AssertionError, match="Rows read"):
        p.check_integrity(clean, s, verbose=False)


# --- dropped spend stops the run ------------------------------------------

def test_dropped_spend_stops_the_run_by_default():
    with pytest.raises(p.DroppedSpendError, match=r"line 8 \(missing budget, actual 12,000\)"):
        p.run(MESSY, write_outputs=False, verbose=False)


def test_override_continues_and_is_labeled():
    s = p.run(MESSY, write_outputs=False, verbose=False, allow_dropped_spend=True)
    status = dict(s["checks"])["No actual spend lost on dropped rows"]
    assert isinstance(status, str) and status.startswith("OVERRIDDEN: $1,033,999")
    assert s["rows_read"] == 10 and len(s["dropped"]) == 5


# --- zero and negative budgets --------------------------------------------

def bad_budgets():
    return pd.DataFrame({
        "department": ["Ops", "Ops", "Ops"],
        "month": pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"]),
        "budget": [100_000, -1_000, 0],
        "actual": [104_000, 500, 40_000],
    })


def test_bad_budgets_get_no_percent_and_no_flag():
    df = p.flag_material(p.add_variance(bad_budgets()))
    assert df["variance_pct"].iloc[1:].isna().all()          # no -150%, no divide by zero
    assert not np.isinf(df["variance_pct"].fillna(0)).any()
    assert not df["material_miss"].iloc[1:].any()             # $40K on a $0 budget isn't "material"
    assert df["variance"].tolist() == [4_000, 1_500, 40_000]  # dollars still count


def test_bad_budgets_are_reported_and_kept_out_of_phasing():
    s = p.summarize(p.flag_material(p.add_variance(bad_budgets())))
    assert s["bad_budget"]["issue"].tolist() == ["Budget is negative", "Budget is zero"]
    ph = s["phasing"].iloc[0]
    assert ph["phasing_ratio"] == 1.0          # only the valid month, not -100x
    assert "budget <= 0" in ph["flag"]


def test_messy_file_negative_budget():
    s = p.run(MESSY, write_outputs=False, verbose=False, allow_dropped_spend=True)
    r = s["_rows"]
    sales_apr = r[(r["department"] == "Sales") & (r["month_num"] == 4)]
    assert sales_apr["budget"].item() == -1_000
    assert pd.isna(sales_apr["variance_pct"].item())
    assert sales_apr["fav_unfav"].item() == "Unfavorable"
    assert s["headline"]["bad_budget_rows"] == 1


# --- materiality rule -----------------------------------------------------

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
