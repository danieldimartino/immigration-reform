"""
One-time aggregation of IPUMS microdata into the small public tables the site
uses. The microdata (Stata files in OneDrive) never enters the repository;
only these aggregates do, as IPUMS's terms allow.

    python tools/extract_microdata.py

Reads, from the synced OneDrive folder:
  Data/Census/ACS/2024 5-year ACS.dta     IPUMS USA, ACS 2020-2024 5-year
  Data/Census/CPS/CPS 1994-2025.dta       IPUMS CPS, March ASEC 1994-2025

Writes:
  data/microdata/acs_groups.csv        characteristics of immigrants by
                                       birthplace, nationally and by state
  data/microdata/acs_group_areas.csv   population of the larger groups by
                                       state, metro area and PUMA
  data/microdata/cps_annual.csv        the immigrant population 1994-2025
  data/microdata/README.md             provenance and the citation IPUMS asks for
"""
import glob
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "microdata"
ONEDRIVE = glob.glob(str(Path.home() / "OneDrive*" / "Data" / "Census"))
ACS_FILE = "ACS/2024 5-year ACS.dta"
CPS_FILE = "CPS/CPS 1994-2025.dta"
ACS_VINTAGE = 2024
CHUNK = 400_000

# Groups need this many residents nationally to get a profile, this many
# in a state to get a state profile, and this many unweighted records to be
# reported at all.
MIN_GROUP_POP = 25_000
MIN_STATE_POP = 5_000
MIN_RECORDS = 100
AREA_GROUPS = 25            # the largest groups get PUMA and metro tables
MIN_AREA_POP = 200          # below this an area's count is left blank

# IPUMS general birthplace codes -> region of birth.
REGIONS = [
    (200, 200, "Mexico"), (210, 219, "Central America"), (250, 269, "Caribbean"),
    (300, 399, "South America"), (150, 199, "Canada and other Northern America"),
    (400, 499, "Europe"), (500, 599, "Asia"), (600, 699, "Africa"), (700, 799, "Oceania"),
]
NAME_FIXES = {
    "United Kingdom, Ns": "United Kingdom (not specified)", "Other Ussr/Russia": "Russia and other former USSR",
    "Guyana/British Guiana": "Guyana", "Egypt/United Arab Rep": "Egypt", "Korea": "South Korea",
    "China": "China", "Hong Kong": "Hong Kong", "Burma (Myanmar)": "Myanmar",
    "Iran": "Iran", "Yugoslavia": "Former Yugoslavia", "Czechoslovakia": "Former Czechoslovakia",
}
ALL_IMMIGRANTS, US_BORN = "All immigrants", "U.S.-born"


def find(name):
    for base in ONEDRIVE:
        p = Path(base) / name
        if p.exists():
            return p
    raise SystemExit(f"FAIL: {name} not found under {ONEDRIVE or 'OneDrive (not synced?)'}")


def title(s):
    t = " ".join(w if w in ("and", "of", "the") else w.capitalize() for w in str(s).split(" "))
    return NAME_FIXES.get(t, t)


def region_of(bpl):
    for lo, hi, name in REGIONS:
        if lo <= bpl <= hi:
            return name
    return "Other or not specified"


def wmedian(values, weights):
    if len(values) == 0:
        return None
    order = np.argsort(values)
    v, w = np.asarray(values)[order], np.asarray(weights)[order]
    cum = np.cumsum(w)
    return float(v[np.searchsorted(cum, cum[-1] / 2)])


# ------------------------------------------------------------------ ACS ---

ACS_COLS = ["perwt", "statefip", "puma", "met2023", "gq", "ownershp", "sex", "age", "bpl", "bpld",
            "citizen", "yrimmig", "speakeng", "hcovany", "hinscaid", "educd", "empstat", "labforce",
            "wkswork1", "uhrswork", "inctot", "incwage"]


