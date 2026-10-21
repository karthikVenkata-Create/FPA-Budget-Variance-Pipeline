"""ONE-TIME VALIDATION, not a general check.

Confirms the pipeline reproduces my 2024 Excel workbook (FPA_Variance_Dashboard_2024_v2.xlsx)
to the dollar. These expected numbers only apply to data/budget_vs_actual_2024.csv.
A new data file should be checked with the integrity checks in pipeline.py, not this.
"""

import pipeline as p

EXCEL_V2 = {
    "rows": 96,
    "total_budget": 28_221_717,
    "total_actual": 28_171_672,
    "net_variance": -50_045,
    "gross_misses": 1_206_143,
    "cancelled_out": 1_156_098,
    "material_misses": 7,
    "near_misses": 4,
    "peak_ytd_variance": 247_760,
    "after_peak_variance": -297_805,
    "bad_budget_rows": 0,
}


def test_matches_excel_v2_workbook():
    h = p.run(p.DEFAULT_CSV, write_outputs=False, verbose=False)["headline"]
    for key, expected in EXCEL_V2.items():
        assert round(h[key]) == expected, f"{key}: got {h[key]:,.0f}, expected {expected:,}"
    assert round(h["net_accuracy"], 3) == 0.998
    assert round(h["gross_accuracy"], 3) == 0.957
    assert h["peak_month"] == "Aug"


def test_nothing_dropped():
    s = p.run(p.DEFAULT_CSV, write_outputs=False, verbose=False)
    assert s["rows_read"] == 96 and len(s["dropped"]) == 0


def test_material_misses_match_workbook():
    s = p.run(p.DEFAULT_CSV, write_outputs=False, verbose=False)
    got = {(r.department, r.month_name) for r in s["material"].itertuples()}
    assert got == {("Marketing", "Mar"), ("Operations", "Apr"), ("HR", "Mar"), ("Finance", "Dec"),
                   ("R&D", "Oct"), ("R&D", "Nov"), ("R&D", "Dec")}


def test_department_totals_match_workbook():
    d = p.run(p.DEFAULT_CSV, write_outputs=False, verbose=False)["by_dept"].set_index("department")["variance"]
    assert round(d["Marketing"]) == 88_118
    assert round(d["R&D"]) == -114_379
    assert round(d["Sales"]) == -91_101
