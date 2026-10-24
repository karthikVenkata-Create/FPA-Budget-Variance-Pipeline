"""
Generates the Alteryx workflow files for the FP&A variance pipeline.

    python build_workflow.py

writes two workflows that share exactly the same logic:
    FPA_Variance_Pipeline.yxmd             reads data/departments/*.csv   -> output/
    FPA_Variance_Pipeline_messy_test.yxmd  reads tests/messy_departments/*.csv -> output_messy_test/

The workflow is generated from code so the two versions can't drift apart and every
expression is reviewable in one place. Open either .yxmd in Alteryx Designer and press Run.
"""

from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Small XML helpers
# ---------------------------------------------------------------------------
E = escape


def annotation(label):
    return f"""<Annotation DisplayMode="0"><Name /><AnnotationText>{E(label)}</AnnotationText><DefaultAnnotationText /><Left value="False" /></Annotation>"""


def node(tid, plugin, x, y, config, label="", engine=("AlteryxBasePluginsEngine.dll", None)):
    dll, entry = engine
    eng = f'<EngineSettings EngineDll="{dll}" EngineDllEntryPoint="{entry}" />' if entry else ""
    return f"""
    <Node ToolID="{tid}">
      <GuiSettings Plugin="{plugin}"><Position x="{x}" y="{y}" /></GuiSettings>
      <Properties><Configuration>{config}</Configuration>{annotation(label)}</Properties>
      {eng}
    </Node>"""


def container(tid, caption, x, y, w, h, children, fill="#ecf2f2"):
    return f"""
    <Node ToolID="{tid}">
      <GuiSettings Plugin="AlteryxGuiToolkit.ToolContainer.ToolContainer"><Position x="{x}" y="{y}" width="{w}" height="{h}" /></GuiSettings>
      <Properties><Configuration><Caption>{E(caption)}</Caption>
        <Style TextColor="#314c4a" FillColor="{fill}" BorderColor="#314c4a" Transparency="25" Margin="25" />
        <Disabled value="False" /><Folded value="False" /></Configuration>{annotation("")}</Properties>
      <ChildNodes>{"".join(children)}</ChildNodes>
    </Node>"""


BASE = "AlteryxBasePluginsGui."


def t_input(tid, x, y, path, label):
    cfg = f"""<Passwords /><File OutputFileName="FileName" RecordLimit="" SearchSubDirs="False" FileFormat="0">{E(path)}</File>
      <FormatSpecificOptions><CodePage>28591</CodePage><Delimeter>,</Delimeter><IgnoreErrors>False</IgnoreErrors>
      <FieldLen>254</FieldLen><AllowShareWrite>False</AllowShareWrite><HeaderRow>True</HeaderRow>
      <IgnoreQuotes>DoubleQuotes</IgnoreQuotes><ImportLine>1</ImportLine></FormatSpecificOptions>"""
    return node(tid, BASE + "DbFileInput.DbFileInput", x, y, cfg, label, ("AlteryxBasePluginsEngine.dll", "AlteryxDbFileInput"))


def t_output(tid, x, y, path, label):
    cfg = f"""<File MaxRecords="" FileFormat="0">{E(path)}</File><Passwords />
      <FormatSpecificOptions><LineEndStyle>CRLF</LineEndStyle><Delimeter>,</Delimeter><ForceQuotes>False</ForceQuotes>
      <HeaderRow>True</HeaderRow><CodePage>28591</CodePage><WriteBOM>False</WriteBOM></FormatSpecificOptions>
      <MultiFile value="False" />"""
    return node(tid, BASE + "DbFileOutput.DbFileOutput", x, y, cfg, label, ("AlteryxBasePluginsEngine.dll", "AlteryxDbFileOutput"))


def t_formula(tid, x, y, fields, label):
    """fields: list of (name, type, size, expression)"""
    ff = "".join(f'<FormulaField expression={quoteattr(expr)} field="{n}" size="{s}" type="{t}" />' for n, t, s, expr in fields)
    return node(tid, BASE + "Formula.Formula", x, y, f"<FormulaFields>{ff}</FormulaFields>", label,
                ("AlteryxBasePluginsEngine.dll", "AlteryxFormula"))


def t_filter(tid, x, y, expr, label):
    cfg = f"<Expression>{E(expr)}</Expression><Mode>Custom</Mode>"
    return node(tid, BASE + "Filter.Filter", x, y, cfg, label, ("AlteryxBasePluginsEngine.dll", "AlteryxFilter"))


