"""Cross-check: the Alteryx workflow's saved outputs (alteryx/output*) must match this
Python pipeline on the same data. Re-run the workflow in Designer, commit its outputs,
and this test proves the two implementations still agree."""

from pathlib import Path

import pandas as pd
import pytest

import pipeline as p

ROOT = Path(__file__).resolve().parents[1]
ALX = ROOT / "alteryx"


def alteryx(folder, name):
    return pd.read_csv(ALX / folder / name, keep_default_na=False, na_values=[""])


def test_headline_numbers_match():
    h = p.run(p.DEFAULT_CSV, write_outputs=False, verbose=False)["headline"]
    a = alteryx("output", "summary.csv").iloc[0]
    assert a["total_budget"] == h["total_budget"]
    assert a["total_actual"] == h["total_actual"]
    assert a["net_variance"] == h["net_variance"]
    assert a["gross_misses"] == h["gross_misses"]
    assert a["cancelled_out"] == h["cancelled_out"]
    assert a["material_misses"] == h["material_misses"] == 7
    assert a["near_misses"] == h["near_misses"] == 4
    assert a["net_accuracy"] == pytest.approx(h["net_accuracy"])
    assert a["gross_accuracy"] == pytest.approx(h["gross_accuracy"])
    assert a["all_checks_pass"] == 1 and a["dropped_spend_status"] == "Pass"


def test_same_material_and_near_misses():
    s = p.run(p.DEFAULT_CSV, write_outputs=False, verbose=False)
    for name, frame in (("material_misses.csv", s["material"]), ("near_misses.csv", s["near"])):
        a = alteryx("output", name)
        got = set(zip(a["department"], pd.to_datetime(a["month"]).dt.strftime("%b"), a["variance"].round()))
        exp = set(zip(frame["department"], frame["month_name"], frame["variance"].round()))
        assert got == exp, name


def test_department_and_month_totals_match():
    s = p.run(p.DEFAULT_CSV, write_outputs=False, verbose=False)
    a = alteryx("output", "by_department.csv").set_index("department")
    py = s["by_dept"].set_index("department")
    for col in ("budget", "actual", "variance", "gross_miss", "material_misses"):
        assert (a[col].sort_index() == py[col].sort_index()).all(), col
    am = alteryx("output", "by_month.csv")
    assert am["ytd_variance"].tolist() == pytest.approx(s["by_month"]["ytd_variance"].tolist())


def test_messy_file_matches_python_override_run():
    s = p.run(ROOT / "tests" / "fixtures" / "messy_sample.csv", write_outputs=False, verbose=False,
              allow_dropped_spend=True)
    h = s["headline"]
    a = alteryx("output_messy_test", "summary.csv").iloc[0]
    for key in ("total_budget", "total_actual", "net_variance", "gross_misses", "cancelled_out", "bad_budget_rows"):
        assert a[key] == h[key], key
    assert a["rows_read"] == 10 and a["rows_dropped"] == 5
    assert a["dropped_spend"] == 1_033_999 and a["dropped_spend_status"] == "FAIL"
    dropped = alteryx("output_messy_test", "dropped_rows.csv")
    py_reasons = sorted(r.split(" (kept")[0].replace("line 5", "X") for r in s["dropped"]["reason"])
    alx_reasons = sorted(r.split(" (kept")[0].replace("submission_A line 5", "X") for r in dropped["reason"])
    assert alx_reasons == py_reasons
