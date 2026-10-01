"""
STEP 2 — turn raw data into exactly what the site needs.

Border (CBP encounters plus CBP's historical PDFs, extracted once into
data/history/):

  data/border_monthly.csv   month x agency x border x demographic x nationality
                            x type, FY2000 on (before FY2020: Border Patrol
                            apprehensions only, demographic and nationality
                            "Not reported")
  data/border_sectors.csv   month x sector / field office x type, FY2000 on
  data/border_annual.csv    fiscal year x series, FY1925 on

Legal immigration (DHS Office of Homeland Security Statistics):

  data/legal_annual.csv        year x series: green cards, naturalizations,
                               refugee arrivals, back to the first records
  data/legal_classes.csv       fiscal year x class of admission, FY2015 on
  data/legal_countries.csv     fiscal year x country of birth x class, FY2005 on
  data/legal_regions.csv       the same by world region
  data/legal_nonimmigrants.csv fiscal year x visa category, FY2015 on

  data/meta.json               row counts, update date, coverage, provenance

Encounter types listed in config "exclude_encounter_types" (Title 42
expulsions) are dropped everywhere.
"""
import csv
import json
import re
from datetime import datetime, timezone

import pandas as pd

import acs
import ohss
from common import DATA, load_config, write_json
from fetch import ACS_DIR, ACS_OUT, CBP_ARCHIVE, CBP_LATEST, LPR_BY_COUNTRY, SOURCES, yearbook_path

HISTORY = DATA / "history"

# ---------------------------------------------------------------- border ---

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# Readable names. Anything CBP adds that is not listed here passes through
# unchanged, and validate_data.py will stop the run so a person can look at it.
COMPONENT = {"U.S. Border Patrol": "Border Patrol",
             "Office of Field Operations": "Field Operations"}
BORDER = {"Southwest Land Border": "Southwest border",
          "Northern Land Border": "Northern border",
          "Other": "Air, sea and other"}
DEMOGRAPHIC = {"Single Adults": "Single adults", "FMUA": "Family units",
               "UAC": "Unaccompanied children", "UC / Single Minors": "Unaccompanied children",
               "Accompanied Minors": "Accompanied minors"}
ENCOUNTER_TYPE = {"Apprehensions": "Apprehensions", "Expulsions": "Title 42 expulsions",
                  "Inadmissibles": "Inadmissibles"}
CITIZENSHIP = {"CHINA, PEOPLES REPUBLIC OF": "China", "MYANMAR (BURMA)": "Myanmar",
               "OTHER": "All other countries"}
RENAME = {"Component": "agency", "Land Border Region": "border",
          "Area of Responsibility": "office", "Demographic": "demographic",
          "Citizenship": "nationality", "Encounter Type": "encounter_type",
          "Encounter Count": "encounters"}

# Which border each historical Border Patrol sector belongs to.
SECTOR_BORDER = {
    **{s: "Southwest border" for s in ("Big Bend", "Del Rio", "El Centro", "El Paso", "Laredo",
                                       "Rio Grande Valley", "San Diego", "Tucson", "Yuma")},
    **{s: "Northern border" for s in ("Blaine", "Buffalo", "Detroit", "Grand Forks", "Havre",
                                      "Houlton", "Spokane", "Swanton")},
    **{s: "Air, sea and other" for s in ("Livermore", "Miami", "New Orleans", "Ramey")},
}
NOT_REPORTED = "Not reported"
APPREHENSIONS = "Border Patrol apprehensions"
INADMISSIBLES = "Port-of-entry inadmissibles"


def fiscal_year(col):
    return col.astype(str).str[:4].astype(int)         # "2026 (FYTD)" -> 2026


def load_cbp():
    latest = pd.read_csv(CBP_LATEST)
    archive = pd.read_csv(CBP_ARCHIVE)
    latest["fy"] = fiscal_year(latest["Fiscal Year"])
    archive["fy"] = fiscal_year(archive["Fiscal Year"])

    # Where the files overlap, record both totals so validation can confirm
    # they agree, then keep the newer file's (possibly revised) figures.
    overlap = sorted(set(latest["fy"]) & set(archive["fy"]))
    reconcile = {str(fy): {"archive": int(archive.loc[archive["fy"] == fy, "Encounter Count"].sum()),
                           "latest": int(latest.loc[latest["fy"] == fy, "Encounter Count"].sum())}
                 for fy in overlap}
    archive = archive[archive["fy"] < latest["fy"].min()]
    return pd.concat([archive, latest], ignore_index=True), reconcile


