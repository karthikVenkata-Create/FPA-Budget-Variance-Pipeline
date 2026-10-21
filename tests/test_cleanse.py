"""The cleanse step on a deliberately messy file: $ signs, commas, extra spaces,
mixed date formats, an accounting-style negative, a conflicting duplicate,
blank and unreadable values."""

from pathlib import Path

import pandas as pd
import pytest

import pipeline as p

MESSY = Path(__file__).parent / "fixtures" / "messy_sample.csv"


def cleaned():
    return p.cleanse(p.load(MESSY), verbose=False)


def row(df, dept, month):
    return df[(df["department"] == dept) & (df["month"] == pd.Timestamp(month))]


# --- nothing disappears silently ------------------------------------------

def test_every_row_is_kept_or_dropped_with_a_reason():
    clean, dropped = cleaned()
    assert len(p.load(MESSY)) == 10
    assert len(clean) + len(dropped) == 10
    assert len(clean) == 5
    assert (dropped["reason"] != "").all()


def test_dropped_rows_say_why():
    _, dropped = cleaned()
    reasons = dict(zip(dropped["source_line"], dropped["reason"]))
    assert reasons[8] == "missing budget"            # IT, blank budget, $12K actual
    assert reasons[9] == "missing department"
    assert reasons[10] == "unreadable month"         # "not a date"
    assert reasons[11] == "unreadable actual"        # "abc"
    assert reasons[6].startswith("duplicate dept-month, CONFLICTS with line 5")


def test_blank_budget_with_real_spend_is_spend_at_risk():
    _, dropped = cleaned()
    it = dropped[dropped["source_line"] == 8].iloc[0]
    assert it["actual_value"] == 12_000
    assert it["spend_at_risk"]


def test_unreadable_actual_counts_as_spend_at_risk():
    _, dropped = cleaned()
    assert dropped.loc[dropped["source_line"] == 11, "spend_at_risk"].item()


# --- duplicates -----------------------------------------------------------

def dupes(second_actual):
    return pd.DataFrame({
        "department": ["Ops", "Ops"], "month": ["2024-01-01", "2024-01-01"],
        "budget": ["100", "100"], "actual": ["110", second_actual],
    })


def test_identical_duplicate_is_dropped_but_not_at_risk():
    clean, dropped = p.cleanse(dupes("110"), verbose=False)
    assert len(clean) == 1
    assert dropped["reason"].item() == "duplicate dept-month, identical to line 2"
    assert not dropped["spend_at_risk"].item()


def test_conflicting_duplicate_is_flagged():
    clean, dropped = p.cleanse(dupes("999"), verbose=False)
    assert len(clean) == 1 and clean["actual"].item() == 110   # first row kept
    assert "CONFLICTS with line 2" in dropped["reason"].item()
    assert dropped["spend_at_risk"].item()


# --- parsing --------------------------------------------------------------

def test_headers_and_names_are_trimmed():
    clean, _ = cleaned()
    assert list(clean.columns) == ["source_line", "department", "month", "budget", "actual"]
    assert set(clean["department"]) == {"Marketing", "Sales", "Customer Success"}


def test_money_strings_become_numbers():
    r = row(cleaned()[0], "Marketing", "2024-01-01")
    assert r["budget"].item() == 100_000
    assert r["actual"].item() == 108_000


def test_accounting_negative_is_parsed():
    assert row(cleaned()[0], "Sales", "2024-04-01")["budget"].item() == -1_000


def test_mixed_date_formats_snap_to_month_start():
    months = set(cleaned()[0]["month"].dt.strftime("%Y-%m-%d"))
    assert months == {"2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01", "2024-05-01"}


def test_zero_variance_is_on_budget():
    df = p.add_variance(cleaned()[0])
    assert df.loc[(df["department"] == "Sales") & (df["month_num"] == 3), "fav_unfav"].item() == "On budget"
    assert set(df["fav_unfav"]) == {"Unfavorable", "Favorable", "On budget"}
