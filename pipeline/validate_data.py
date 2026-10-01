"""
STEP 3 — refuse to publish something broken.

This runs before every commit. If it raises, the workflow stops and the live
site keeps yesterday's good data instead of getting today's bad data.

Add your own checks as you learn what "wrong" looks like for your dataset.
"""
import json
import sys
from datetime import date

import pandas as pd

import acs
from common import DATA, load_config

# The categories CBP has used since FY2020. A new one usually means CBP changed
# its file format; a person should look before it goes live.
KNOWN = {
    "agency": {"Border Patrol", "Field Operations"},
    "border": {"Southwest border", "Northern border", "Air, sea and other"},
    "demographic": {"Single adults", "Family units", "Unaccompanied children",
                    "Accompanied minors", "Not reported"},
    "encounter_type": {"Apprehensions", "Inadmissibles"},
}
COLUMNS = {
    "border_monthly.csv": ["month", "fiscal_year", "agency", "border", "demographic",
                           "nationality", "encounter_type", "encounters"],
    "border_sectors.csv": ["month", "fiscal_year", "agency", "border", "office",
                           "encounter_type", "encounters"],
    "border_annual.csv": ["fiscal_year", "series", "value", "partial"],
    "legal_annual.csv": ["year", "series", "value"],
    "legal_classes.csv": ["fiscal_year", "group", "class", "new_arrivals", "adjustments", "total"],
    "legal_countries.csv": ["fiscal_year", "country", "group", "class", "green_cards"],
    "legal_regions.csv": ["fiscal_year", "region", "group", "class", "green_cards"],
    "legal_nonimmigrants.csv": ["fiscal_year", "category", "visa", "code", "admissions"],
}
# DHS rounds every cell to the nearest 10, so a sum of N cells can differ from
# the printed total by up to 5*N. Allow that, or this share, whichever is more.
ROUNDING = 0.005


def months_between(first, last):
    return pd.period_range(first, last, freq="M").strftime("%Y-%m").tolist()


def close(a, b, tol=ROUNDING, cells=1):
    return abs(a - b) <= max(tol * abs(b), 5 * cells)


def load(problems):
    tables = {}
    for name, cols in COLUMNS.items():
        path = DATA / name
        if not path.exists():
            raise SystemExit(f"FAIL: data/{name} does not exist")
        df = pd.read_csv(path, keep_default_na=False)
        missing = [c for c in cols if c not in df.columns]
        if missing:
            problems.append(f"{name}: missing columns {missing}")
            continue
        if df.empty:
            problems.append(f"{name}: the dataset is empty")
            continue
        blank = df[cols].astype(str).eq("").any()
        if blank[[c for c in cols if c != "code"]].any():
            problems.append(f"{name}: some rows have blank values")
        value_col = cols[-1] if name != "border_annual.csv" else "value"
        if name == "legal_classes.csv":
            value_col = "total"
        if not pd.api.types.is_integer_dtype(df[value_col]) or (df[value_col] < 0).any():
            problems.append(f"{name}: {value_col} must be whole, non-negative numbers")
        tables[name] = df
    return tables


