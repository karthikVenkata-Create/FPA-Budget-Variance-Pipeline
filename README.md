# FP&A Budget Variance Pipeline

**Karthik Bommisetty** · UIC MBA (Finance) + MS Business Analytics

**[Try the interactive version →](https://karthikvenkata-create.github.io/fpa.html)** · [My website](https://karthikvenkata-create.github.io) · [LinkedIn](https://www.linkedin.com/in/karthik-bommisetty)

I rebuilt my Excel budget-vs-actual project as a Python pipeline. It turns any department-by-month budget vs actual file into a variance report, checks its own math on every run, and on my 2024 file it matches my Excel workbook to the dollar. The data covers $28.2M of 2024 operating spend across 8 departments and 12 months, 96 department-months in total.

> The data is a practice dataset, not a real company's books. The monthly budget phasing in particular is synthetic (see [About the data](#about-the-data)), so the timing patterns below show the method rather than a real finding.

## Summary

- **The headline number hides the misses.** Net budget accuracy is **99.8%**, but only because overspends and underspends cancel each other out. Total misses come to **$1.21M** ($578K over budget, $628K under), and **$1.16M** of that cancelled out, leaving a net of −$50K. Counting every miss, accuracy is **95.7%**.
- **7 of 96 department-months were material misses**, meaning both more than $25K *and* more than 5% off budget. Another 4 were near misses: over $25K but between 4% and 5%.
- **The year looks on plan because of timing.** Spend ran $248K over plan through August, then $298K under from September to December. Three of the seven material misses are R&D in Q4.
- **The biggest finding is about the budget itself.** Every department's monthly budget swings at least 20x across the year, and Customer Success swings 512x. In a real company, phasing this lumpy would be the first thing I'd question, because it makes monthly variances almost meaningless.

![Net vs gross accuracy](images/accuracy_gap.png)

![Variance scatter](images/variance_scatter.png)

## The 7 material misses

| Department | Month | Variance | % of budget |
|---|---|---|---|
| R&D | Dec | −$76,990 | −8.4% |
| HR | Mar | +$60,759 | +5.5% |
| R&D | Oct | −$46,734 | −8.5% |
| Operations | Apr | +$46,284 | +5.4% |
| Marketing | Mar | +$37,782 | +6.0% |
| Finance | Dec | +$36,319 | +7.9% |
| R&D | Nov | −$29,963 | −7.1% |

Positive means overspend (unfavorable). These are cost centers, so coming in under budget is favorable, and a variance of exactly $0 is labeled "On budget."

**Near misses.** I define a near miss as passing the dollar test (over $25K) but landing between 4% and 5%. That gives exactly four: HR Nov (−$60,692, −4.9%), R&D Apr (+$39,045, +4.7%), Customer Success Dec (−$32,685, −4.7%) and Marketing Jul (+$41,995, +4.6%). All the thresholds are config values at the top of `pipeline.py`, so a stricter policy is a one-line change.

The rule needs both tests. With the dollar test alone, 15 months get flagged. With the percent test alone, 47 do, mostly small months where a few thousand dollars is a big percentage. Requiring both gets it down to the 7 that matter on both counts.

## About the data

The monthly budgets don't look like a real company's. Sales is budgeted $18.6K in April, $6.5K in August and $1.09M in September. Marketing goes from $1.31M in January to $4.3K in June. Real department budgets don't swing like that month to month.

The pipeline flags this automatically on a "Data Quality" tab. Any department whose biggest monthly budget is more than 10x its smallest gets flagged, and all 8 departments here do:

| Department | Smallest month | Biggest month | Swing |
|---|---|---|---|
| Customer Success | $1,363 | $697,211 | 512x |
| Marketing | $4,280 | $1,310,207 | 306x |
| Sales | $6,473 | $1,090,283 | 168x |
| Operations | $15,447 | $936,211 | 61x |
| Finance | $22,781 | $1,107,759 | 49x |
| R&D | $27,468 | $912,818 | 33x |
| HR | $37,393 | $1,239,326 | 33x |
| IT | $28,305 | $592,649 | 21x |

Here's what that means for the analysis. The annual and department-level numbers (net vs gross accuracy, which departments over- or underspent) still hold up. The month-level story doesn't. Patterns like "R&D underspent in Q4" are what the method would surface, but with phasing this lumpy, a monthly variance mostly tells you the budget was put in the wrong month. On a real budget, I'd want the phasing fixed before reading anything into individual months.

## Pipeline

The steps follow the same order you'd lay out on an Alteryx Designer canvas:

```mermaid
flowchart LR
    A["📥 Input<br/>any budget vs actual CSV"] --> B["🧹 Data Cleanse<br/>trim, strip $, parse dates,<br/>drop bad rows, dedupe"]
    B --> C["🧮 Formula<br/>variance = actual − budget<br/>fav / unfav / on budget"]
    C --> D["🔍 Filter<br/>material: >$25K AND >5%<br/>near miss: >$25K, 4–5%"]
    D --> E["Σ Summarize<br/>by dept, by month, YTD<br/>net vs gross, phasing"]
    E --> F["✅ Integrity checks<br/>totals in = totals out<br/>parts add to whole"]
    F --> G["📤 Output<br/>variance_report.xlsx<br/>+ 2 charts"]
```

| Step | What it does |
|---|---|
| Input | Reads the raw CSV as text so nothing gets silently converted |
| Data Cleanse | Trims whitespace, strips `$` and commas, reads `(1,234)` as negative, handles mixed date formats, drops rows with missing or unreadable values, removes duplicate dept-months |
| Formula | Variance, variance %, absolute variance, Favorable / Unfavorable / On budget |
| Filter | Flags material misses and near misses |
| Summarize | Totals, net and gross accuracy, by department, by month with YTD build, budget phasing check |
| Integrity checks | Nine checks that hold for **any** input file (below). The run stops if one fails |
| Output | Excel report (8 tabs) and two PNG charts |

**Integrity checks (every run, any data):** one row per department-month; budget in = budget out; actual in = actual out; department totals add to the grand total; monthly totals add to the annual total; year-to-date variance ends at the net variance; variance = actual − budget on every row; gross misses ≥ |net variance|; material and near-miss flags never overlap.

**One-time validation (2024 file only):** `tests/test_baseline_2024.py` checks that this pipeline reproduces my Excel v2 workbook to the dollar. Those expected numbers are hardcoded on purpose, because they only apply to this one file. A new file gets the integrity checks, not this test.

**Accuracy definitions**

- Net accuracy = 1 − |Σ variance| / Σ budget, which lets misses cancel out
- Gross accuracy = 1 − Σ |variance| / Σ budget, which counts every miss
- Cancelled out = Σ |variance| − |Σ variance|

## Why a pipeline instead of Excel

My first version of this project was in Excel with Power Query. It reported 99.8% accuracy and called Marketing the "top performer" for going over budget, and both of those were wrong. Rebuilding it as a pipeline is what made the errors obvious, and it also changes how the work holds up:

- **Repeatable.** Next month's file runs through the same steps: `python pipeline.py path/to/new_file.csv`. There's no copy-paste and there are no broken `#REF!` links. My v1 dashboard actually had `#REF!` errors in its filter panel.
- **Self-checking.** The integrity checks run on every file, so a bad input or a logic change can't quietly shift the totals. The tests include a deliberately broken summary to prove the checks catch it.
- **Tested on messy input.** `tests/fixtures/messy_sample.csv` has `$` signs, extra spaces, three date formats, an accounting-style negative, a duplicate row and unreadable values. The tests check exactly which rows survive and what they turn into.
- **Auditable.** Every rule is in code, in order. A reviewer can see exactly how a number was produced instead of clicking through cells.
- **Configurable.** Materiality, near-miss and phasing thresholds live in one place instead of being buried in formulas.

Excel is still the right tool for the final output a finance manager actually opens, so that's where the pipeline sends its results.

## Run it

```bash
pip install -r requirements.txt
python pipeline.py                                    # the 2024 data
python pipeline.py tests/fixtures/messy_sample.csv    # any other file
python -m pytest                                      # 16 tests
```

Outputs land in `output/variance_report.xlsx` and `images/`.

## Repo layout

```
├── pipeline.py                        # the whole pipeline
├── data/budget_vs_actual_2024.csv     # 96 dept-months, raw input
├── output/variance_report.xlsx        # Summary, Material Misses, Near Misses, By Department,
│                                      # By Month, Data Quality, Integrity Checks, Variance Data
├── images/accuracy_gap.png
├── images/variance_scatter.png
├── tests/
│   ├── test_cleanse.py                # messy input file
│   ├── test_integrity.py              # checks pass on new data, catch a broken summary
│   ├── test_baseline_2024.py          # one-time match to the Excel v2 workbook
│   └── fixtures/messy_sample.csv
└── requirements.txt
```

## What's next

The natural next step is a full-year reforecast: given actuals through September, where does the year land? That's most of what FP&A teams actually do, more than looking backward at variance. The pipeline already handles partial-year files (there's a test for it), so a reforecast would build on top of it.

## Project history

| Version | Date | Tool | What changed |
|---|---|---|---|
| v1 | Mar 2026 | Excel + Power Query | Original dashboard, reported 99.8% accuracy |
| v2 | Oct 2026 | Excel rebuild | Fixed sign logic, added gross accuracy, materiality, YTD timing |
| v3 | Oct 2026 | Python pipeline | This repo. Same numbers, plus integrity checks, near misses, phasing check and tests |

**Tools:** Python (pandas, matplotlib, openpyxl, pytest) · Excel · Power Query · Alteryx Designer Core certified
