"""
FP&A Budget Variance Pipeline
Karthik Bommisetty

Turns a budget vs actual file (department x month) into a variance report. The
steps follow the same order as an Alteryx Designer workflow:

    Input -> Data Cleanse -> Formula -> Filter -> Summarize -> Integrity checks -> Output

Run:  python pipeline.py [path/to/file.csv] [--allow-dropped-spend]
Out:  output/variance_report.xlsx, images/accuracy_gap.png, images/variance_scatter.png

The integrity checks hold for any input file. The one-time check that this
pipeline matches my 2024 Excel workbook lives in tests/test_baseline_2024.py.

The included data is a practice dataset, not a real company's books.
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = ROOT / "data" / "budget_vs_actual_2024.csv"
OUTPUT_DIR = ROOT / "output"
IMAGE_DIR = ROOT / "images"

# Materiality rule: a department-month is a material miss only if it breaks BOTH
# thresholds. The $ test filters out noise on tiny months, the % test filters out
# big departments where $25K is a rounding error.
MATERIALITY_PCT = 0.05
MATERIALITY_USD = 25_000

# Near miss: passes the $ test but lands just under the % test (here 4% to 5%).
NEAR_MISS_PCT_FLOOR = 0.04

# Data quality: flag a department whose biggest monthly budget is more than this
# many times its smallest. Real opex budgets rarely swing more than 2-3x.
PHASING_RATIO_FLAG = 10

# Tolerance for the integrity checks (floating point only, the data is whole dollars)
TOL = 0.01


# ---------------------------------------------------------------------------
# 1. Input
# ---------------------------------------------------------------------------
def load(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str)


# ---------------------------------------------------------------------------
# 2. Data Cleanse
# ---------------------------------------------------------------------------
class DroppedSpendError(Exception):
    """Raised when rows that carried actual spend were dropped during cleansing."""


def cleanse(df: pd.DataFrame, verbose: bool = True) -> tuple:
    """Returns (clean, dropped). Every row read ends up in exactly one of the two,
    and every dropped row says why, so nothing disappears silently."""
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower()
    for col in df.columns:
        df[col] = df[col].str.strip()
    df.insert(0, "source_line", range(2, len(df) + 2))  # line number in the CSV (header is line 1)
    raw = df.copy()

    df["department"] = df["department"].str.replace(r"\s+", " ", regex=True).replace("", np.nan)
    # Accepts 2024-01-01, 1/1/2024, Jan 2024 and so on; everything snaps to the first of the month
    df["month"] = pd.to_datetime(df["month"], errors="coerce", format="mixed").dt.to_period("M").dt.to_timestamp()
    for col in ("budget", "actual"):
        cleaned = df[col].str.replace(r"[$,\s]", "", regex=True)
        cleaned = cleaned.str.replace(r"^\((.*)\)$", r"-\1", regex=True)  # (1,234) -> -1234
        df[col] = pd.to_numeric(cleaned, errors="coerce")

    # Why each bad row is bad: blank vs present-but-unreadable
    def problem(col, label):
        blank = raw[col].isna() | (raw[col] == "")
        return np.where(df[col].isna(), np.where(blank, f"missing {label}", f"unreadable {label}"), "")

    parts = pd.DataFrame({c: problem(c, c) for c in ("department", "month", "budget", "actual")}, index=df.index)
    reason = parts.apply(lambda r: "; ".join(x for x in r if x), axis=1)
    bad = reason != ""

    good = df[~bad]
    dup = good.duplicated(["department", "month"], keep="first")
    first = good[~dup].set_index(["department", "month"])
    dup_reason = {}
    for i, r in good[dup].iterrows():
        k = first.loc[(r["department"], r["month"])]
        same = k["budget"] == r["budget"] and k["actual"] == r["actual"]
        dup_reason[i] = ("duplicate dept-month, identical to line %d" % k["source_line"]) if same else (
            "duplicate dept-month, CONFLICTS with line %d (kept: budget %s, actual %s)"
            % (k["source_line"], f"{k['budget']:,.0f}", f"{k['actual']:,.0f}"))
    reason.loc[list(dup_reason)] = pd.Series(dup_reason)

    drop_mask = reason != ""
    dropped = raw[drop_mask].copy()
    dropped["reason"] = reason[drop_mask]
    dropped["actual_value"] = df.loc[drop_mask, "actual"]
    # Spend on an identical duplicate is still counted on the kept row. Any other dropped row with
    # nonzero actual spend, or an actual we couldn't read (so the spend is unknown), is spend at risk.
    unknown_actual = dropped["reason"].str.contains("unreadable actual")
    dropped["spend_at_risk"] = (~dropped["reason"].str.contains("identical")) & (
        dropped["actual_value"].fillna(0).ne(0) | unknown_actual)
    clean = df[~drop_mask].sort_values(["department", "month"]).reset_index(drop=True)

    if verbose and len(dropped):
        print(f"  cleanse: kept {len(clean)} of {len(df)} rows, dropped {len(dropped)} (see the Dropped Rows tab)")
    return clean, dropped.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. Formula
# ---------------------------------------------------------------------------
def add_variance(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # Cost centers: positive variance = spent more than planned = Unfavorable
    df["variance"] = df["actual"] - df["budget"]
    # A cost-center budget of zero or less is almost always a data error. The dollar
    # variance still counts, but a % of it is meaningless (and /0 breaks), so leave it blank.
    df["budget_ok"] = df["budget"] > 0
    df["variance_pct"] = (df["variance"] / df["budget"]).where(df["budget_ok"])
    df["abs_variance"] = df["variance"].abs()
    df["fav_unfav"] = np.select(
        [df["variance"] > 0, df["variance"] < 0], ["Unfavorable", "Favorable"], default="On budget"
    )
    df["month_num"] = df["month"].dt.month
    df["month_name"] = df["month"].dt.strftime("%b")
    return df


# ---------------------------------------------------------------------------
# 4. Filter
# ---------------------------------------------------------------------------
def flag_material(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    big_dollars = df["abs_variance"] > MATERIALITY_USD
    pct = df["variance_pct"].abs()
    df["material_miss"] = big_dollars & (pct > MATERIALITY_PCT)
    df["near_miss"] = big_dollars & (pct > NEAR_MISS_PCT_FLOOR) & (pct <= MATERIALITY_PCT)
    return df


# ---------------------------------------------------------------------------
# 5. Summarize
# ---------------------------------------------------------------------------
def summarize(df: pd.DataFrame) -> dict:
    budget = df["budget"].sum()
    actual = df["actual"].sum()
    net_var = df["variance"].sum()
    gross_miss = df["abs_variance"].sum()

    headline = {
        "rows": len(df),
        "departments": df["department"].nunique(),
        "months": df["month"].nunique(),
        "total_budget": budget,
        "total_actual": actual,
        "net_variance": net_var,
        "net_accuracy": 1 - abs(net_var) / budget,
        "gross_misses": gross_miss,
        "cancelled_out": gross_miss - abs(net_var),
        "gross_accuracy": 1 - gross_miss / budget,
        "material_misses": int(df["material_miss"].sum()),
        "near_misses": int(df["near_miss"].sum()),
        "bad_budget_rows": int((~df["budget_ok"]).sum()),
    }

    def label(v):
        return "Unfavorable" if v > 0 else "Favorable" if v < 0 else "On budget"

    by_dept = (
        df.groupby("department", sort=False)
        .agg(
            budget=("budget", "sum"),
            actual=("actual", "sum"),
            variance=("variance", "sum"),
            gross_miss=("abs_variance", "sum"),
            material_misses=("material_miss", "sum"),
        )
        .reset_index()
    )
    ok = df[df["budget_ok"]].groupby("department")["budget"]
    by_dept["min_month_budget"] = by_dept["department"].map(ok.min())
    by_dept["max_month_budget"] = by_dept["department"].map(ok.max())
    by_dept["bad_budget_months"] = by_dept["department"].map((~df["budget_ok"]).groupby(df["department"]).sum())
    by_dept["variance_pct"] = (by_dept["variance"] / by_dept["budget"]).where(by_dept["budget"] > 0)
    by_dept["gross_accuracy"] = 1 - by_dept["gross_miss"] / by_dept["budget"]
    by_dept["fav_unfav"] = by_dept["variance"].apply(label)
    by_dept["phasing_ratio"] = by_dept["max_month_budget"] / by_dept["min_month_budget"]
    by_dept = by_dept.sort_values("variance", ascending=False).reset_index(drop=True)

    # Group by the actual month (not month number) so a fiscal year like Jul-Jun stays in order
    by_month = (
        df.groupby("month")
        .agg(
            budget=("budget", "sum"),
            actual=("actual", "sum"),
            variance=("variance", "sum"),
            gross_miss=("abs_variance", "sum"),
            material_misses=("material_miss", "sum"),
        )
        .reset_index()
        .sort_values("month")
    )
    multi_year = by_month["month"].dt.year.nunique() > 1
    by_month.insert(1, "month_label", by_month["month"].dt.strftime("%b %Y" if multi_year else "%b"))
    by_month["ytd_variance"] = by_month["variance"].cumsum()
    by_month["gross_accuracy"] = 1 - by_month["gross_miss"] / by_month["budget"]

    # Timing: where the running variance peaked, and what happened after. Works for any
    # period length, unlike a fixed Jan-Aug / Sep-Dec split.
    peak_i = by_month["ytd_variance"].abs().idxmax()
    headline["first_month"] = by_month["month_label"].iloc[0]
    headline["last_month"] = by_month["month_label"].iloc[-1]
    headline["peak_month"] = by_month.loc[peak_i, "month_label"]
    headline["peak_ytd_variance"] = by_month.loc[peak_i, "ytd_variance"]
    headline["after_peak_variance"] = by_month.loc[by_month["month"] > by_month.loc[peak_i, "month"], "variance"].sum()

    cols = ["department", "month_name", "budget", "actual", "variance", "variance_pct", "fav_unfav"]
    material = df[df["material_miss"]].sort_values("abs_variance", ascending=False)[cols].reset_index(drop=True)
    near = (
        df[df["near_miss"]]
        .assign(abs_pct=lambda d: d["variance_pct"].abs())
        .sort_values("abs_pct", ascending=False)[cols]
        .reset_index(drop=True)
    )

    phasing = by_dept[["department", "min_month_budget", "max_month_budget", "phasing_ratio", "bad_budget_months"]].copy()
    phasing["flag"] = np.where(phasing["phasing_ratio"] > PHASING_RATIO_FLAG, "Question this phasing", "")
    phasing.loc[phasing["bad_budget_months"] > 0, "flag"] += np.where(
        phasing.loc[phasing["bad_budget_months"] > 0, "flag"] != "", "; ", "") + "has budget <= 0 (ratio uses valid months only)"
    phasing = phasing.sort_values("phasing_ratio", ascending=False).reset_index(drop=True)

    bad_budget = df[~df["budget_ok"]][["department", "month", "budget", "actual", "variance"]].copy()
    bad_budget["issue"] = np.where(bad_budget["budget"] == 0, "Budget is zero", "Budget is negative")
    bad_budget["what_the_pipeline_did"] = "Kept the dollars in all totals; % variance and materiality not calculated"
    bad_budget["month"] = bad_budget["month"].dt.strftime("%Y-%m")

    return {"headline": headline, "by_dept": by_dept, "by_month": by_month,
            "material": material, "near": near, "phasing": phasing, "bad_budget": bad_budget}


# ---------------------------------------------------------------------------
# Integrity checks: these hold for ANY input file, not just the 2024 data
# ---------------------------------------------------------------------------
def check_integrity(clean: pd.DataFrame, s: dict, verbose: bool = True, allow_dropped_spend: bool = False) -> list:
    h, dept, month = s["headline"], s["by_dept"], s["by_month"]
    dropped = s["dropped"]
    at_risk = dropped.loc[dropped["spend_at_risk"], "actual_value"].sum()
    rows = s["_rows"]
    checks = [
        ("Rows read = rows kept + rows dropped",
         s["rows_read"] == len(clean) + len(dropped)),
        ("Every dropped row has a reason",
         bool((dropped["reason"] != "").all())),
        ("One row per department-month",
         not clean.duplicated(["department", "month"]).any()),
        ("Budget in = budget out",
         abs(clean["budget"].sum() - h["total_budget"]) < TOL),
        ("Actual in = actual out",
         abs(clean["actual"].sum() - h["total_actual"]) < TOL),
        ("Department totals add to the grand total",
         abs(dept["budget"].sum() - h["total_budget"]) < TOL
         and abs(dept["actual"].sum() - h["total_actual"]) < TOL
         and abs(dept["variance"].sum() - h["net_variance"]) < TOL),
        ("Monthly totals add to the annual total",
         abs(month["budget"].sum() - h["total_budget"]) < TOL
         and abs(month["actual"].sum() - h["total_actual"]) < TOL),
        ("Year-to-date variance ends at the net variance",
         abs(month["ytd_variance"].iloc[-1] - h["net_variance"]) < TOL),
        ("Variance = actual - budget on every row",
         bool(np.allclose(clean["actual"] - clean["budget"], s["_rows"]["variance"]))),
        ("Gross misses >= |net variance|",
         h["gross_misses"] + TOL >= abs(h["net_variance"])),
        ("Material and near-miss flags never overlap",
         not (rows["material_miss"] & rows["near_miss"]).any()),
        ("Variance % only calculated where budget > 0",
         bool(rows.loc[~rows["budget_ok"], "variance_pct"].isna().all())),
    ]
    failed = [name for name, ok in checks if not ok]
    if failed:
        raise AssertionError("Integrity checks failed: " + "; ".join(failed))

    # Dropping a row that carried real spend understates what was spent. Stop unless told otherwise.
    lines = dropped[dropped["spend_at_risk"]]
    status = True
    if len(lines):
        n_unknown = int(lines["actual_value"].isna().sum())
        amount = f"${at_risk:,.0f} of actual spend" + (
            f" plus {n_unknown} row(s) whose actual couldn't be read" if n_unknown else "")
        detail = ", ".join(
            f"line {r.source_line} ({r.reason}, actual "
            f"{'unreadable' if pd.isna(r.actual_value) else format(r.actual_value, ',.0f')})"
            for r in lines.itertuples())
        if not allow_dropped_spend:
            raise DroppedSpendError(
                f"{amount} is on rows that were dropped: {detail}. "
                "Fix the source file, or rerun with --allow-dropped-spend to report it and continue.")
        status = f"OVERRIDDEN: {amount} dropped (see Dropped Rows tab)"
    checks.append(("No actual spend lost on dropped rows", status))
    if verbose:
        n_over = sum(1 for _, ok in checks if isinstance(ok, str))
        print(f"  integrity: {len(checks) - n_over} of {len(checks)} checks passed"
              + (f", {n_over} overridden" if n_over else ""))
    return checks


# ---------------------------------------------------------------------------
# 6. Output: Excel report
# ---------------------------------------------------------------------------
def write_excel(df: pd.DataFrame, s: dict, checks: list, path: Path) -> None:
    h = s["headline"]
    summary = pd.DataFrame(
        [
            ("Total budget", h["total_budget"]),
            ("Total actual", h["total_actual"]),
            ("Net variance", h["net_variance"]),
            ("Net accuracy", h["net_accuracy"]),
            ("Gross misses (all misses combined)", h["gross_misses"]),
            ("Misses that cancelled out", h["cancelled_out"]),
            ("Gross accuracy", h["gross_accuracy"]),
            (f"Material misses (of {h['rows']})", h["material_misses"]),
            (f"Near misses (of {h['rows']})", h["near_misses"]),
            (f"Peak year-to-date variance ({h['peak_month']})", h["peak_ytd_variance"]),
            (f"Variance after the peak (through {h['last_month']})", h["after_peak_variance"]),
            ("Rows read", s["rows_read"]),
            ("Rows dropped", len(s["dropped"])),
            ("Actual spend on dropped rows", s["dropped"].loc[s["dropped"]["spend_at_risk"], "actual_value"].sum()),
            ("Rows with budget <= 0", h["bad_budget_rows"]),
            ("Materiality: % threshold", MATERIALITY_PCT),
            ("Materiality: $ threshold", MATERIALITY_USD),
            ("Near miss: % floor", NEAR_MISS_PCT_FLOOR),
        ],
        columns=["Metric", "Value"],
    )

    detail = df[["department", "month", "budget", "actual", "variance", "variance_pct",
                 "fav_unfav", "abs_variance", "material_miss", "near_miss"]].copy()
    detail["month"] = detail["month"].dt.strftime("%Y-%m")
    integrity = pd.DataFrame([(n, ok if isinstance(ok, str) else "Pass" if ok else "FAIL") for n, ok in checks], columns=["Check", "Result"])

    sheets = {
        "Summary": summary,
        "Material Misses": s["material"],
        "Near Misses": s["near"],
        "By Department": s["by_dept"],
        "By Month": s["by_month"].assign(month=lambda d: d["month"].dt.strftime("%Y-%m")),
        "Budget Phasing": s["phasing"],
        "Data Quality": s["bad_budget"],
        "Dropped Rows": s["dropped"].drop(columns=["actual_value"]),
        "Integrity Checks": integrity,
        "Variance Data": detail,
    }

    money = "$#,##0;($#,##0)"
    pct = "0.0%;(0.0%)"
    money_cols = {"budget", "actual", "variance", "abs_variance", "gross_miss", "ytd_variance",
                  "min_month_budget", "max_month_budget"}
    pct_cols = {"variance_pct", "gross_accuracy"}

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, frame in sheets.items():
            frame.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            for col_idx, col in enumerate(frame.columns, start=1):
                letter = ws.cell(row=1, column=col_idx).column_letter
                ws.column_dimensions[letter].width = max(14, len(str(col)) + 4)
                fmt = None if name == "Dropped Rows" else money if col in money_cols else \
                    pct if col in pct_cols else '0.0"x"' if col == "phasing_ratio" else None
                if fmt:
                    for row in range(2, len(frame) + 2):
                        ws.cell(row=row, column=col_idx).number_format = fmt
            if name in ("Summary", "Integrity Checks"):
                ws.column_dimensions["A"].width = 50
            if name == "Summary":
                for r, metric in enumerate(summary["Metric"], start=2):
                    cell = ws.cell(row=r, column=2)
                    if "accuracy" in metric.lower() or "%" in metric:
                        cell.number_format = "0.0%"
                    elif "(of" not in metric and not metric.startswith("Rows"):
                        cell.number_format = money


# ---------------------------------------------------------------------------
# 6. Output: charts
# ---------------------------------------------------------------------------
INK = "#1f2933"
MUTED = "#6b7280"
GRID = "#e5e7eb"
NAVY = "#1f4e79"
RED = "#c0392b"
GRAY = "#9aa3ad"
LIGHT = "#b8bec7"


def _style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=10)


def chart_accuracy_gap(h: dict, path: Path) -> None:
    """Dot plot, not bars: a dot's position carries the value, so a zoomed-in axis
    doesn't exaggerate the gap the way a truncated bar would."""
    fig, ax = plt.subplots(figsize=(8.5, 3.8), dpi=200)
    net, gross = h["net_accuracy"] * 100, h["gross_accuracy"] * 100
    ys = [1, 0]

    ax.hlines(ys, 90, 100, color=GRID, lw=1, zorder=1)
    ax.hlines(0.5, gross, net, color=RED, lw=1.2, ls=":", zorder=1)
    ax.vlines([gross, net], 0, 1, color=RED, lw=0.8, ls=":", alpha=0.6, zorder=1)
    ax.scatter([net, gross], ys, s=[260, 260], color=[GRAY, NAVY], zorder=3)
    ax.text(net, 1.22, f"{net:.1f}%", ha="center", fontsize=15, fontweight="bold", color=INK)
    ax.text(gross, 0.22, f"{gross:.1f}%", ha="center", fontsize=15, fontweight="bold", color=INK)
    ax.text((net + gross) / 2, 0.58, f"{net - gross:.1f} pts", ha="center", fontsize=10, color=RED)

    ax.set_yticks(ys)
    ax.set_yticklabels(["Net accuracy\nmisses cancel out", "Gross accuracy\nevery miss counted"])
    ax.set_ylim(-0.45, 1.55)
    ax.set_xlim(90, 100.4)
    ax.set_xlabel("Budget accuracy (%)  ·  axis starts at 90%", color=MUTED)
    _style(ax)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)

    ax.set_title(rf"99.8% looks right because \${h['cancelled_out'] / 1e6:.2f}M of misses cancelled out",
                 loc="left", fontsize=13.5, fontweight="bold", color=INK, pad=28)
    over = (h["gross_misses"] + h["net_variance"]) / 2
    under = (h["gross_misses"] - h["net_variance"]) / 2
    sign = "−" if h["net_variance"] < 0 else "+"
    ax.text(0, 1.04,
            rf"Total misses \${h['gross_misses'] / 1e6:.2f}M: \${over / 1e6:.2f}M over budget and "
            rf"\${under / 1e6:.2f}M under, netting to {sign}\${abs(h['net_variance']) / 1e3:.0f}K.",
            transform=ax.transAxes, fontsize=9.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def chart_variance_scatter(df: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5.8), dpi=200)
    x = df["variance_pct"] * 100
    y = df["variance"] / 1000
    xlim, ylim = 11, 90

    # Shade the material zones: |pct| > 5% AND |$| > 25K, in both directions
    zone = dict(color=RED, alpha=0.07, lw=0, zorder=0)
    ax.fill_between([MATERIALITY_PCT * 100, xlim], MATERIALITY_USD / 1000, ylim, **zone)
    ax.fill_between([-xlim, -MATERIALITY_PCT * 100], -ylim, -MATERIALITY_USD / 1000, **zone)
    for v in (MATERIALITY_PCT * 100, -MATERIALITY_PCT * 100):
        ax.axvline(v, color=RED, lw=0.8, ls="--", alpha=0.5)
    for v in (MATERIALITY_USD / 1000, -MATERIALITY_USD / 1000):
        ax.axhline(v, color=RED, lw=0.8, ls="--", alpha=0.5)
    ax.axhline(0, color=GRID, lw=1)
    ax.axvline(0, color=GRID, lw=1)

    mat, near = df["material_miss"], df["near_miss"]
    normal = ~mat & ~near
    ax.scatter(x[normal], y[normal], s=34, color=LIGHT, edgecolor="white", lw=0.6, zorder=3)
    ax.scatter(x[near], y[near], s=50, facecolor="white", edgecolor=RED, lw=1.4, zorder=4)
    ax.scatter(x[mat], y[mat], s=70, color=RED, edgecolor="white", lw=0.8, zorder=5)

    nudge = {("Finance", "Dec"): (6, -12), ("Marketing", "Mar"): (6, 5),
             ("Marketing", "Jul"): (-8, 13), ("R&D", "Apr"): (-8, -12)}
    for _, r in df[mat | near].iterrows():
        dx, dy = nudge.get((r["department"], r["month_name"]), (6, 4))
        ax.annotate(f"{r['department']} {r['month_name']}",
                    (r["variance_pct"] * 100, r["variance"] / 1000),
                    xytext=(dx, dy), textcoords="offset points", fontsize=8.5,
                    color=INK if r["material_miss"] else MUTED, ha="right" if dx < 0 else "left",
                    bbox=dict(fc="white", ec="none", alpha=0.85, pad=0.8), zorder=6)

    ax.set_xlim(-xlim, xlim)
    ax.xaxis.set_major_locator(plt.MultipleLocator(2))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:+.0f}%" if v else "0%"))
    ax.set_ylim(-ylim, ylim)
    ax.set_xlabel(r"Variance as % of budget  (actual $-$ budget)", color=MUTED)
    ax.set_ylabel(r"Variance (\$K)", color=MUTED)
    _style(ax)

    n_mat, n_near = int(mat.sum()), int(near.sum())
    ax.set_title(f"{n_mat} of {len(df)} department-months were material misses", loc="left",
                 fontsize=14, fontweight="bold", color=INK, pad=22)
    ax.text(0, 1.02, r"Material = $|\mathrm{var}| > \$25\mathrm{K}$ and $|\mathrm{var\,\%}| > 5\%$."
                     r"  Near miss = over \$25K but 4% to 5%.",
            transform=ax.transAxes, fontsize=9.5, color=MUTED)

    legend = [
        Line2D([], [], marker="o", ls="", color=RED, markersize=8, label=f"Material miss ({n_mat})"),
        Line2D([], [], marker="o", ls="", markerfacecolor="white", markeredgecolor=RED, markersize=7,
               label=f"Near miss ({n_near})"),
        Line2D([], [], marker="o", ls="", color=LIGHT, markersize=7,
               label=f"Within threshold ({len(df) - n_mat - n_near})"),
        Patch(color=RED, alpha=0.12, label="Materiality zone"),
    ]
    ax.legend(handles=legend, loc="upper left", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
def run(csv_path: Path, write_outputs: bool = True, verbose: bool = True,
        allow_dropped_spend: bool = False) -> dict:
    say = print if verbose else (lambda *a, **k: None)
    say("1. Input")
    raw = load(csv_path)
    say(f"  read {len(raw)} rows from {csv_path.name}")
    say("2. Data Cleanse")
    clean, dropped = cleanse(raw, verbose=verbose)
    say("3. Formula")
    df = add_variance(clean)
    say("4. Filter")
    df = flag_material(df)
    say(f"  {int(df['material_miss'].sum())} material misses, {int(df['near_miss'].sum())} near misses")
    say("5. Summarize")
    s = summarize(df)
    s.update(_rows=df, dropped=dropped, rows_read=len(raw))
    say("6. Integrity checks")
    checks = check_integrity(clean, s, verbose=verbose, allow_dropped_spend=allow_dropped_spend)
    s["checks"] = checks
    if write_outputs:
        say("7. Output")
        OUTPUT_DIR.mkdir(exist_ok=True)
        IMAGE_DIR.mkdir(exist_ok=True)
        write_excel(df, s, checks, OUTPUT_DIR / "variance_report.xlsx")
        chart_accuracy_gap(s["headline"], IMAGE_DIR / "accuracy_gap.png")
        chart_variance_scatter(df, IMAGE_DIR / "variance_scatter.png")
    return s


def money(v: float) -> str:
    return ("−" if v < 0 else "") + f"${abs(v):,.0f}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Budget vs actual variance pipeline")
    ap.add_argument("csv", nargs="?", default=DEFAULT_CSV, type=Path)
    ap.add_argument("--allow-dropped-spend", action="store_true",
                    help="continue even if rows with actual spend had to be dropped (they're listed on the Dropped Rows tab)")
    args = ap.parse_args()
    try:
        s = run(args.csv, allow_dropped_spend=args.allow_dropped_spend)
    except DroppedSpendError as e:
        raise SystemExit(f"\nSTOPPED: {e}")
    h = s["headline"]
    print()
    print(f"Budget {money(h['total_budget'])} | Actual {money(h['total_actual'])} | Net variance {money(h['net_variance'])}")
    print(f"Net accuracy {h['net_accuracy']:.1%} | Gross accuracy {h['gross_accuracy']:.1%}")
    print(f"Total misses {money(h['gross_misses'])}, of which {money(h['cancelled_out'])} cancelled out")
    print(f"Running variance peaked at {money(h['peak_ytd_variance'])} in {h['peak_month']}, "
          f"then moved {money(h['after_peak_variance'])} through {h['last_month']}")
    for title, frame in (("Material misses", s["material"]), ("Near misses (over $25K, 4-5%)", s["near"])):
        print(f"{title}:")
        for _, r in frame.iterrows():
            print(f"  {r['department']:<17} {r['month_name']}  {r['variance']:>+10,.0f}  {r['variance_pct']:+.1%}")
    flagged = s["phasing"][s["phasing"]["phasing_ratio"] > PHASING_RATIO_FLAG]
    if len(flagged):
        print(f"Data quality: {len(flagged)} of {len(s['phasing'])} departments have monthly budgets that swing "
              f"more than {PHASING_RATIO_FLAG}x (worst: {flagged.iloc[0]['department']} at "
              f"{flagged.iloc[0]['phasing_ratio']:.0f}x). Monthly variances there are hard to read.")
    if h["bad_budget_rows"]:
        print(f"Data quality: {h['bad_budget_rows']} rows have a budget of zero or less (see the Data Quality tab).")
    if len(s["dropped"]):
        print(f"Dropped rows: {len(s['dropped'])} (see the Dropped Rows tab):")
        for r in s["dropped"].itertuples():
            print(f"  line {r.source_line}: {r.reason}")


if __name__ == "__main__":
    main()
