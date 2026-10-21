"""
FP&A Budget Variance Pipeline
Karthik Bommisetty

Rebuilds my Excel budget vs actual analysis (2024 department opex, 8 departments
x 12 months) as a repeatable pipeline. The steps follow the same order as an
Alteryx Designer workflow:

    Input -> Data Cleanse -> Formula -> Filter -> Summarize -> Output

Run:  python pipeline.py
Out:  output/variance_report.xlsx, images/accuracy_gap.png, images/variance_scatter.png

The data is a practice dataset, not a real company's books.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parent
INPUT_CSV = ROOT / "data" / "budget_vs_actual_2024.csv"
OUTPUT_DIR = ROOT / "output"
IMAGE_DIR = ROOT / "images"

# Materiality rule: a department-month is a material miss only if it breaks BOTH
# thresholds. The $ test filters out noise on tiny months, the % test filters out
# big departments where $25K is a rounding error.
MATERIALITY_PCT = 0.05
MATERIALITY_USD = 25_000


# ---------------------------------------------------------------------------
# 1. Input
# ---------------------------------------------------------------------------
def load(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str)


# ---------------------------------------------------------------------------
# 2. Data Cleanse
# ---------------------------------------------------------------------------
def cleanse(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower()
    for col in df.columns:
        df[col] = df[col].str.strip()

    df["department"] = df["department"].str.replace(r"\s+", " ", regex=True)
    df["month"] = pd.to_datetime(df["month"], errors="coerce")
    for col in ("budget", "actual"):
        df[col] = pd.to_numeric(df[col].str.replace(r"[$,]", "", regex=True), errors="coerce")

    before = len(df)
    df = df.dropna(subset=["department", "month", "budget", "actual"])
    df = df.drop_duplicates(subset=["department", "month"])
    dropped = before - len(df)
    if dropped:
        print(f"  cleanse: dropped {dropped} bad or duplicate rows")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. Formula
# ---------------------------------------------------------------------------
def add_variance(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # Cost centers: positive variance = spent more than planned = Unfavorable
    df["variance"] = df["actual"] - df["budget"]
    df["variance_pct"] = df["variance"] / df["budget"]
    df["abs_variance"] = df["variance"].abs()
    df["fav_unfav"] = df["variance"].apply(lambda v: "Unfavorable" if v > 0 else "Favorable")
    df["month_num"] = df["month"].dt.month
    df["month_name"] = df["month"].dt.strftime("%b")
    return df


# ---------------------------------------------------------------------------
# 4. Filter
# ---------------------------------------------------------------------------
def flag_material(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["material_miss"] = (df["abs_variance"] > MATERIALITY_USD) & (
        df["variance_pct"].abs() > MATERIALITY_PCT
    )
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
        "gross_accuracy": 1 - gross_miss / budget,
        "material_misses": int(df["material_miss"].sum()),
        "jan_aug_variance": df.loc[df["month_num"] <= 8, "variance"].sum(),
        "sep_dec_variance": df.loc[df["month_num"] >= 9, "variance"].sum(),
    }

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
    by_dept["variance_pct"] = by_dept["variance"] / by_dept["budget"]
    by_dept["gross_accuracy"] = 1 - by_dept["gross_miss"] / by_dept["budget"]
    by_dept["fav_unfav"] = by_dept["variance"].apply(lambda v: "Unfavorable" if v > 0 else "Favorable")
    by_dept = by_dept.sort_values("variance", ascending=False).reset_index(drop=True)

    by_month = (
        df.groupby(["month_num", "month_name"])
        .agg(
            budget=("budget", "sum"),
            actual=("actual", "sum"),
            variance=("variance", "sum"),
            gross_miss=("abs_variance", "sum"),
            material_misses=("material_miss", "sum"),
        )
        .reset_index()
        .sort_values("month_num")
    )
    by_month["ytd_variance"] = by_month["variance"].cumsum()
    by_month["gross_accuracy"] = 1 - by_month["gross_miss"] / by_month["budget"]

    material = (
        df[df["material_miss"]]
        .sort_values("abs_variance", ascending=False)
        [["department", "month_name", "budget", "actual", "variance", "variance_pct", "fav_unfav"]]
        .reset_index(drop=True)
    )

    return {"headline": headline, "by_dept": by_dept, "by_month": by_month, "material": material}


# ---------------------------------------------------------------------------
# Reconciliation: the pipeline has to match the v2 Excel workbook to the dollar
# ---------------------------------------------------------------------------
EXPECTED = {
    "rows": 96,
    "total_budget": 28_221_717,
    "total_actual": 28_171_672,
    "net_variance": -50_045,
    "gross_misses": 1_206_143,
    "material_misses": 7,
    "jan_aug_variance": 247_760,
    "sep_dec_variance": -297_805,
}


def reconcile(h: dict) -> None:
    for key, expected in EXPECTED.items():
        assert round(h[key]) == expected, f"{key}: got {h[key]:,.0f}, expected {expected:,}"
    assert round(h["net_accuracy"], 3) == 0.998, h["net_accuracy"]
    assert round(h["gross_accuracy"], 3) == 0.957, h["gross_accuracy"]
    print("  reconcile: all figures tie to the Excel v2 workbook")


# ---------------------------------------------------------------------------
# 6. Output: Excel report
# ---------------------------------------------------------------------------
def write_excel(df: pd.DataFrame, s: dict, path: Path) -> None:
    h = s["headline"]
    summary = pd.DataFrame(
        [
            ("Total budget", h["total_budget"]),
            ("Total actual", h["total_actual"]),
            ("Net variance", h["net_variance"]),
            ("Net accuracy", h["net_accuracy"]),
            ("Gross misses", h["gross_misses"]),
            ("Gross accuracy", h["gross_accuracy"]),
            ("Material misses (of 96)", h["material_misses"]),
            ("Jan-Aug variance", h["jan_aug_variance"]),
            ("Sep-Dec variance", h["sep_dec_variance"]),
            ("Materiality: % threshold", MATERIALITY_PCT),
            ("Materiality: $ threshold", MATERIALITY_USD),
        ],
        columns=["Metric", "Value"],
    )

    detail = df[
        ["department", "month", "budget", "actual", "variance", "variance_pct", "fav_unfav", "abs_variance", "material_miss"]
    ].copy()
    detail["month"] = detail["month"].dt.strftime("%Y-%m")

    sheets = {
        "Summary": summary,
        "Material Misses": s["material"],
        "By Department": s["by_dept"],
        "By Month": s["by_month"].drop(columns="month_num"),
        "Variance Data": detail,
    }

    money = "$#,##0;($#,##0)"
    pct = "0.0%;(0.0%)"
    money_cols = {"budget", "actual", "variance", "abs_variance", "gross_miss", "ytd_variance"}
    pct_cols = {"variance_pct", "gross_accuracy"}

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, frame in sheets.items():
            frame.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            for col_idx, col in enumerate(frame.columns, start=1):
                letter = ws.cell(row=1, column=col_idx).column_letter
                ws.column_dimensions[letter].width = max(14, len(str(col)) + 4)
                fmt = money if col in money_cols else pct if col in pct_cols else None
                if fmt:
                    for row in range(2, len(frame) + 2):
                        ws.cell(row=row, column=col_idx).number_format = fmt
            if name == "Summary":
                ws.column_dimensions["A"].width = 28
                for r, metric in enumerate(summary["Metric"], start=2):
                    cell = ws.cell(row=r, column=2)
                    if "accuracy" in metric.lower() or "%" in metric:
                        cell.number_format = "0.0%"
                    elif "misses (of" not in metric:
                        cell.number_format = money


# ---------------------------------------------------------------------------
# 6. Output: charts
# ---------------------------------------------------------------------------
INK = "#1f2933"
MUTED = "#6b7280"
GRID = "#e5e7eb"
NAVY = "#1f4e79"
RED = "#c0392b"
GRAY = "#b8bec7"


def _style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=10)


def chart_accuracy_gap(h: dict, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5.2), dpi=200)
    labels = ["Net accuracy\n(misses cancel out)", "Gross accuracy\n(every miss counted)"]
    values = [h["net_accuracy"] * 100, h["gross_accuracy"] * 100]
    bars = ax.bar(labels, values, color=[GRAY, NAVY], width=0.5, zorder=3)

    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.15, f"{v:.1f}%",
                ha="center", va="bottom", fontsize=16, fontweight="bold", color=INK)

    ax.set_ylim(93, 100.6)
    ax.set_ylabel("Budget accuracy (%)", color=MUTED)
    ax.yaxis.grid(True, color=GRID, zorder=0)
    _style(ax)

    gap = values[0] - values[1]
    ax.plot([0.25, 1.36], [values[0], values[0]], color=RED, lw=0.8, ls=":")
    ax.annotate("", xy=(1.36, values[1]), xytext=(1.36, values[0]),
                arrowprops=dict(arrowstyle="<->", color=RED, lw=1.5))
    ax.text(1.42, (values[0] + values[1]) / 2,
            f"{gap:.1f} pts\n${h['gross_misses'] / 1e6:.2f}M of\noffsetting misses",
            color=RED, fontsize=10, va="center")

    ax.set_title("The 99.8% headline hides $1.21M of misses", loc="left",
                 fontsize=14, fontweight="bold", color=INK, pad=22)
    ax.text(0, 1.02, r"Net $= 1 - |\Sigma\,\mathrm{var}|\,/\,\Sigma\,\mathrm{budget}$"
                     r"     Gross $= 1 - \Sigma\,|\mathrm{var}|\,/\,\Sigma\,\mathrm{budget}$",
            transform=ax.transAxes, fontsize=9.5, color=MUTED)
    ax.set_xlim(-0.6, 2.0)
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

    normal = ~df["material_miss"]
    ax.scatter(x[normal], y[normal], s=34, color=GRAY, edgecolor="white", lw=0.6, zorder=3)
    ax.scatter(x[~normal], y[~normal], s=70, color=RED, edgecolor="white", lw=0.8, zorder=4)

    nudge = {("Finance", "Dec"): (6, -12), ("Marketing", "Mar"): (-8, -14)}
    for _, r in df[df["material_miss"]].iterrows():
        dx, dy = nudge.get((r["department"], r["month_name"]), (6, 4))
        ax.annotate(f"{r['department']} {r['month_name']}",
                    (r["variance_pct"] * 100, r["variance"] / 1000),
                    xytext=(dx, dy), textcoords="offset points", fontsize=8.5, color=INK,
                    ha="right" if dx < 0 else "left")

    ax.set_xlim(-xlim, xlim)
    ax.xaxis.set_major_locator(plt.MultipleLocator(2))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:+.0f}%" if v else "0%"))
    ax.set_ylim(-ylim, ylim)
    ax.set_xlabel(r"Variance as % of budget  (actual $-$ budget)", color=MUTED)
    ax.set_ylabel(r"Variance (\$K)", color=MUTED)
    _style(ax)

    n_mat = int(df["material_miss"].sum())
    ax.set_title(f"{n_mat} of {len(df)} department-months were material misses", loc="left",
                 fontsize=14, fontweight="bold", color=INK, pad=22)
    ax.text(0, 1.02, r"Material = $|\mathrm{var}| > \$25\mathrm{K}$ and $|\mathrm{var\,\%}| > 5\%$."
                     "  Top right = overspend, bottom left = underspend.",
            transform=ax.transAxes, fontsize=9.5, color=MUTED)

    legend = [
        Line2D([], [], marker="o", ls="", color=RED, markersize=8, label=f"Material miss ({n_mat})"),
        Line2D([], [], marker="o", ls="", color=GRAY, markersize=7, label=f"Within threshold ({len(df) - n_mat})"),
        Patch(color=RED, alpha=0.12, label="Materiality zone"),
    ]
    ax.legend(handles=legend, loc="upper left", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    IMAGE_DIR.mkdir(exist_ok=True)

    print("1. Input")
    raw = load(INPUT_CSV)
    print(f"  read {len(raw)} rows from {INPUT_CSV.name}")
    print("2. Data Cleanse")
    df = cleanse(raw)
    print("3. Formula")
    df = add_variance(df)
    print("4. Filter")
    df = flag_material(df)
    print(f"  {int(df['material_miss'].sum())} material misses")
    print("5. Summarize")
    s = summarize(df)
    reconcile(s["headline"])
    print("6. Output")
    write_excel(df, s, OUTPUT_DIR / "variance_report.xlsx")
    chart_accuracy_gap(s["headline"], IMAGE_DIR / "accuracy_gap.png")
    chart_variance_scatter(df, IMAGE_DIR / "variance_scatter.png")

    h = s["headline"]
    print()
    print(f"Budget ${h['total_budget']:,.0f} | Actual ${h['total_actual']:,.0f} | Net variance ${h['net_variance']:,.0f}")
    print(f"Net accuracy {h['net_accuracy']:.1%} | Gross accuracy {h['gross_accuracy']:.1%} | Gross misses ${h['gross_misses']:,.0f}")
    print(f"Jan-Aug ${h['jan_aug_variance']:,.0f} | Sep-Dec ${h['sep_dec_variance']:,.0f}")
    print("Material misses:")
    for _, r in s["material"].iterrows():
        print(f"  {r['department']:<12} {r['month_name']}  {r['variance']:>+10,.0f}  {r['variance_pct']:+.1%}")


if __name__ == "__main__":
    main()