def shape_cbp(df, cfg):
    df = df[df["fy"] >= cfg["first_fiscal_year"]].copy()
    df = df[~df["Encounter Type"].isin(cfg["exclude_encounter_types"])]

    m = df["Month (abbv)"].str.upper().map(lambda s: MONTHS.index(s) + 1)
    year = df["fy"] - (m >= 10).astype(int)            # Oct–Dec belong to the prior calendar year
    df["month"] = year.astype(str) + "-" + m.map("{:02d}".format)
    df["fiscal_year"] = df["fy"]

    df["Component"] = df["Component"].replace(COMPONENT)
    df["Land Border Region"] = df["Land Border Region"].replace(BORDER)
    df["Demographic"] = df["Demographic"].replace(DEMOGRAPHIC)
    df["Encounter Type"] = df["Encounter Type"].replace(ENCOUNTER_TYPE)
    df["Citizenship"] = df["Citizenship"].map(lambda s: CITIZENSHIP.get(s, s.title()))
    return df.rename(columns=RENAME)


def load_history():
    """CBP's pre-FY2020 Border Patrol figures, extracted once from its PDFs."""
    monthly = pd.read_csv(HISTORY / "usbp_apprehensions_monthly_sector.csv")
    annual = pd.read_csv(HISTORY / "usbp_apprehensions_annual.csv")
    unknown = set(monthly["sector"]) - set(SECTOR_BORDER)
    if unknown:
        raise SystemExit(f"FAIL: historical sectors not assigned to a border: {sorted(unknown)}")
    monthly["agency"] = "Border Patrol"
    monthly["border"] = monthly["sector"].map(SECTOR_BORDER)
    monthly["office"] = monthly["sector"] + " Sector"
    monthly["encounter_type"] = "Apprehensions"
    monthly = monthly.rename(columns={"apprehensions": "encounters"})
    return monthly, annual


def aggregate(df, dims):
    out = df.groupby(dims, as_index=False)["encounters"].sum()
    return out.sort_values(dims).reset_index(drop=True)


def border_tables(cfg):
    raw, reconcile = load_cbp()
    df = shape_cbp(raw, cfg)
    hist_monthly, hist_annual = load_history()
    history_last_fy = int(hist_monthly["fiscal_year"].max())
    if history_last_fy >= cfg["first_fiscal_year"]:
        raise SystemExit(f"FAIL: history runs to FY{history_last_fy}, overlapping the CSV data")

    main_dims = ["month", "fiscal_year", "agency", "border", "demographic",
                 "nationality", "encounter_type"]
    hist_main = hist_monthly.assign(demographic=NOT_REPORTED, nationality=NOT_REPORTED)
    monthly = pd.concat([aggregate(hist_main, main_dims), aggregate(df, main_dims)],
                        ignore_index=True)

    sector_dims = ["month", "fiscal_year", "agency", "border", "office", "encounter_type"]
    sectors = pd.concat([aggregate(hist_monthly, sector_dims), aggregate(df, sector_dims)],
                        ignore_index=True)

    # Annual series back to 1925. Port-of-entry figures before FY2020 come from
    # the Yearbook (Table 36, "CBP OFO Encounters"); FY2020 on, from the CSVs.
    bp = df[(df["agency"] == "Border Patrol") & (df["encounter_type"] == "Apprehensions")]
    ofo = df[(df["agency"] == "Field Operations") & (df["encounter_type"] == "Inadmissibles")]
    t36 = ohss.year_series(ohss.sheet_rows(yearbook_path("enforcement"),
                                           ohss.find_sheet(yearbook_path("enforcement"),
                                                           "CBP OFO Encounters")))
    annual = pd.concat([
        hist_annual.rename(columns={"apprehensions": "value"}).assign(series=APPREHENSIONS),
        bp.groupby("fiscal_year", as_index=False)["encounters"].sum()
          .rename(columns={"encounters": "value"}).assign(series=APPREHENSIONS),
        pd.DataFrame([(fy, v) for fy, v in t36.items() if fy < cfg["first_fiscal_year"] and v],
                     columns=["fiscal_year", "value"]).assign(series=INADMISSIBLES),
        ofo.groupby("fiscal_year", as_index=False)["encounters"].sum()
           .rename(columns={"encounters": "value"}).assign(series=INADMISSIBLES),
    ], ignore_index=True)[["fiscal_year", "series", "value"]]
    annual = annual.sort_values(["series", "fiscal_year"]).reset_index(drop=True)

    latest_month = df["month"].max()
    latest_fy = int(df["fiscal_year"].max())
    annual["partial"] = (annual["fiscal_year"] == latest_fy) & (not latest_month.endswith("-09"))

    monthly.to_csv(DATA / "border_monthly.csv", index=False)
    sectors.to_csv(DATA / "border_sectors.csv", index=False)
    annual.to_csv(DATA / "border_annual.csv", index=False)
    return {
        "rows": int(len(monthly)),
        "sector_rows": int(len(sectors)),
        "annual_rows": int(len(annual)),
        "first_month": monthly["month"].min(),
        "detail_from_month": df["month"].min(),
        "latest_month": latest_month,
        "first_fiscal_year": int(annual["fiscal_year"].min()),
        "latest_fiscal_year": latest_fy,
        "total_encounters": int(monthly["encounters"].sum()),
        "overlap_check": reconcile,
        "excluded_types": [ENCOUNTER_TYPE.get(t, t) for t in cfg["exclude_encounter_types"]],
    }