def acs_prepare(ch):
    """Derived per-person flags; everything downstream is a weighted mean or median."""
    d = pd.DataFrame(index=ch.index)
    d["w"] = ch["perwt"].astype(float)
    d["state"] = ch["statefip"].map("{:02d}".format)
    d["puma"] = d["state"] + ch["puma"].map("{:05d}".format)
    d["metro"] = ch["met2023"].map(lambda m: f"{m:05d}" if m else "")
    d["bpl"] = ch["bpl"]
    d["bpld"] = ch["bpld"]
    d["foreign"] = (ch["bpl"] >= 150) & (ch["citizen"] != 1)      # excludes born abroad to U.S. parents
    d["native"] = ~d["foreign"]
    d["naturalized"] = ch["citizen"] == 2
    d["recent"] = ch["yrimmig"] >= 2010
    d["age"] = ch["age"]
    d["female"] = ch["sex"] == 2
    d["child"] = ch["age"] < 18
    d["adult25"] = ch["age"] >= 25
    d["bachelors"] = d["adult25"] & (ch["educd"] >= 101)
    d["less_hs"] = d["adult25"] & (ch["educd"] < 62)               # below high-school diploma or GED
    d["age5"] = ch["age"] >= 5
    d["limited_english"] = d["age5"] & ch["speakeng"].isin([1, 5, 6])   # less than "very well"
    d["working_age"] = ch["age"].between(16, 64)
    d["employed"] = d["working_age"] & (ch["empstat"] == 1)
    d["in_lf"] = d["working_age"] & (ch["labforce"] == 2)
    d["fulltime"] = (ch["wkswork1"] >= 50) & (ch["uhrswork"] >= 35) & (ch["incwage"] > 0) & (ch["incwage"] < 999998)
    d["wage"] = ch["incwage"].where(d["fulltime"])
    d["has_income"] = (ch["age"] >= 16) & (ch["inctot"] != 9999999) & (ch["inctot"] > 0)
    d["income"] = ch["inctot"].where(d["has_income"])
    d["household"] = ch["gq"].isin([1, 2])
    d["owner"] = d["household"] & (ch["ownershp"] == 1)
    d["insured"] = ch["hcovany"] == 2
    d["medicaid"] = ch["hinscaid"] == 2
    d["years_in_us"] = (ACS_VINTAGE - ch["yrimmig"]).where(ch["yrimmig"] > 0)
    return d


# Each measure: (column, numerator flag, denominator flag or None for the whole group).
RATES = [
    ("pct_naturalized", "naturalized", None), ("pct_recent", "recent", None),
    ("pct_female", "female", None), ("pct_children", "child", None),
    ("pct_bachelors", "bachelors", "adult25"), ("pct_less_hs", "less_hs", "adult25"),
    ("pct_limited_english", "limited_english", "age5"),
    ("pct_employed", "employed", "working_age"), ("pct_in_labor_force", "in_lf", "working_age"),
    ("pct_homeowner", "owner", "household"), ("pct_insured", "insured", None), ("pct_medicaid", "medicaid", None),
]
MEDIANS = [("median_age", "age", None), ("median_income", "income", "has_income"),
           ("median_fulltime_wage", "wage", "fulltime"), ("median_years_in_us", "years_in_us", None)]


class Accumulator:
    """Weighted sums per (geo, group) plus samples for the medians."""

    def __init__(self):
        self.sums = {}
        self.samples = {}

    def add(self, key, d):
        s = self.sums.setdefault(key, {"n": 0, "w": 0.0})
        s["n"] += len(d)
        s["w"] += d["w"].sum()
        for name, num, den in RATES:
            s[num] = s.get(num, 0.0) + (d["w"] * d[num]).sum()
        for den in {den for _, _, den in RATES if den}:        # each denominator once
            s[den] = s.get(den, 0.0) + (d["w"] * d[den]).sum()
        for name, col, den in MEDIANS:
            vals = d[[col, "w"]].dropna()
            if den:
                vals = vals[d.loc[vals.index, den]]
            if len(vals):
                keep = self.samples.setdefault((key, col), [])
                keep.append(vals.to_numpy())

    def rows(self):
        for key, s in self.sums.items():
            row = {"n": s["n"], "population": round(s["w"])}
            for name, num, den in RATES:
                base = s[den] if den else s["w"]
                row[name] = round(s[num] / base * 100, 1) if base else None
            for name, col, den in MEDIANS:
                parts = self.samples.get((key, col))
                if parts:
                    arr = np.concatenate(parts)
                    row[name] = round(wmedian(arr[:, 0], arr[:, 1]), 1 if col == "age" else 0)
                else:
                    row[name] = None
            yield key, row