def check_border(t, cfg, meta, problems):
    df, sectors, annual = t["border_monthly.csv"], t["border_sectors.csv"], t["border_annual.csv"]
    for col, allowed in KNOWN.items():
        new = set(df[col].unique()) - allowed
        if new:
            problems.append(f"unfamiliar {col} values from CBP: {sorted(new)}")

    gaps = sorted(set(months_between(df["month"].min(), df["month"].max())) - set(df["month"]))
    if gaps:
        problems.append(f"months missing from the border series: {gaps}")

    # CBP posts mid-month for the month before. Much older than that and the
    # page scrape has probably latched onto the wrong file.
    latest = pd.Period(df["month"].max(), freq="M")
    age = (pd.Period(date.today(), freq="M") - latest).n
    if age > cfg["max_months_stale"]:
        problems.append(f"latest border month is {latest}, {age} months old — "
                        "CBP may have moved or renamed its files")

    # No month should collapse to near zero; that is a truncated file.
    monthly = df.groupby("month")["encounters"].sum()
    tiny = monthly[monthly < monthly.median() * 0.05]
    if not tiny.empty:
        problems.append(f"implausibly small monthly totals: {tiny.to_dict()}")

    # The monthly and sector tables are cuts of the same data.
    diff = monthly.sub(sectors.groupby("month")["encounters"].sum(), fill_value=0)
    if (diff != 0).any():
        problems.append(f"sector totals disagree with the monthly table in {list(diff[diff != 0].index)}")

    # Before the CSV era, only Border Patrol apprehensions exist, and they must
    # carry the "Not reported" placeholders; after it, nothing should.
    first_csv = pd.Period(meta["detail_from_month"], freq="M")
    early = df[df["month"].map(lambda m: pd.Period(m, freq="M") < first_csv)]
    if not early.empty and (early["agency"].ne("Border Patrol").any()
                            or early["nationality"].ne("Not reported").any()):
        problems.append("historical months contain agencies or nationalities they cannot have")
    late = df[df["month"].map(lambda m: pd.Period(m, freq="M") >= first_csv)]
    if late["nationality"].eq("Not reported").any():
        problems.append("CSV-era months contain 'Not reported' nationalities")
    if "Title 42 expulsions" in set(df["encounter_type"]):
        problems.append("Title 42 expulsions are present but should be excluded")

    # Annual series: continuous, and the CSV years must agree with the monthly table.
    for series, g in annual.groupby("series"):
        years = sorted(g["fiscal_year"])
        if years != list(range(years[0], years[-1] + 1)):
            problems.append(f"annual series {series!r} has gaps")
    bp_monthly = df[(df["agency"] == "Border Patrol") & (df["encounter_type"] == "Apprehensions")] \
        .groupby("fiscal_year")["encounters"].sum()
    bp_annual = annual[annual["series"] == "Border Patrol apprehensions"].set_index("fiscal_year")["value"]
    for fy, v in bp_annual.items():
        if fy in bp_monthly.index and fy >= cfg["first_fiscal_year"] and v != bp_monthly[fy]:
            problems.append(f"FY{fy} annual apprehensions {v:,} != monthly sum {bp_monthly[fy]:,}")
    if annual["partial"].sum() > 2:
        problems.append("more than one fiscal year is flagged partial")

    # Where CBP's old and new files cover the same fiscal year, they should
    # agree. Small revisions are normal; large gaps mean a format change.
    for fy, c in meta.get("overlap_check", {}).items():
        if c["archive"] and not close(c["latest"], c["archive"], 0.02):
            problems.append(f"FY{fy} totals differ between CBP files: "
                            f"archive {c['archive']:,} vs latest {c['latest']:,}")