# ----------------------------------------------------------------- legal ---

GREEN_CARDS = "Green cards (lawful permanent residents)"
NATURALIZATIONS = "Naturalizations"
NATZ_APPLICATIONS = "Naturalization applications filed"
REFUGEES = "Refugee arrivals"

# Class-of-admission groups and readable class names, keyed by how the
# Yearbook (Table 6) labels each row. Matching is by prefix.
IMMEDIATE = "Immediate relatives of citizens"
FAMILY = "Family-sponsored preferences"
EMPLOYMENT = "Employment-based preferences"
DIVERSITY = "Diversity lottery"
HUMANITARIAN = "Refugees and asylees"
OTHER = "Other classes"
RESIDUAL = "Refugees, asylees and other"

GROUP_HEADERS = {"Immediate relatives of U.S. citizens": IMMEDIATE,
                 "Family-sponsored preferences": FAMILY,
                 "Employment-based preferences": EMPLOYMENT}
CLASSES = {                                     # label prefix -> (group or None, class)
    "Spouses": (IMMEDIATE, "Spouses of citizens"),
    "Children": (IMMEDIATE, "Children of citizens"),
    "Parents": (IMMEDIATE, "Parents of citizens"),
    "First: Unmarried": (FAMILY, "Unmarried adult children of citizens (F1)"),
    "Second: Spouses": (FAMILY, "Spouses and children of green-card holders (F2)"),
    "Third: Married": (FAMILY, "Married children of citizens (F3)"),
    "Fourth: Brothers": (FAMILY, "Siblings of citizens (F4)"),
    "First: Priority": (EMPLOYMENT, "Priority workers (EB-1)"),
    "Second: Professionals": (EMPLOYMENT, "Advanced-degree professionals (EB-2)"),
    "Third: Skilled": (EMPLOYMENT, "Skilled and other workers (EB-3)"),
    "Fourth: Certain": (EMPLOYMENT, "Special immigrants (EB-4)"),
    "Fifth: Employment": (EMPLOYMENT, "Investors (EB-5)"),
    "Diversity": (DIVERSITY, "Diversity lottery"),
    "Refugees": (HUMANITARIAN, "Refugees"),
    "Asylees": (HUMANITARIAN, "Asylees"),
    "Parolees": (OTHER, "Parolees"),
    "Children born abroad": (OTHER, "Children born abroad to residents"),
    "Certain Iraqis and Afghans": (OTHER, "Iraqi and Afghan U.S. government employees"),
    "Cancellation of removal": (OTHER, "Cancellation of removal"),
    "Victims of human trafficking": (OTHER, "Trafficking victims (T visa)"),
    "Victims of crimes": (OTHER, "Crime victims (U visa)"),
    "Other": (OTHER, "Other"),
}
# The LPR-by-country workbook has one sheet per class.
COUNTRY_SHEETS = {
    "Immediate Relatives-Spouses": "Spouses", "Immediate Relatives-Children": "Children",
    "Immediate Relatives-Parents": "Parents",
    "Family First Preference": "First: Unmarried", "Family Second Preference": "Second: Spouses",
    "Family Third Preference": "Third: Married", "Family Fourth Preference": "Fourth: Brothers",
    "Emp- First Preference": "First: Priority", "Emp- Second Preference": "Second: Professionals",
    "Emp- Third Preference": "Third: Skilled", "Emp- Fourth Preference": "Fourth: Certain",
    "Emp- Fifth Preference": "Fifth: Employment", "Diversity": "Diversity",
}
NOT_BY_COUNTRY = "Not broken out by country"