def t_multirow(tid, x, y, field, ftype, expr, group, label):
    gb = "".join(f'<Field field="{g}" />' for g in group)
    cfg = f"""<UpdateField value="False" /><UpdateField_Name>{field}</UpdateField_Name><CreateField_Name>{field}</CreateField_Name>
      <CreateField_Type>{ftype}</CreateField_Type><CreateField_Size>4</CreateField_Size><OtherRows>Empty</OtherRows>
      <NumRows value="1" /><Expression>{E(expr)}</Expression><GroupByFields>{gb}</GroupByFields>"""
    return node(tid, BASE + "MultiRowFormula.MultiRowFormula", x, y, cfg, label,
                ("AlteryxBasePluginsEngine.dll", "AlteryxMultiRowFormula"))


def t_unique(tid, x, y, fields, label):
    uf = "".join(f'<Field field="{f}" />' for f in fields)
    return node(tid, BASE + "Unique.Unique", x, y, f"<UniqueFields>{uf}</UniqueFields>", label,
                ("AlteryxBasePluginsEngine.dll", "AlteryxUnique"))


def select_fields(spec, unknown):
    """spec: list of (field, selected, rename or None)"""
    s = ""
    for f, sel, rn in spec:
        r = f' rename="{E(rn)}"' if rn else ""
        s += f'<SelectField field="{E(f)}" selected="{sel}"{r} />'
    s += f'<SelectField field="*Unknown" selected="{unknown}" />'
    return f'<OrderChanged value="True" /><CommaDecimal value="False" /><SelectFields>{s}</SelectFields>'


def t_select(tid, x, y, spec, unknown, label):
    return node(tid, BASE + "AlteryxSelect.AlteryxSelect", x, y, select_fields(spec, unknown), label,
                ("AlteryxBasePluginsEngine.dll", "AlteryxSelect"))


def t_join(tid, x, y, keys, label):
    k = "".join(f'<Field field="{f}" />' for f in keys)
    cfg = f"""<JoinInfo connection="Left">{k}</JoinInfo><JoinInfo connection="Right">{k}</JoinInfo>
      <SelectConfiguration><Configuration outputConnection="Join">{select_fields([], "True")}</Configuration></SelectConfiguration>"""
    cfg = cfg.replace('<OrderChanged value="True" />', '<OrderChanged value="False" />')
    n = node(tid, BASE + "Join.Join", x, y, cfg, label, ("AlteryxBasePluginsEngine.dll", "AlteryxJoin"))
    return n.replace("<Configuration><JoinInfo", '<Configuration joinByRecordPos="False"><JoinInfo', 1)


def t_union(tid, x, y, label):
    cfg = """<ByName_ErrorMode>Warning</ByName_ErrorMode><ByName_OutputMode>All</ByName_OutputMode><Mode>ByName</Mode><SetOutputOrder value="False" />"""
    return node(tid, BASE + "Union.Union", x, y, cfg, label, ("AlteryxBasePluginsEngine.dll", "AlteryxUnion"))


def t_append(tid, x, y, label):
    cfg = f"""<CartesianMode>Error</CartesianMode><SelectConfiguration><Configuration outputConnection="Output">{select_fields([], "True")}</Configuration></SelectConfiguration>"""
    cfg = cfg.replace('<OrderChanged value="True" />', '<OrderChanged value="False" />')
    return node(tid, BASE + "AppendFields.AppendFields", x, y, cfg, label, ("AlteryxBasePluginsEngine.dll", "AlteryxAppendFields"))


def t_summarize(tid, x, y, spec, label):
    """spec: list of (field, action, rename)"""
    sf = "".join(f'<SummarizeField field="{E(f)}" action="{a}" rename="{E(r)}" />' for f, a, r in spec)
    return node(tid, "AlteryxSpatialPluginsGui.Summarize.Summarize", x, y, f"<SummarizeFields>{sf}</SummarizeFields>", label,
                ("AlteryxSpatialPluginsEngine.dll", "AlteryxSummarize"))


def t_sort(tid, x, y, spec, label):
    sf = "".join(f'<Field field="{f}" order="{o}" />' for f, o in spec)
    return node(tid, BASE + "Sort.Sort", x, y, f'<SortInfo locale="0">{sf}</SortInfo>', label,
                ("AlteryxBasePluginsEngine.dll", "AlteryxSort"))


def t_runtotal(tid, x, y, fields, label):
    rf = "".join(f'<Field field="{f}" />' for f in fields)
    return node(tid, BASE + "RunningTotal.RunningTotal", x, y, f"<GroupByFields /><RunningTotalFields>{rf}</RunningTotalFields>", label,
                ("AlteryxBasePluginsEngine.dll", "AlteryxRunningTotal"))