def run_acs(path):
    print(f"reading {path.name} …")
    t0 = time.time()
    it = pd.read_stata(path, columns=ACS_COLS, chunksize=CHUNK, convert_categoricals=False, iterator=True)
    labels = {int(k): title(v) for k, v in it.value_labels()["BPLD"].items()}

    nat, state = Accumulator(), Accumulator()
    areas = {}                                     # (level, code, bpld) -> weight
    fb_by_group = {}
    for i, ch in enumerate(it):
        d = acs_prepare(ch)
        fb = d[d["foreign"]]
        nb = d[d["native"]]
        nat.add(("us", "", ALL_IMMIGRANTS), fb)
        nat.add(("us", "", US_BORN), nb)
        for st, g in fb.groupby("state"):
            state.add(("state", st, ALL_IMMIGRANTS), g)
        for st, g in nb.groupby("state"):
            state.add(("state", st, US_BORN), g)
        for code, g in fb.groupby("bpld"):
            nat.add(("us", "", int(code)), g)
            fb_by_group[int(code)] = fb_by_group.get(int(code), 0) + g["w"].sum()
            for st, gs in g.groupby("state"):
                state.add(("state", st, int(code)), gs)
            for level in ("state", "metro", "puma"):
                for area, ga in g.groupby(level):
                    if area:
                        areas[(level, area, int(code))] = areas.get((level, area, int(code)), 0) + ga["w"].sum()
        for level in ("state", "metro", "puma"):
            for area, ga in fb.groupby(level):
                if area:
                    areas[(level, area, ALL_IMMIGRANTS)] = areas.get((level, area, ALL_IMMIGRANTS), 0) + ga["w"].sum()
            for area, ga in d.groupby(level):
                if area:
                    areas[(level, area, "population")] = areas.get((level, area, "population"), 0) + ga["w"].sum()
        if i % 5 == 0:
            print(f"  {(i + 1) * CHUNK:,} records, {time.time() - t0:.0f}s")

    big = {c for c, w in fb_by_group.items() if w >= MIN_GROUP_POP}
    top = [c for c, _ in sorted(fb_by_group.items(), key=lambda x: -x[1])[:AREA_GROUPS]]
    total_fb = nat.sums[("us", "", ALL_IMMIGRANTS)]["w"]

    def group_name(code):
        return code if isinstance(code, str) else labels.get(code, str(code))

    rows = []
    for acc in (nat, state):
        for (level, code, group), row in acc.rows():
            if isinstance(group, int) and group not in big:
                continue
            if row["n"] < MIN_RECORDS or (level == "state" and isinstance(group, int) and row["population"] < MIN_STATE_POP):
                continue
            base = (nat if level == "us" else state).sums.get((level, code, ALL_IMMIGRANTS), {}).get("w", 0)
            rows.append({"level": level, "code": code, "group": group_name(group),
                         "region": region_of(int(str(group)[:3])) if isinstance(group, int) else "",
                         "pct_of_immigrants": round(row["population"] / base * 100, 2) if base and group != US_BORN else None,
                         **row})
    groups = pd.DataFrame(rows)
    groups = groups[["level", "code", "group", "region", "n", "population", "pct_of_immigrants"]
                    + [m[0] for m in RATES] + [m[0] for m in MEDIANS]]
    groups = groups.sort_values(["level", "code", "population"], ascending=[True, True, False])

    # Region rows, nationally and by state, from the group sums.
    area_rows = []
    for (level, area, group), w in areas.items():
        if group == "population" or group == ALL_IMMIGRANTS or (group in big and (level == "state" or group in top)):
            pop = areas.get((level, area, "population"), 0)
            fbw = areas.get((level, area, ALL_IMMIGRANTS), 0)
            if group not in ("population", ALL_IMMIGRANTS) and w < MIN_AREA_POP:
                continue
            area_rows.append({"level": level, "code": area, "group": group_name(group) if group != "population" else "All residents",
                              "population": round(w),
                              "pct_of_residents": round(w / pop * 100, 2) if pop else None,
                              "pct_of_immigrants": round(w / fbw * 100, 2) if fbw and group not in ("population", ALL_IMMIGRANTS) else None})
    group_areas = pd.DataFrame(area_rows).sort_values(["level", "code", "population"], ascending=[True, True, False])

    print(f"  ACS done in {time.time() - t0:.0f}s: {len(big)} groups, total immigrants {total_fb:,.0f}")
    return groups, group_areas, sorted(labels[c] for c in big), [labels[c] for c in top]


# ------------------------------------------------------------------ CPS ---

CPS_COLS = ["year", "month", "asecflag", "asecwt", "bpl", "citizen", "yrimmig", "age"]
CPS_REGIONS = [(20000, 20000, "Mexico"), (21000, 21999, "Central America"), (25000, 26999, "Caribbean"),
               (30000, 39999, "South America"), (15000, 19999, "Canada and other Northern America"),
               (40000, 49999, "Europe"), (50000, 59999, "Asia"), (60000, 69999, "Africa"), (70000, 79999, "Oceania")]