# Nonimmigrant admissions (Table 26): top-level categories, and readable names.
VISA_CATEGORIES = {
    "Temporary workers and families": "Temporary workers and families",
    "Treaty traders and investors": "Treaty traders and investors",
    "Students": "Students",
    "Exchange visitors": "Exchange visitors",
    "Diplomats and other representatives": "Diplomats and officials",
    "Temporary visitors for pleasure": "Tourists",
    "Temporary visitors for business": "Business visitors",
    "Transit individuals": "In transit",
    "Commuter students": "Commuter students",
    "Noncitizen fiance(e)s of U.S. citizens and children": "Fiancé(e)s of citizens",
    "Other": "Other",
    "Unknown": "Unknown",
}
VISA_CODE = re.compile(r"\(([A-Z][A-Z0-9]*(?:[,/ ]+(?:to )?[A-Z][A-Z0-9]*)*)\)\s*$")   # "(H1B)", "(N1 to N7)"
I94_TOTAL = "Total I-94 admissions"


def match_class(label):
    for prefix, (group, name) in CLASSES.items():
        if label.startswith(prefix):
            return group, name
    return None, None


def legal_annual():
    lpr = ohss.year_series(ohss.sheet_rows(yearbook_path("lawful_permanent_residents"), "Table 1"))
    natz_path = yearbook_path("naturalizations")
    natz = ohss.year_series(ohss.sheet_rows(natz_path, ohss.find_sheet(natz_path, "Persons Naturalized, and")),
                            columns=(1, 2))
    ref_path = yearbook_path("refugees")
    ref = ohss.year_series(ohss.sheet_rows(ref_path, ohss.find_sheet(ref_path, "Refugee Arrivals: Fiscal")))
    rows = [(y, GREEN_CARDS, v) for y, v in lpr.items() if v is not None]
    rows += [(y, NATZ_APPLICATIONS, a) for y, (a, n) in natz.items() if a is not None]
    rows += [(y, NATURALIZATIONS, n) for y, (a, n) in natz.items() if n is not None]
    rows += [(y, REFUGEES, v) for y, v in ref.items() if v is not None]
    df = pd.DataFrame(rows, columns=["year", "series", "value"]).sort_values(["series", "year"])
    return df.reset_index(drop=True), lpr


def legal_classes():
    """Table 6: green cards by class of admission, new arrivals vs adjustments."""
    path = yearbook_path("lawful_permanent_residents")
    years, rows = ohss.wide_table(ohss.sheet_rows(path, ohss.find_sheet(path, "Type and Major Class")),
                                  "Type and class of admission")
    out, checks = [], []
    section_totals = {"TOTAL": {}, "ADJUSTMENTS OF STATUS": {}, "NEW ARRIVALS": {}}
    for section, label, values in rows:
        if section not in section_totals:
            raise SystemExit(f"FAIL: unexpected section {section!r} in Table 6")
        if label == "Total":
            section_totals[section] = values
            continue
        if label in GROUP_HEADERS:
            checks.append((section, GROUP_HEADERS[label], values))
            continue
        group, name = match_class(label)
        if not group:
            raise SystemExit(f"FAIL: unfamiliar class of admission in Table 6: {label!r}")
        for y in years:
            out.append((y, section, group, name, values[y]))
    df = pd.DataFrame(out, columns=["fiscal_year", "section", "group", "class", "value"])
    df["section"] = df["section"].map({"TOTAL": "total", "ADJUSTMENTS OF STATUS": "adjustments",
                                       "NEW ARRIVALS": "new_arrivals"})
    wide = df.pivot_table(index=["fiscal_year", "group", "class"], columns="section",
                          values="value", aggfunc="sum").reset_index()
    wide = wide[["fiscal_year", "group", "class", "new_arrivals", "adjustments", "total"]]
    wide = wide.sort_values(["fiscal_year", "group", "class"]).reset_index(drop=True)

    # Group subtotals and section totals as the Yearbook prints them, for validation.
    printed = {"totals": {str(y): section_totals["TOTAL"][y] for y in years},
               "groups": {f"{s}|{g}|{y}": v[y] for s, g, v in checks for y in years}}
    return wide, printed