def t_textinput(tid, x, y, fields, rows, label):
    fl = "".join(f'<Field name="{f}" />' for f in fields)
    dt = "".join("<r>" + "".join(f"<c>{E(str(v))}</c>" for v in r) + "</r>" for r in rows)
    cfg = f'<NumRows value="{len(rows)}" /><Fields>{fl}</Fields><Data>{dt}</Data>'
    return node(tid, BASE + "TextInput.TextInput", x, y, cfg, label, ("AlteryxBasePluginsEngine.dll", "AlteryxTextInput"))


def t_message(tid, x, y, filt, mtype, expr, label):
    cfg = f"""<When>Filter</When><Filter>{E(filt)}</Filter><Type>{mtype}</Type><Priority>High</Priority>
      <Transient>False</Transient><MessageExpression>{E(expr)}</MessageExpression>"""
    return node(tid, BASE + "Message.Message", x, y, cfg, label, ("AlteryxBasePluginsEngine.dll", "AlteryxMessage"))


def t_textbox(tid, x, y, w, h, text, size="9", fill="#ffffff"):
    return f"""
    <Node ToolID="{tid}">
      <GuiSettings Plugin="AlteryxGuiToolkit.TextBox.TextBox"><Position x="{x}" y="{y}" width="{w}" height="{h}" /></GuiSettings>
      <Properties><Configuration><Text>{E(text)}</Text><Font name="Segoe UI" size="{size}" style="0" />
        <TextColor name="Black" /><FillColor r="{int(fill[1:3],16)}" g="{int(fill[3:5],16)}" b="{int(fill[5:7],16)}" />
        <Shape shape="0" /><Justification Justification="0" /></Configuration>{annotation("")}</Properties>
    </Node>"""


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------
def clean_num(col):
    # "$1,234" -> "1234", "(1,000)" -> "-1000". ToNumber("") returns 0 in Alteryx, so a blank
    # budget would silently become a $0 budget. The REGEX_Match guard turns it into Null instead.
    return f'REGEX_Replace(REGEX_Replace(Trim([{col}]), "[$,\\s]", ""), "^\\((.*)\\)$", "-$1")'


PARSE = [
    ("department_clean", "V_String", 254, 'Trim(REGEX_Replace([department], "\\s+", " "))'),
    ("month_txt", "V_String", 254, "Trim([month])"),
    ("month_date", "Date", 10,
     'IF REGEX_Match([month_txt], "\\d{4}-\\d{1,2}-\\d{1,2}") THEN DateTimeTrim(DateTimeParse([month_txt], "%Y-%m-%d"), "month")\n'
     'ELSEIF REGEX_Match([month_txt], "\\d{1,2}/\\d{1,2}/\\d{4}") THEN DateTimeTrim(DateTimeParse([month_txt], "%m/%d/%Y"), "month")\n'
     'ELSEIF REGEX_Match([month_txt], "[A-Za-z]{3} \\d{4}") THEN DateTimeTrim(DateTimeParse("01 " + [month_txt], "%d %b %Y"), "month")\n'
     "ELSE Null() ENDIF"),
    ("budget_txt", "V_String", 254, clean_num("budget")),
    ("actual_txt", "V_String", 254, clean_num("actual")),
    ("budget_num", "Double", 8, 'IIF(REGEX_Match([budget_txt], "-?\\d+(\\.\\d+)?"), ToNumber([budget_txt]), Null())'),
    ("actual_num", "Double", 8, 'IIF(REGEX_Match([actual_txt], "-?\\d+(\\.\\d+)?"), ToNumber([actual_txt]), Null())'),
    ("reason", "V_String", 254,
     "REGEX_Replace(\n"
     '  IIF(IsEmpty([department_clean]), "missing department; ", "") +\n'
     '  IIF(IsNull([month_date]), IIF(IsEmpty([month_txt]), "missing month; ", "unreadable month; "), "") +\n'
     '  IIF(IsNull([budget_num]), IIF(IsEmpty([budget_txt]), "missing budget; ", "unreadable budget; "), "") +\n'
     '  IIF(IsNull([actual_num]), IIF(IsEmpty([actual_txt]), "missing actual; ", "unreadable actual; "), ""),\n'
     '";\\s*$", "")'),
]

RAW_FIELDS = ["FileName", "department", "month", "budget", "actual", "source_line", "department_clean", "month_txt",
              "month_date", "budget_txt", "actual_txt", "budget_num", "actual_num", "reason"]

DUP_REASON = [
    ("reason", "V_String", 254,
     'IIF([budget_num] = [Right_budget_num] AND [actual_num] = [Right_actual_num],\n'
     '  "duplicate dept-month, identical to " + [Right_FileName] + " line " + ToString([Right_source_line]),\n'
     '  "duplicate dept-month, CONFLICTS with " + [Right_FileName] + " line " + ToString([Right_source_line]) +\n'
     '  " (kept: budget " + ToString([Right_budget_num], 0, 1) + ", actual " + ToString([Right_actual_num], 0, 1) + ")")'),
]

