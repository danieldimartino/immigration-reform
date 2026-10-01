"""
Reader for the DHS Office of Homeland Security Statistics (OHSS) workbooks.

Every OHSS table sheet has the same shape: a few title rows, one header row
whose first cell names the row dimension (e.g. "Region and country of birth"
or "Year"), the data, then footnotes and a "Source:" line. Section labels in
capitals ("REGION", "COUNTRY", "TOTAL") separate blocks. Footnote markers are
glued to labels ("Children1", "1976 3"). This module hides all of that.
"""
import re

import openpyxl

FOOTNOTE = re.compile(r"\s*\d$")          # "Children1" -> "Children"
YEAR_LABEL = re.compile(r"^(\d{4})(?:\s+\d)?$")   # "1976 3" -> 1976
NOT_A_NUMBER = {"NA", "X", "D", "-", "–", "—", None, ""}


def sheet_rows(path, sheet):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if sheet not in wb.sheetnames:
        raise SystemExit(f"FAIL: {path.name} has no sheet {sheet!r}; "
                         f"sheets are {wb.sheetnames}")
    return [tuple(r) for r in wb[sheet].iter_rows(values_only=True)]


def find_sheet(path, title_contains):
    """The sheet whose table-of-contents entry contains the given text."""
    for row in sheet_rows(path, "TOC"):
        if len(row) > 1 and row[1] and title_contains.lower() in str(row[1]).lower():
            return str(row[0]).strip()
    raise SystemExit(f"FAIL: no table titled like {title_contains!r} in {path.name}")


def clean_label(value):
    s = str(value).replace("\n", " ").strip()
    return FOOTNOTE.sub("", s).strip()


def number(value):
    if value in NOT_A_NUMBER or (isinstance(value, str) and value.strip() in NOT_A_NUMBER):
        return None
    return int(round(float(value)))


def header_index(rows, first_cell):
    for i, r in enumerate(rows):
        if r and r[0] and str(r[0]).strip().lower().startswith(first_cell.lower()):
            return i
    raise SystemExit(f"FAIL: no header row starting with {first_cell!r}")


def wide_table(rows, first_cell):
    """
    A label-by-year table -> list of (section, label, {year: value}).
    Stops at the footnotes. `section` is the last capitalised block label seen.
    """
    h = header_index(rows, first_cell)
    years = [int(y) for y in rows[h][1:] if y is not None and str(y).strip().isdigit()]
    out, section = [], None
    for r in rows[h + 1:]:
        label = r[0]
        if label is None:
            continue
        label = str(label).replace("\n", " ").strip()
        if label.startswith(("Notes", "Note:", "Source")) or re.match(r"^\d+ [A-Z]", label) \
                or label in ("NA Not available.", "X Not applicable."):
            break
        if label.isupper() and all(v is None for v in r[1:]):
            section = label
            continue
        values = {y: number(v) for y, v in zip(years, r[1:1 + len(years)])}
        out.append((section, clean_label(label), values))
    return years, out


def year_series(rows, columns=(1,)):
    """
    A Year/Number table, possibly laid out in several side-by-side pairs
    (Table 1 has four). Returns {year: value} for the first value column of
    each pair, or {year: (v1, v2, ...)} when several columns are requested.
    """
    h = header_index(rows, "Year")
    header = [str(c).strip().lower() if c else "" for c in rows[h]]
    year_cols = [i for i, c in enumerate(header) if c == "year"]
    out = {}
    for r in rows[h + 1:]:
        for yc in year_cols:
            m = YEAR_LABEL.match(str(r[yc]).strip()) if yc < len(r) and r[yc] is not None else None
            if not m:
                continue
            vals = tuple(number(r[yc + c]) if yc + c < len(r) else None for c in columns)
            out[int(m.group(1))] = vals[0] if len(columns) == 1 else vals
    if not out:
        raise SystemExit("FAIL: year table has no rows")
    return out