def legal_countries(lpr_totals):
    """The LPR-by-country workbook: one sheet per class, countries by year."""
    countries, regions = [], []
    class_totals = {}
    for sheet, prefix in COUNTRY_SHEETS.items():
        group, name = match_class(prefix)
        years, rows = ohss.wide_table(ohss.sheet_rows(LPR_BY_COUNTRY, sheet), "Region and country")
        for section, label, values in rows:
            if label == "Total":
                # Both blocks print a total; they occasionally disagree
                # (a DHS typo), so validation gets both.
                for y in years:
                    class_totals.setdefault((name, y), {})[section.lower()] = values[y]
                continue
            target = countries if section == "COUNTRY" else regions
            for y in years:
                if values[y] is not None:
                    target.append((y, label, group, name, values[y]))
    cols = ["fiscal_year", "country", "group", "class", "green_cards"]
    countries = pd.DataFrame(countries, columns=cols)
    regions = pd.DataFrame(regions, columns=["fiscal_year", "region", "group", "class", "green_cards"])

    # Refugees, asylees and the small classes are not broken out by country.
    # Their combined size is the gap between the Yearbook's total and the
    # classes above, shown as one line so the yearly totals still add up.
    by_year = countries.groupby("fiscal_year")["green_cards"].sum()
    residual = []
    for y, n in by_year.items():
        total = lpr_totals.get(y)
        if total is None:
            raise SystemExit(f"FAIL: Yearbook Table 1 has no total for {y}")
        residual.append((y, NOT_BY_COUNTRY, RESIDUAL, RESIDUAL, int(total - n)))
    countries = pd.concat([countries, pd.DataFrame(residual, columns=cols)], ignore_index=True)
    regions = pd.concat([regions, pd.DataFrame(residual, columns=regions.columns)], ignore_index=True)
    countries = countries.sort_values(["fiscal_year", "group", "class", "country"]).reset_index(drop=True)
    regions = regions.sort_values(["fiscal_year", "group", "class", "region"]).reset_index(drop=True)
    printed = {f"{name}|{y}": v for (name, y), v in class_totals.items()}
    return countries, regions, printed


def legal_nonimmigrants():
    """Table 26: I-94 admissions by visa class, with their top-level category."""
    path = yearbook_path("nonimmigrants")
    years, rows = ohss.wide_table(ohss.sheet_rows(path, ohss.find_sheet(path, "Nonimmigrant Admissions by Class")),
                                  "Class of admission")
    out, printed, category = [], {}, None
    for _, label, values in rows:
        if label == I94_TOTAL:
            printed.update({f"{I94_TOTAL}|{y}": values[y] for y in years})
            continue
        if label in VISA_CATEGORIES:
            category = VISA_CATEGORIES[label]
            printed.update({f"{category}|{y}": values[y] for y in years})
            if label == "Unknown":
                out += [(y, category, "Unknown", "", values[y]) for y in years]
            continue
        m = VISA_CODE.search(label)
        if not m or category is None:
            continue                                   # a subtotal row
        visa = label[:m.start()].strip()
        out += [(y, category, visa, m.group(1), values[y]) for y in years if values[y] is not None]
    df = pd.DataFrame(out, columns=["fiscal_year", "category", "visa", "code", "admissions"])
    return df.sort_values(["fiscal_year", "category", "visa"]).reset_index(drop=True), printed


def legal_tables():
    annual, lpr_totals = legal_annual()
    classes, printed_classes = legal_classes()
    countries, regions, printed_country = legal_countries(lpr_totals)
    nonimm, printed_nonimm = legal_nonimmigrants()

    annual.to_csv(DATA / "legal_annual.csv", index=False)
    classes.to_csv(DATA / "legal_classes.csv", index=False)
    countries.to_csv(DATA / "legal_countries.csv", index=False)
    regions.to_csv(DATA / "legal_regions.csv", index=False)
    nonimm.to_csv(DATA / "legal_nonimmigrants.csv", index=False)

    latest = int(classes["fiscal_year"].max())
    return {
        "annual_rows": int(len(annual)),
        "class_rows": int(len(classes)),
        "country_rows": int(len(countries)),
        "nonimmigrant_rows": int(len(nonimm)),
        "first_year": int(annual["year"].min()),
        "latest_fiscal_year": latest,
        "countries_from": int(countries["fiscal_year"].min()),
        "classes_from": int(classes["fiscal_year"].min()),
        "green_cards_latest": int(lpr_totals[latest]),
        "printed": {"classes": printed_classes, "country_classes": printed_country,
                    "nonimmigrants": printed_nonimm},
    }