DROPPED_FLAGS = [
    ("dropped_flag", "Int32", 4, "1"),
    # Spend on an identical duplicate is still counted on the kept row. Any other dropped row with
    # nonzero actual spend, or an actual that couldn't be read (amount unknown), is spend at risk.
    ("unknown_actual", "Int32", 4, 'IIF(Contains([reason], "unreadable actual"), 1, 0)'),
    ("spend_at_risk", "Int32", 4,
     'IIF(!Contains([reason], "identical") AND ((!IsNull([actual_num]) AND [actual_num] != 0) OR [unknown_actual] = 1), 1, 0)'),
    ("actual_at_risk", "Double", 8, "IIF([spend_at_risk] = 1 AND !IsNull([actual_num]), [actual_num], 0)"),
    ("no_reason", "Int32", 4, "IIF(IsEmpty([reason]), 1, 0)"),
]

VARIANCE = [
    # Cost centers: positive variance = spent more than planned = Unfavorable
    ("variance", "Double", 8, "[actual_num] - [budget_num]"),
    # A cost-center budget of zero or less is almost always a data error: keep the dollars,
    # but a % of it is meaningless (and /0 breaks), so leave the % blank.
    ("budget_ok", "Int32", 4, "IIF([budget_num] > 0, 1, 0)"),
    ("bad_budget", "Int32", 4, "1 - [budget_ok]"),
    ("variance_pct", "Double", 8, "IIF([budget_ok] = 1, [variance] / [budget_num], Null())"),
    ("abs_variance", "Double", 8, "ABS([variance])"),
    ("fav_unfav", "V_String", 20, 'IIF([variance] > 0, "Unfavorable", IIF([variance] < 0, "Favorable", "On budget"))'),
    ("material_miss", "Int32", 4,
     "IIF([abs_variance] > [materiality_usd] AND !IsNull([variance_pct]) AND ABS([variance_pct]) > [materiality_pct], 1, 0)"),
    ("near_miss", "Int32", 4,
     "IIF([abs_variance] > [materiality_usd] AND !IsNull([variance_pct]) AND ABS([variance_pct]) > [near_miss_pct_floor]\n"
     "    AND ABS([variance_pct]) <= [materiality_pct], 1, 0)"),
    ("over_budget", "Double", 8, "IIF([variance] > 0, [variance], 0)"),
    ("under_budget", "Double", 8, "IIF([variance] < 0, -[variance], 0)"),
    ("budget_for_phasing", "Double", 8, "IIF([budget_ok] = 1, [budget_num], Null())"),
    ("pct_violation", "Int32", 4, "IIF([budget_ok] = 0 AND !IsNull([variance_pct]), 1, 0)"),
    ("both_flags", "Int32", 4, "[material_miss] * [near_miss]"),
    ("month_name", "V_String", 10, 'DateTimeFormat([month_date], "%b")'),
]

DEPT_FORMULA = [
    ("variance_pct", "Double", 8, "IIF([budget] > 0, [variance] / [budget], Null())"),
    ("gross_accuracy", "Double", 8, "1 - [gross_miss] / [budget]"),
    ("fav_unfav", "V_String", 20, 'IIF([variance] > 0, "Unfavorable", IIF([variance] < 0, "Favorable", "On budget"))'),
    ("phasing_ratio", "Double", 8, "[max_month_budget] / [min_month_budget]"),
    ("phasing_flag", "V_String", 254,
     'IIF([phasing_ratio] > [phasing_ratio_flag], "Question this phasing", "") +\n'
     'IIF([bad_budget_months] > 0, IIF([phasing_ratio] > [phasing_ratio_flag], "; ", "") + "has budget <= 0 (ratio uses valid months only)", "")'),
]

MONTH_FORMULA = [
    ("ytd_variance", "Double", 8, "[RunTot_variance]"),
    ("month_label", "V_String", 20, 'DateTimeFormat([month], "%b %Y")'),
    ("gross_accuracy", "Double", 8, "1 - [gross_miss] / [budget]"),
]