def check_legal(t, cfg, meta, problems):
    annual, classes = t["legal_annual.csv"], t["legal_classes.csv"]
    countries, regions, nonimm = t["legal_countries.csv"], t["legal_regions.csv"], t["legal_nonimmigrants.csv"]
    printed = meta["printed"]

    # Every series continuous from its first year to the latest edition.
    latest = meta["latest_fiscal_year"]
    for series, g in annual.groupby("series"):
        years = sorted(g["year"])
        if years != list(range(years[0], years[-1] + 1)):
            problems.append(f"legal series {series!r} has gaps")
        if years[-1] != latest:
            problems.append(f"legal series {series!r} ends in {years[-1]}, not {latest}")
    if date.today().year - latest > cfg["max_years_stale"]:
        problems.append(f"latest Yearbook edition is FY{latest} — DHS may have moved its files")

    # Classes: leaves add up to the Yearbook's printed group and grand totals.
    for (fy, group), g in classes.groupby(["fiscal_year", "group"]):
        for section, col in (("TOTAL", "total"), ("ADJUSTMENTS OF STATUS", "adjustments"),
                             ("NEW ARRIVALS", "new_arrivals")):
            want = printed["classes"]["groups"].get(f"{section}|{group}|{fy}")
            if want is not None and not close(g[col].sum(), want, cells=len(g)):
                problems.append(f"FY{fy} {group} {col}: classes sum to {g[col].sum():,}, "
                                f"Yearbook prints {want:,}")
    for fy, g in classes.groupby("fiscal_year"):
        want = printed["classes"]["totals"][str(fy)]
        if not close(g["total"].sum(), want, cells=len(g)):
            problems.append(f"FY{fy}: classes sum to {g['total'].sum():,}, Yearbook total is {want:,}")
        if not close(g["new_arrivals"].sum() + g["adjustments"].sum(), g["total"].sum(), cells=2 * len(g)):
            problems.append(f"FY{fy}: new arrivals + adjustments != total")
        lpr = annual[(annual["series"].str.startswith("Green cards")) & (annual["year"] == fy)]["value"]
        if len(lpr) and lpr.iloc[0] != want:
            problems.append(f"FY{fy}: Table 1 and Table 6 totals disagree ({lpr.iloc[0]:,} vs {want:,})")

    # Countries: each class adds up to its sheet's printed total; the residual
    # line is never negative and, where Table 6 exists, matches its
    # refugee/asylee/other classes.
    residual_name = "Refugees, asylees and other"
    table6 = classes.set_index(["fiscal_year", "class"])["total"]
    for (fy, cls), g in countries[countries["group"] != residual_name].groupby(["fiscal_year", "class"]):
        want = printed["country_classes"].get(f"{cls}|{fy}")
        total = g["green_cards"].sum()
        if want is None:
            problems.append(f"no printed total for {cls} in {fy}")
        elif not any(close(total, v, cells=len(g)) for v in want.values() if v is not None):
            problems.append(f"FY{fy} {cls}: countries sum to {total:,}, sheet prints {want}")
        # The Yearbook's class table is an independent cut of the same data.
        if (fy, cls) in table6.index and not close(total, table6[(fy, cls)], cells=len(g)):
            problems.append(f"FY{fy} {cls}: countries sum to {total:,}, Yearbook Table 6 says {table6[(fy, cls)]:,}")
    residual = countries[countries["group"] == residual_name].set_index("fiscal_year")["green_cards"]
    if (residual < 0).any():
        problems.append(f"negative residual classes in {list(residual[residual < 0].index)}")
    for fy, g in classes.groupby("fiscal_year"):
        want = g[g["group"].isin(["Refugees and asylees", "Other classes"])]["total"].sum()
        if fy in residual.index and not close(residual[fy], want, 0.02):
            problems.append(f"FY{fy}: residual {residual[fy]:,} vs Table 6 refugees/asylees/other {want:,}")
    if set(regions["fiscal_year"]) != set(countries["fiscal_year"]):
        problems.append("region and country tables cover different years")
    if countries["country"].str.contains(r"\d").any():
        problems.append("country names still carry footnote digits")

    # Nonimmigrants: visa classes add up to their category, categories to the I-94 total.
    for (fy, cat), g in nonimm.groupby(["fiscal_year", "category"]):
        want = printed["nonimmigrants"].get(f"{cat}|{fy}")
        if want is not None and not close(g["admissions"].sum(), want, 0.01, cells=len(g)):
            problems.append(f"FY{fy} {cat}: visas sum to {g['admissions'].sum():,}, Yearbook prints {want:,}")
    for fy, g in nonimm.groupby("fiscal_year"):
        want = printed["nonimmigrants"].get(f"Total I-94 admissions|{fy}")
        if want and not close(g["admissions"].sum(), want, 0.01, cells=len(g)):
            problems.append(f"FY{fy}: visa classes sum to {g['admissions'].sum():,}, I-94 total is {want:,}")


def check_acs(cfg, problems):
    path = DATA / "acs_areas.csv"
    if not path.exists():
        problems.append("data/acs_areas.csv does not exist")
        return
    df = pd.read_csv(path, dtype={"code": str, "state": str})
    missing = [c for c in ["level", "code", "population", "foreign_born", "vintage"] + acs.MEASURE_KEYS
               if c not in df.columns]
    if missing:
        problems.append(f"acs_areas.csv: missing columns {missing}")
        return
    if (df["vintage"] != cfg["vintage"]).any():
        problems.append(f"acs_areas.csv holds a different vintage than config ({cfg['vintage']})")
    # Roughly 52 states, 900+ metro/micro areas, 2,400+ PUMAs; far fewer
    # means a truncated download.
    for level, least in (("state", 51), ("metro", 800), ("puma", 2300)):
        n = int((df["level"] == level).sum())
        if n < least:
            problems.append(f"acs_areas.csv: only {n} {level} rows (expected at least {least})")
    if (df["level"] == "us").sum() != 1:
        problems.append("acs_areas.csv: the national row is missing or duplicated")
    if df["code"].duplicated().any():
        problems.append("acs_areas.csv: duplicate area codes")
    pct = df[[k for k in acs.MEASURE_KEYS if k.startswith("pct_")]].stack()
    if ((pct < 0) | (pct > 100)).any():
        problems.append("acs_areas.csv: a percentage is outside 0-100")
    if (df["foreign_born"] > df["population"]).any():
        problems.append("acs_areas.csv: foreign-born exceeds population somewhere")
    if df.loc[df["level"] != "us", "pct_foreign_born"].isna().mean() > 0.02:
        problems.append("acs_areas.csv: too many areas have no immigrant share")
    us = df[df["level"] == "us"]["foreign_born"].sum()
    states = df[df["level"] == "state"]["foreign_born"].sum()
    if us and abs(states - us) / us > 0.005:
        problems.append(f"acs_areas.csv: states' foreign-born sum to {states:,.0f}, nation says {us:,.0f}")