def cps_region(bpl):
    for lo, hi, name in CPS_REGIONS:
        if lo <= bpl <= hi:
            return name
    return "Other or not specified"


def run_cps(path):
    print(f"reading {path.name} …")
    it = pd.read_stata(path, columns=CPS_COLS, chunksize=1_000_000, convert_categoricals=False, iterator=True)
    parts = []
    for ch in it:
        ch = ch[ch["asecflag"] == 1]
        fb = ch["citizen"].isin([4, 5])
        g = pd.DataFrame({"year": ch["year"], "w": ch["asecwt"], "fb": fb,
                          "nat": fb & (ch["citizen"] == 4), "recent": fb & (ch["yrimmig"] >= ch["year"] - 5),
                          "region": np.where(fb, ch["bpl"].map(cps_region), "")})
        tot = g.groupby("year")["w"].sum().rename("population")
        s = g[g["fb"]].groupby("year").apply(lambda x: pd.Series({
            "foreign_born": x["w"].sum(), "naturalized": (x["w"] * x["nat"]).sum(),
            "recent_arrivals": (x["w"] * x["recent"]).sum(), "n": len(x)}), include_groups=False)
        reg = g[g["fb"]].groupby(["year", "region"])["w"].sum().unstack(fill_value=0)
        parts.append(pd.concat([tot, s, reg], axis=1))
    df = pd.concat(parts).groupby(level=0).sum()
    out = pd.DataFrame({"year": df.index, "population": df["population"].round(),
                        "foreign_born": df["foreign_born"].round(), "naturalized": df["naturalized"].round(),
                        "recent_arrivals": df["recent_arrivals"].round(), "records": df["n"].astype(int)})
    for name in [r[2] for r in CPS_REGIONS] + ["Other or not specified"]:
        if name in df:
            out["born_" + name.lower().replace(" ", "_").replace(",", "")] = df[name].round()
    out["pct_foreign_born"] = (out["foreign_born"] / out["population"] * 100).round(2)
    print(f"  CPS done: {out['year'].min()}-{out['year'].max()}")
    return out.reset_index(drop=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    groups, group_areas, group_names, top = run_acs(find(ACS_FILE))
    cps = run_cps(find(CPS_FILE))
    groups.to_csv(OUT / "acs_groups.csv", index=False)
    group_areas.to_csv(OUT / "acs_group_areas.csv", index=False)
    cps.to_csv(OUT / "cps_annual.csv", index=False)
    (OUT / "README.md").write_text(f"""# Aggregates from IPUMS microdata

Produced by `tools/extract_microdata.py` on {date.today().isoformat()}. The microdata
stays in OneDrive and is never committed; only these aggregates are, as the IPUMS
terms of use allow for published statistics.

- `acs_groups.csv`: characteristics of immigrants by country of birth (groups with at
  least {MIN_GROUP_POP:,} residents nationally; state rows need {MIN_STATE_POP:,} residents and
  {MIN_RECORDS} records), with "All immigrants" and "U.S.-born" for comparison. Source:
  IPUMS USA, American Community Survey 2020–2024 five-year sample, person weights.
- `acs_group_areas.csv`: population of every profiled group by state, and of the
  {AREA_GROUPS} largest groups by metro area and PUMA (counts under {MIN_AREA_POP} omitted).
- `cps_annual.csv`: the foreign-born population by year, citizenship, recency of
  arrival and region of birth. Source: IPUMS CPS, March supplement (ASEC) 1994–2025.

Immigrants are the foreign-born excluding people born abroad to U.S.-citizen parents.
Medians are weighted. Full-time wage covers wage earners working 50+ weeks and 35+ hours.

Citations:
Steven Ruggles, Sarah Flood, Matthew Sobek, et al. IPUMS USA: Version 15.0 [dataset].
Minneapolis, MN: IPUMS, 2024. https://doi.org/10.18128/D010.V15.0
Sarah Flood, Miriam King, Renae Rodgers, et al. IPUMS CPS: Version 12.0 [dataset].
Minneapolis, MN: IPUMS, 2024. https://doi.org/10.18128/D030.V12.0

Groups profiled ({len(group_names)}): {", ".join(group_names)}
""", encoding="utf-8")
    print(f"wrote {len(groups)} group rows, {len(group_areas)} area rows, {len(cps)} CPS years")
    return 0


if __name__ == "__main__":
    sys.exit(main())