# ------------------------------------------------------------------- acs ---

def check_shells():
    """Stop if the Census has re-numbered any row the measures depend on."""
    labels = {}
    with open(ACS_DIR / "shells.txt", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="|"):
            if r["Table ID"] in acs.ROWS:
                labels[(r["Table ID"], int(float(r["Line"])))] = r["Label"].strip()
    wrong = [f"{t} line {n}: expected {want!r}, shells say {labels.get((t, n))!r}"
             for t, rows in acs.ROWS.items() for n, want in rows.items()
             if labels.get((t, n)) != want]
    if wrong:
        raise SystemExit("FAIL: ACS table layout changed:\n  " + "\n  ".join(wrong))


def read_acs_table(table):
    """{geo_id: {line: estimate}} for the lines in acs.ROWS[table]."""
    lines = acs.ROWS[table]
    out = {}
    with open(ACS_DIR / f"{table}.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="|"):
            out[r["GEO_ID"]] = {n: acs.estimate(r.get(f"{table}_E{n:03d}")) for n in lines}
    return out


def acs_summary(df):
    us = df[df["level"] == "us"].iloc[0]
    return {
        "vintage": int(df["vintage"].iloc[0]),
        "counts": {lvl: int((df["level"] == lvl).sum()) for lvl in ("state", "metro", "puma")},
        "us": {k: (None if pd.isna(us[k]) else float(us[k])) for k in ["population"] + acs.MEASURE_KEYS},
    }


def acs_table(cfg):
    """
    data/acs_areas.csv: one row per state, metro area and PUMA (plus the
    nation) with the map's measures. Rebuilt only when fetch.py downloaded a
    new vintage; otherwise the committed file stands.
    """
    have_raw = all((ACS_DIR / f"{t}.csv").exists() for t in acs.TABLES) and (ACS_DIR / "shells.txt").exists()
    if not have_raw:
        if ACS_OUT.exists():
            print("acs: keeping the existing data/acs_areas.csv")
            return acs_summary(pd.read_csv(ACS_OUT, dtype={"code": str, "state": str}))
        raise SystemExit("FAIL: no ACS download and no data/acs_areas.csv")

    check_shells()
    tables = {t: read_acs_table(t) for t in acs.TABLES}
    rows = []
    for geo_id in tables["B05002"]:
        level = acs.level_of(geo_id)
        if level is None or any(geo_id not in tables[t] for t in acs.TABLES):
            continue
        code = geo_id.split("US", 1)[1]
        m = acs.compute({t: tables[t][geo_id] for t in acs.TABLES})
        rows.append({"level": level, "code": code,
                     "state": code[:2] if level in ("state", "puma") else "",
                     **m, "vintage": cfg["vintage"]})
    df = pd.DataFrame(rows)[acs.COLUMNS]
    df = df.sort_values(["level", "code"]).reset_index(drop=True)
    df.to_csv(ACS_OUT, index=False)
    print(f"wrote {len(df)} areas to data/acs_areas.csv (ACS {cfg['vintage']} 5-year)")
    return acs_summary(df)


def transform():
    cfg = load_config()
    border = border_tables(cfg["border"])
    legal = legal_tables()
    acs_info = acs_table(cfg["acs"])

    # Carry the last published row counts forward so validation can compare
    # against them (this run is about to overwrite meta.json).
    meta_path = DATA / "meta.json"
    previous = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    now = datetime.now(timezone.utc)
    write_json(meta_path, {
        "updated": now.strftime("%B %d, %Y").replace(" 0", " "),
        "updated_iso": now.isoformat(timespec="seconds"),
        "previous_rows": {"border": previous.get("border", {}).get("rows"),
                          "legal": previous.get("legal", {}).get("country_rows")},
        "border": border,
        "legal": legal,
        "acs": acs_info,
        "sources": json.loads(SOURCES.read_text()),
    })
    print(f"border: {border['rows']} monthly rows ({border['first_month']} to {border['latest_month']}), "
          f"annual from FY{border['first_fiscal_year']}")
    print(f"legal: {legal['country_rows']} country rows, {legal['class_rows']} class rows, "
          f"annual from {legal['first_year']} to FY{legal['latest_fiscal_year']}")


if __name__ == "__main__":
    transform()
