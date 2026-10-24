# Alteryx version

This is the same pipeline as the Python version, built as an Alteryx Designer workflow. It reads each department's own budget-vs-actual file, accounts for every row, and writes the variance report. On the 2024 data it matches the Python pipeline to the dollar, and `tests/test_alteryx_matches_python.py` in the repo root checks that.

![Alteryx canvas](images/alteryx_canvas.png)

## Run it

1. Open `FPA_Variance_Pipeline.yxmd` in Alteryx Designer (built and tested on 2025.2).
2. Press **Run**.
3. The Results window should say *"Integrity: all checks passed. 96 rows read, 96 kept, 0 dropped. Net accuracy 99.8%, gross accuracy 95.7%, 7 material misses."* with 0 errors and 0 warnings.
4. The outputs land in `output/`.

To see the error handling, open `FPA_Variance_Pipeline_messy_test.yxmd` instead. It reads two messy submissions in `tests/messy_departments/` and finishes with 1 error: *"STOPPED: $1,033,999 of actual spend plus 1 row(s) whose actual couldn't be read is on rows that were dropped (5 rows, listed in dropped_rows.csv)..."*. Every output still gets written, so `dropped_rows.csv` shows exactly which lines broke and why.

## What the workflow does

| Section | Tools | What happens |
|---|---|---|
| 1. Read | Input Data (wildcard `data/departments/*.csv`), Multi-Row Formula | Stacks all 8 department files into one stream. Each row keeps its file name and its line number in that file, so a bad row can be traced back to its source |
| 2. Parse and validate | Formula, Filter, Unique | Turns text into numbers and dates, strips `$` and commas, reads `(1,000)` as negative, and accepts `2024-01-01`, `3/1/2024` and `Feb 2024`. A row that can't be read gets a reason (`missing budget`, `unreadable month`...) and goes to the dropped-row log. Duplicate dept-months are split off |
| 3. Variance and materiality | Text Input (SETTINGS), Append Fields, Formula, Select, Filter, Sort | Variance, Fav / Unfav / On budget, and the material miss (>$25K **and** >5%) and near miss (>$25K, 4–5%) flags. **All rows stay in the main stream.** The filters only add exception lists on the side |
| 4. Dropped-row log | Join, Formula, Union, Select, Text Input, Summarize | Matches each duplicate to the row that was kept and labels it *identical* or *CONFLICTS (kept: budget X, actual Y)*. Flags any dropped row that carried real spend |
| 5. Summaries | Summarize, Formula, Sort, Running Total | By department (with the budget-phasing check), by month (with YTD), and company totals. These are all built from every row |
| 6. Integrity checks | Summarize, Append Fields, Formula, Message | Rows read = kept + dropped, department and month totals add up to the grand total, YTD ends at the net variance, and four more, plus the dropped-spend rule. A failed check, or dropped spend without the override, raises an **Error** in the Results window |

Thresholds live in the **SETTINGS** Text Input tool. Set `allow_dropped_spend` to 1 to report dropped spend and continue. The error then becomes a warning marked OVERRIDDEN.

## Mistakes this version avoids

These came from a first-draft plan for the workflow. Each one would have produced wrong numbers:

- **Summarizing the filter's False side.** It's tempting to send the "not material" rows to Summarize. That would drop the 7 material months from the executive totals, leaving net variance $27K off and gross misses $335K short. Here the summaries come from all rows.
- **Calculating gross accuracy per row.** A row-level `1 − |variance| / budget` can't be added or averaged into 95.7%. Gross accuracy is `1 − Σ|variance| ÷ Σ budget`, calculated after the Summarize.
- **Using Data Cleanse to strip `$` and commas.** Its "remove punctuation" option also strips minus signs and decimal points, so a −1,000 budget would quietly become 1000. Here a Formula uses regex instead.
- **`ToNumber("")` returns 0 in Alteryx.** A blank budget cell would silently become a $0 budget. The Formula only converts text that actually looks like a number, so a blank stays blank and the row is logged as `missing budget`.
- **Dividing by a zero or negative budget.** For those rows the % variance is left blank, the dollars stay in every total, and the department is flagged in `by_department.csv`.

## Outputs

| File | What's in it |
|---|---|
| `summary.csv` | Headline numbers (net vs gross accuracy, $1.16M cancelled out) and the result of every integrity check |
| `variance_data.csv` | Every kept row with variance, %, Fav / Unfav and flags, plus its source file and line |
| `material_misses.csv` / `near_misses.csv` | The 7 and the 4 |
| `by_department.csv` | Totals, gross accuracy and budget-phasing ratio per department |
| `by_month.csv` | Monthly totals and the YTD variance build |
| `dropped_rows.csv` | Every dropped row, its file and line, the reason, and whether it carried spend (empty on the clean 2024 data) |

`output_messy_test/` holds the outputs from the messy-data run.

## Rebuilding the workflow

`build_workflow.py` generates both `.yxmd` files from one definition, so the clean and messy-test versions can't drift apart, and every expression can be reviewed as text. Run `python build_workflow.py` after changing it, then open the workflow in Designer.

## Known limits

- Every file has to use the same four column headers (`department, month, budget, actual`). The wildcard input doesn't rename mismatched headers.
- When a check fails, the run ends with an error, but the outputs are still written. That's on purpose, so you can see why it failed. Check that the Results window shows 0 errors before trusting the numbers. `summary.csv` also records `all_checks_pass` and `dropped_spend_status`.