TOL = "0.01"
CHECKS = [
    ("net_accuracy", "Double", 8, "1 - ABS([net_variance]) / [total_budget]"),
    ("gross_accuracy", "Double", 8, "1 - [gross_misses] / [total_budget]"),
    ("cancelled_out", "Double", 8, "[gross_misses] - ABS([net_variance])"),
    ("chk_rows_balance", "Int32", 4, "IIF([rows_read] = [rows_kept] + [rows_dropped], 1, 0)"),
    ("chk_dropped_reason", "Int32", 4, "IIF([rows_no_reason] = 0, 1, 0)"),
    ("chk_dept_totals", "Int32", 4,
     f"IIF(ABS([dept_budget] - [total_budget]) < {TOL} AND ABS([dept_actual] - [total_actual]) < {TOL}\n"
     f"    AND ABS([dept_variance] - [net_variance]) < {TOL}, 1, 0)"),
    ("chk_month_totals", "Int32", 4,
     f"IIF(ABS([month_budget] - [total_budget]) < {TOL} AND ABS([month_actual] - [total_actual]) < {TOL}, 1, 0)"),
    ("chk_ytd_ends_at_net", "Int32", 4, f"IIF(ABS([ytd_last] - [net_variance]) < {TOL}, 1, 0)"),
    ("chk_gross_ge_net", "Int32", 4, f"IIF([gross_misses] + {TOL} >= ABS([net_variance]), 1, 0)"),
    ("chk_flags_exclusive", "Int32", 4, "IIF([both_flags] = 0, 1, 0)"),
    ("chk_pct_only_valid_budget", "Int32", 4, "IIF([pct_violations] = 0, 1, 0)"),
    ("failed_checks", "V_String", 1000,
     'REGEX_Replace(\n'
     '  IIF([chk_rows_balance] = 0, "rows read <> kept + dropped; ", "") +\n'
     '  IIF([chk_dropped_reason] = 0, "a dropped row has no reason; ", "") +\n'
     '  IIF([chk_dept_totals] = 0, "department totals <> grand total; ", "") +\n'
     '  IIF([chk_month_totals] = 0, "monthly totals <> annual total; ", "") +\n'
     '  IIF([chk_ytd_ends_at_net] = 0, "YTD variance <> net variance; ", "") +\n'
     '  IIF([chk_gross_ge_net] = 0, "gross misses < |net variance|; ", "") +\n'
     '  IIF([chk_flags_exclusive] = 0, "material and near-miss flags overlap; ", "") +\n'
     '  IIF([chk_pct_only_valid_budget] = 0, "variance % on a budget <= 0; ", ""),\n'
     '";\\s*$", "")'),
    ("all_checks_pass", "Int32", 4, "IIF(IsEmpty([failed_checks]), 1, 0)"),
    ("dropped_spend_status", "V_String", 1000,
     'IIF([spend_rows] = 0, "Pass",\n'
     '  IIF([allow_dropped_spend] = 1,\n'
     '    "OVERRIDDEN: $" + ToString([dropped_spend], 0, 1) + " of actual spend" +\n'
     '    IIF([unknown_actual_rows] > 0, " plus " + ToString([unknown_actual_rows]) + " row(s) whose actual couldn\'t be read", "") +\n'
     '    " dropped (see dropped_rows.csv)",\n'
     '    "FAIL"))'),
]


def fit_container(tid, caption, children, fill="#ecf2f2", pad_l=30, pad_t=45, pad_r=95, pad_b=95):
    import re
    pos = [(int(a), int(b)) for a, b in re.findall(r'<Position x="(\d+)" y="(\d+)" />', "".join(children))]
    x0 = min(p[0] for p in pos) - pad_l
    y0 = min(p[1] for p in pos) - pad_t
    x1 = max(p[0] for p in pos) + pad_r
    y1 = max(p[1] for p in pos) + pad_b
    return container(tid, caption, x0, y0, x1 - x0, y1 - y0, children, fill)