MICRO = DATA / "microdata"
GROUP_MEASURES = ["pct_naturalized", "pct_recent", "pct_female", "pct_children", "pct_bachelors", "pct_less_hs",
                  "pct_limited_english", "pct_employed", "pct_in_labor_force", "pct_homeowner", "pct_insured",
                  "pct_medicaid", "median_age", "median_income", "median_fulltime_wage", "median_years_in_us"]


def check_microdata(problems):
    """The committed aggregates from IPUMS microdata (tools/extract_microdata.py)."""
    for name in ("acs_groups.csv", "acs_group_areas.csv", "cps_annual.csv"):
        if not (MICRO / name).exists():
            problems.append(f"data/microdata/{name} does not exist")
            return
    g = pd.read_csv(MICRO / "acs_groups.csv", dtype={"code": str})
    need = ["level", "code", "group", "region", "n", "population", "pct_of_immigrants"] + GROUP_MEASURES
    missing = [c for c in need if c not in g.columns]
    if missing:
        problems.append(f"acs_groups.csv: missing columns {missing}")
        return
    us = g[g["level"] == "us"]
    if us["group"].duplicated().any():
        problems.append("acs_groups.csv: duplicate national groups")
    for must in ("All immigrants", "U.S.-born"):
        if must not in set(us["group"]):
            problems.append(f"acs_groups.csv: no national row for {must!r}")
    if (us["group"].nunique() - 2) < 100:
        problems.append(f"acs_groups.csv: only {us['group'].nunique() - 2} country groups")
    pct = g[[c for c in GROUP_MEASURES if c.startswith("pct_")] + ["pct_of_immigrants"]].stack()
    if ((pct < 0) | (pct > 100)).any():
        problems.append("acs_groups.csv: a percentage is outside 0-100")
    if (g["n"] < 100).any():
        problems.append("acs_groups.csv: a row rests on fewer than 100 records")
    total = us.loc[us["group"] == "All immigrants", "population"].sum()
    countries = us[~us["group"].isin(["All immigrants", "U.S.-born"])]["population"].sum()
    if not 0.9 * total <= countries <= total * 1.001:
        problems.append(f"acs_groups.csv: country groups sum to {countries:,.0f} vs {total:,.0f} immigrants")

    a = pd.read_csv(MICRO / "acs_group_areas.csv", dtype={"code": str})
    if a[a["level"] == "puma"]["code"].nunique() < 2300 or a[a["level"] == "state"]["code"].nunique() < 51:
        problems.append("acs_group_areas.csv: too few areas")
    if (a["pct_of_residents"].dropna() > 100).any() or (a["pct_of_immigrants"].dropna() > 100.5).any():
        problems.append("acs_group_areas.csv: a share exceeds 100%")

    c = pd.read_csv(MICRO / "cps_annual.csv")
    years = sorted(c["year"])
    if years != list(range(years[0], years[-1] + 1)):
        problems.append("cps_annual.csv: years are not continuous")
    if years[-1] < 2024:
        problems.append(f"cps_annual.csv: ends in {years[-1]}")
    if ((c["foreign_born"] > c["population"]) | (c["naturalized"] > c["foreign_born"])).any():
        problems.append("cps_annual.csv: components exceed their totals")
    if not c["pct_foreign_born"].between(5, 25).all():
        problems.append("cps_annual.csv: implausible foreign-born share")


def validate():
    cfg = load_config()
    problems = []
    meta_path = DATA / "meta.json"
    if not meta_path.exists():
        raise SystemExit("FAIL: data/meta.json does not exist")
    meta = json.loads(meta_path.read_text())

    tables = load(problems)
    if len(tables) == len(COLUMNS):
        check_border(tables, cfg["border"], meta["border"], problems)
        check_legal(tables, cfg["ohss"], meta["legal"], problems)

        # Guard against a broken source silently gutting the site.
        for key, table in (("border", "border_monthly.csv"), ("legal", "legal_countries.csv")):
            previous = meta.get("previous_rows", {}).get(key)
            if previous and len(tables[table]) < previous * 0.5:
                problems.append(f"{table}: row count fell from {previous} to {len(tables[table])} — "
                                "that looks like a broken source, not real change")

    check_acs(cfg["acs"], problems)
    check_microdata(problems)

    if problems:
        print("VALIDATION FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        raise SystemExit(1)

    b, l = meta["border"], meta["legal"]
    print(f"validation passed: border {b['rows']} rows ({b['first_month']} to {b['latest_month']}), "
          f"legal {l['country_rows']} country rows (to FY{l['latest_fiscal_year']})")


if __name__ == "__main__":
    validate()
