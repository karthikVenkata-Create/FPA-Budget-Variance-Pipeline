"""The cleanse step on a deliberately messy file: $ signs, commas, extra spaces,
mixed date formats, accounting-style negatives, a duplicate row and bad values."""

from pathlib import Path

import pipeline as p

MESSY = Path(__file__).parent / "fixtures" / "messy_sample.csv"


def cleaned():
    return p.cleanse(p.load(MESSY), verbose=False)


def test_bad_rows_are_dropped():
    df = cleaned()
    # 10 rows in: 4 have a missing or unreadable field, 1 is a duplicate dept-month
    assert len(df) == 5


def test_headers_and_names_are_trimmed():
    df = cleaned()
    assert list(df.columns) == ["department", "month", "budget", "actual"]
    assert set(df["department"]) == {"Marketing", "Sales", "Customer Success"}


def test_money_strings_become_numbers():
    df = cleaned()
    row = df[(df["department"] == "Marketing") & (df["month"] == p.pd.Timestamp("2024-01-01"))]
    assert row["budget"].item() == 100_000
    assert row["actual"].item() == 108_000


def test_accounting_negative_is_parsed():
    df = cleaned()
    row = df[(df["department"] == "Sales") & (df["month"] == p.pd.Timestamp("2024-04-01"))]
    assert row["budget"].item() == -1_000


def test_duplicate_keeps_first_row():
    df = cleaned()
    row = df[(df["department"] == "Sales") & (df["month"] == p.pd.Timestamp("2024-04-01"))]
    assert row["actual"].item() == 500


def test_mixed_date_formats_snap_to_month_start():
    months = set(cleaned()["month"].dt.strftime("%Y-%m-%d"))
    assert months == {"2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01", "2024-05-01"}


def test_zero_variance_is_on_budget():
    df = p.add_variance(cleaned())
    sales_mar = df[(df["department"] == "Sales") & (df["month_num"] == 3)]
    assert sales_mar["fav_unfav"].item() == "On budget"
    assert set(df["fav_unfav"]) == {"Unfavorable", "Favorable", "On budget"}