def build(input_glob, out_dir):
    o = lambda name: f"{out_dir}\\{name}"
    P = lambda col, row: (int(round(90 + col * 110 + 100 * ((col >= 2) + (col >= 5) + (col >= 13)))),
                         int(round(230 + row * 110)))   # canvas grid, with gaps between sections
    n = []
    c = []                             # connections: (from, anchor, to, anchor, name)

    def link(a, b, aa="Output", ba="Input", name=None):
        c.append((a, aa, b, ba, name))

    # ---- 1. Read --------------------------------------------------------
    r1 = [
        t_input(1, *P(0, 1), input_glob, "Read every department file (wildcard)"),
        t_multirow(2, *P(1, 1), "source_line", "Int32",
                   "IIF(IsEmpty([Row-1:source_line]) OR [Row-1:source_line] = 0, 2, [Row-1:source_line] + 1)",
                   ["FileName"], "Line number in its CSV (header = line 1)"),
        t_summarize(3, *P(1, 2), [("FileName", "Count", "rows_read")], "Rows read"),
    ]
    link(1, 2); link(2, 3)
    n.append(fit_container(100, "1. Read every department's file", r1))

    # ---- 2. Parse & validate -------------------------------------------
    r2 = [
        t_formula(4, *P(2, 1), PARSE, "Parse text to numbers and dates; record why a row is bad"),
        t_filter(5, *P(3, 1), "IsEmpty([reason])", "Row readable?"),
        t_unique(6, *P(4, 1), ["department_clean", "month_date"], "One row per dept-month"),
    ]
    link(2, 4); link(4, 5); link(5, 6, "True", "Input")
    n.append(fit_container(101, "2. Parse and validate every row", r2))

    # ---- 4. Variance and materiality ------------------------------------
    r4 = [
        t_textinput(17, *P(5, -0.25), ["materiality_usd", "materiality_pct", "near_miss_pct_floor", "phasing_ratio_flag",
                                   "allow_dropped_spend"], [[25000, 0.05, 0.04, 10, 0]],
                    "SETTINGS: edit thresholds here (allow_dropped_spend: 1 = report and continue)"),
        t_append(18, *P(5, 1), "Attach settings to every row"),
        t_formula(19, *P(6, 1), VARIANCE, "Variance, Fav / Unfav, material and near miss"),
        t_select(20, *P(7, 1),
                 [("department_clean", "True", "department"), ("month_date", "True", "month"),
                  ("budget_num", "True", "budget"), ("actual_num", "True", "actual"), ("variance", "True", None),
                  ("variance_pct", "True", None), ("abs_variance", "True", None), ("fav_unfav", "True", None),
                  ("material_miss", "True", None), ("near_miss", "True", None), ("FileName", "True", None),
                  ("source_line", "True", None)], "False", "Tidy columns"),
        t_output(21, *P(8, 0), o("variance_data.csv"), "variance_data.csv (all rows)"),
        t_filter(22, *P(8, 1), "[material_miss] = 1", "Material miss? (>$25K and >5%)"),
        t_sort(23, *P(9, 1), [("abs_variance", "Descending")], "Biggest first"),
        t_output(24, *P(10, 1), o("material_misses.csv"), "material_misses.csv"),
        t_filter(25, *P(8, 2), "[near_miss] = 1", "Near miss? (>$25K, 4-5%)"),
        t_output(26, *P(9, 2), o("near_misses.csv"), "near_misses.csv"),
    ]
    link(6, 18, "Unique", "Targets"); link(17, 18, "Output", "Source")
    link(18, 19); link(19, 20); link(20, 21); link(20, 22); link(22, 23, "True", "Input"); link(23, 24)
    link(20, 25); link(25, 26, "True", "Input")
    n.append(fit_container(103, "3. Variance and materiality (all rows stay in; filters only add exception lists)", r4, fill="#eef3fb"))

    # ---- 3. Dropped rows (nothing disappears silently) ------------------
    r3 = [
        t_join(7, *P(5, 3.4), ["department_clean", "month_date"], "Match each duplicate to the row that was kept"),
        t_formula(8, *P(6, 3.4), DUP_REASON, "Identical or CONFLICTING duplicate?"),
        t_select(9, *P(7, 3.4), [(f"Right_{f}", "False", None) for f in RAW_FIELDS], "True", "Drop the matched row's columns"),
        t_union(10, *P(8, 3.4), "All dropped rows"),
        t_formula(11, *P(9, 3.4), DROPPED_FLAGS, "Flag spend at risk"),
        t_select(12, *P(10, 3.4),
                 [("FileName", "True", None), ("source_line", "True", None), ("department", "True", None),
                  ("month", "True", None), ("budget", "True", None), ("actual", "True", None),
                  ("reason", "True", None), ("spend_at_risk", "True", None)], "False", "Columns for the log"),
        t_output(13, *P(11, 3.4), o("dropped_rows.csv"), "dropped_rows.csv"),
        t_select(50, *P(10, 4.4),
                 [("dropped_flag", "True", None), ("spend_at_risk", "True", None), ("actual_at_risk", "True", None),
                  ("unknown_actual", "True", None), ("no_reason", "True", None)], "False", "Count columns only"),
        t_textinput(14, *P(10, 5.4), ["dropped_flag", "spend_at_risk", "actual_at_risk", "unknown_actual", "no_reason"],
                    [[0, 0, 0, 0, 0]], "Zero row: counts exist even when nothing is dropped"),
        t_union(15, *P(11, 4.9), "Dropped + zero row"),
        t_summarize(16, *P(12, 4.9), [("dropped_flag", "Sum", "rows_dropped"), ("spend_at_risk", "Sum", "spend_rows"),
                                      ("actual_at_risk", "Sum", "dropped_spend"), ("unknown_actual", "Sum", "unknown_actual_rows"),
                                      ("no_reason", "Sum", "rows_no_reason")], "Dropped-row totals"),
    ]
    link(6, 7, "Duplicates", "Left"); link(6, 7, "Unique", "Right")
    link(7, 8, "Join", "Input"); link(8, 9)
    link(5, 10, "False", "Input", "#1"); link(9, 10, "Output", "Input", "#2")
    link(10, 11); link(11, 12); link(12, 13)
    link(11, 50); link(50, 15, "Output", "Input", "#1"); link(14, 15, "Output", "Input", "#2"); link(15, 16)
    n.append(fit_container(102, "4. Log every dropped row with its reason (nothing disappears silently)", r3, fill="#fbeeee"))

    # ---- 5. Summaries (built from ALL rows, never from the filter's False side) ----
    r5 = [
        t_summarize(27, *P(7, 7.5), [("department_clean", "GroupBy", "department"), ("budget_num", "Sum", "budget"),
                     ("actual_num", "Sum", "actual"), ("variance", "Sum", "variance"), ("abs_variance", "Sum", "gross_miss"),
                     ("material_miss", "Sum", "material_misses"), ("budget_for_phasing", "Min", "min_month_budget"),
                     ("budget_for_phasing", "Max", "max_month_budget"), ("bad_budget", "Sum", "bad_budget_months"),
                     ("phasing_ratio_flag", "Max", "phasing_ratio_flag")], "By department"),
        t_formula(28, *P(8, 7.5), DEPT_FORMULA, "Gross accuracy and budget phasing check"),
        t_sort(29, *P(9, 7.5), [("variance", "Descending")], "Biggest overspend first"),
        t_output(30, *P(10, 7.5), o("by_department.csv"), "by_department.csv"),
        t_summarize(31, *P(7, 8.5), [("month_date", "GroupBy", "month"), ("budget_num", "Sum", "budget"), ("actual_num", "Sum", "actual"),
                     ("variance", "Sum", "variance"), ("abs_variance", "Sum", "gross_miss"),
                     ("material_miss", "Sum", "material_misses")], "By month"),
        t_sort(32, *P(8, 8.5), [("month", "Ascending")], "Date order (works for fiscal years)"),
        t_runtotal(33, *P(9, 8.5), ["variance"], "Year-to-date variance"),
        t_formula(34, *P(10, 8.5), MONTH_FORMULA, "Label and gross accuracy"),
        t_select(35, *P(11, 8.5), [("RunTot_variance", "False", None)], "True", ""),
        t_output(36, *P(12, 8.5), o("by_month.csv"), "by_month.csv"),
        t_summarize(37, *P(7, 9.5), [("department_clean", "Count", "rows_kept"), ("budget_num", "Sum", "total_budget"),
                     ("actual_num", "Sum", "total_actual"), ("variance", "Sum", "net_variance"),
                     ("abs_variance", "Sum", "gross_misses"), ("over_budget", "Sum", "over_budget"),
                     ("under_budget", "Sum", "under_budget"), ("material_miss", "Sum", "material_misses"),
                     ("near_miss", "Sum", "near_misses"), ("bad_budget", "Sum", "bad_budget_rows"),
                     ("pct_violation", "Sum", "pct_violations"), ("both_flags", "Sum", "both_flags"),
                     ("allow_dropped_spend", "Max", "allow_dropped_spend")], "Company totals"),
    ]
    link(19, 27); link(27, 28); link(28, 29); link(29, 30)
    link(19, 31); link(31, 32); link(32, 33); link(33, 34); link(34, 35); link(35, 36)
    link(19, 37)
    n.append(fit_container(104, "5. Summaries: built from every row, not from the filter's False side", r5))

    # ---- 6. Integrity checks --------------------------------------------
    r6 = [
        t_summarize(38, *P(13, 7.5), [("budget", "Sum", "dept_budget"), ("actual", "Sum", "dept_actual"),
                                    ("variance", "Sum", "dept_variance")], "Check: department totals"),
        t_summarize(39, *P(13, 8.5), [("budget", "Sum", "month_budget"), ("actual", "Sum", "month_actual"),
                                    ("ytd_variance", "Last", "ytd_last")], "Check: monthly totals and YTD"),
        t_append(40, *P(14, 9.5), "+ rows read"),
        t_append(41, *P(15, 9.5), "+ dropped totals"),
        t_append(42, *P(16, 9.5), "+ department check"),
        t_append(43, *P(17, 9.5), "+ month check"),
        t_formula(44, *P(18, 9.5), CHECKS, "Accuracy, 8 integrity checks, dropped-spend rule"),
        t_output(45, *P(19, 8.5), o("summary.csv"), "summary.csv (headline numbers and every check)"),
        t_message(46, *P(19, 9.5), "[dropped_spend_status] = \"FAIL\"", "Error",
                  '"STOPPED: $" + ToString([dropped_spend], 0, 1) + " of actual spend" + '
                  'IIF([unknown_actual_rows] > 0, " plus " + ToString([unknown_actual_rows]) + " row(s) whose actual couldn\'t be read", "") + '
                  '" is on rows that were dropped (" + ToString([spend_rows]) + " rows, listed in dropped_rows.csv). '
                  'Fix the source files, or set allow_dropped_spend = 1 in the SETTINGS tool to report it and continue."',
                  "Error if real spend was dropped"),
        t_message(47, *P(19, 10.5), "[all_checks_pass] = 0", "Error",
                  '"Integrity checks failed: " + [failed_checks]', "Error if any check fails"),
        t_message(48, *P(20, 9.5), 'StartsWith([dropped_spend_status], "OVERRIDDEN")', "Warning",
                  '"Dropped-spend check " + [dropped_spend_status]', "Warn when overridden"),
        t_message(49, *P(20, 10.5), '[all_checks_pass] = 1 AND [dropped_spend_status] = "Pass"', "Message",
                  '"Integrity: all checks passed. " + ToString([rows_read]) + " rows read, " + ToString([rows_kept]) + " kept, " + '
                  'ToString([rows_dropped]) + " dropped. Net accuracy " + ToString([net_accuracy] * 100, 1) + "%, gross accuracy " + '
                  'ToString([gross_accuracy] * 100, 1) + "%, " + ToString([material_misses]) + " material misses."',
                  "Success message"),
    ]
    link(29, 38); link(34, 39)
    link(37, 40, "Output", "Targets"); link(3, 40, "Output", "Source")
    link(40, 41, "Output", "Targets"); link(16, 41, "Output", "Source")
    link(41, 42, "Output", "Targets"); link(38, 42, "Output", "Source")
    link(42, 43, "Output", "Targets"); link(39, 43, "Output", "Source")
    link(43, 44); link(44, 45); link(44, 46); link(44, 47); link(44, 48); link(44, 49)
    n.append(fit_container(105, "6. Integrity checks: the run errors out if the numbers don't hold together", r6, fill="#f3f0e6"))

    n.append(t_textbox(90, 60, 40, 760, 110,
                       "FP&A Budget Variance Pipeline (Alteryx)  |  Karthik Bommisetty\n"
                       "Reads every department's budget vs actual file, accounts for every row, and shows why "
                       "99.8% net accuracy hides $1.21M of misses (95.7% gross).\n"
                       "Thresholds live in the SETTINGS tool. Results go to the output folder; the Results window "
                       "says whether every integrity check passed.", "10", "#e1e7f2"))

    conns = ""
    for a, aa, b, ba, name in c:
        nm = f' name="{name}"' if name else ""
        conns += f'\n    <Connection{nm}><Origin ToolID="{a}" Connection="{aa}" /><Destination ToolID="{b}" Connection="{ba}" /></Connection>'

    props = """
  <Properties>
    <Memory default="True" /><GlobalRecordLimit value="0" /><TempFiles default="True" />
    <Annotation on="True" includeToolName="False" />
    <ConvErrorLimit value="10" /><ConvErrorLimit_Stop value="False" />
    <CancelOnError value="False" />
    <DisableBrowse value="False" /><EnablePerformanceProfiling value="False" /><RunWithE2 value="True" />
    <SortedGrouping value="True" /><PredictiveToolsCodePage value="1252" /><DisableAllOutput value="False" />
    <ShowAllMacroMessages value="False" /><ShowConnectionStatusIsOn value="True" />
    <ShowConnectionStatusOnlyWhenRunning value="True" /><ZoomLevel value="0" /><LayoutType>Horizontal</LayoutType>
    <MetaInfo><NameIsFileName value="True" /><Name>FPA_Variance_Pipeline</Name>
      <Description>Budget vs actual variance pipeline: row accounting, materiality, net vs gross accuracy, integrity checks.</Description>
      <RootToolName /><ToolVersion /><ToolInDb value="False" /><CategoryName /><SearchTags />
      <Author>Karthik Bommisetty</Author><Company /><Copyright /><DescriptionLink actual="" displayed="" />
      <Example><Description /><File /></Example></MetaInfo>
    <Events><Enabled value="True" /></Events>
  </Properties>"""
    return f'<?xml version="1.0"?>\n<AlteryxDocument yxmdVer="2025.2">\n  <Nodes>{"".join(n)}\n  </Nodes>\n  <Connections>{conns}\n  </Connections>{props}\n</AlteryxDocument>\n'



if __name__ == "__main__":
    (HERE / "FPA_Variance_Pipeline.yxmd").write_text(build(r"data\departments\*.csv", "output"), encoding="utf-8")
    (HERE / "FPA_Variance_Pipeline_messy_test.yxmd").write_text(
        build(r"tests\messy_departments\*.csv", "output_messy_test"), encoding="utf-8")
    print("wrote FPA_Variance_Pipeline.yxmd and FPA_Variance_Pipeline_messy_test.yxmd")
