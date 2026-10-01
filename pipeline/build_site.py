"""
STEP 4 — render the site from the data.

Two pages, each from its own template, plus the CSVs for download:

  templates/index.html   -> site/index.html    legal immigration
  templates/border.html  -> site/border.html   border encounters
  data/*.csv             -> site/data/*.csv

The site folder is generated output: edit the templates, not the result.

Each page's explorer runs in the browser, so its data is embedded in it. To
keep pages small, each text column is stored once as a list of distinct
values and every row refers to them by position.
"""
import json
import shutil

import pandas as pd
from jinja2 import Environment, FileSystemLoader

import acs
from common import DATA, SITE, TEMPLATES, load_config

BORDER_DIMS = ["agency", "border", "demographic", "nationality", "encounter_type"]
SECTOR_DIMS = ["agency", "border", "office", "encounter_type"]
COUNTRY_DIMS = ["country", "group", "class"]
REGION_DIMS = ["region", "group", "class"]
DOWNLOADS = ["border_monthly.csv", "border_sectors.csv", "border_annual.csv",
             "legal_annual.csv", "legal_classes.csv", "legal_countries.csv",
             "legal_regions.csv", "legal_nonimmigrants.csv", "acs_areas.csv"]
MICRO = DATA / "microdata"
GROUP_COLS = ["n", "population", "pct_of_immigrants", "pct_naturalized", "pct_recent", "pct_female", "pct_children",
              "pct_bachelors", "pct_less_hs", "pct_limited_english", "pct_employed", "pct_in_labor_force",
              "pct_homeowner", "pct_insured", "pct_medicaid", "median_age", "median_income",
              "median_fulltime_wage", "median_years_in_us"]
GROUP_MEASURES = [
    ("pct_naturalized", "Naturalized U.S. citizens", "%", "of the group"),
    ("pct_recent", "Arrived 2010 or later", "%", "of the group"),
    ("median_years_in_us", "Median years in the U.S.", "yrs", ""),
    ("median_age", "Median age", "yrs", ""),
    ("pct_female", "Women", "%", "of the group"),
    ("pct_children", "Children under 18", "%", "of the group"),
    ("pct_bachelors", "Bachelor's degree or higher", "%", "age 25+"),
    ("pct_less_hs", "No high-school diploma", "%", "age 25+"),
    ("pct_limited_english", "Speak English less than \"very well\"", "%", "age 5+"),
    ("pct_employed", "Employed", "%", "age 16–64"),
    ("pct_in_labor_force", "In the labor force", "%", "age 16–64"),
    ("median_income", "Median personal income", "$", "age 16+ with income"),
    ("median_fulltime_wage", "Median full-time wage", "$", "full-time, year-round"),
    ("pct_homeowner", "Live in an owned home", "%", "in households"),
    ("pct_insured", "Have health insurance", "%", "of the group"),
    ("pct_medicaid", "Covered by Medicaid", "%", "of the group"),
]


def pack(df, dims, periods, period_col, value_col):
    """Dictionary-encode a table: {"dims": {col: [values]}, "rows": [[period, codes..., n]]}."""
    lookup = {c: sorted(df[c].unique()) for c in dims}
    index = {c: {v: i for i, v in enumerate(vals)} for c, vals in lookup.items()}
    period_ix = {p: i for i, p in enumerate(periods)}
    rows = [[period_ix[r[period_col]], *[index[c][r[c]] for c in dims], int(r[value_col])]
            for r in df.to_dict("records")]
    return {"dims": lookup, "rows": rows}


def month_label(m):
    return pd.Period(m, freq="M").strftime("%B %Y")


def pct(new, old):
    return None if not old else round((new - old) / old * 100, 1)


def border_payload(cfg, meta):
    df = pd.read_csv(DATA / "border_monthly.csv")
    sectors = pd.read_csv(DATA / "border_sectors.csv")
    annual = pd.read_csv(DATA / "border_annual.csv")
    months = sorted(df["month"].unique())

    # Headline figures, from the CSV era where every month is complete.
    monthly = df.groupby("month")["encounters"].sum()
    latest = monthly.index.max()
    year_ago = str(pd.Period(latest, freq="M") - 12)
    fy = int(df["fiscal_year"].max())
    fy_months = df.loc[df["fiscal_year"] == fy, "month"].unique()
    prior_months = [str(pd.Period(m, freq="M") - 12) for m in fy_months]
    fytd, prior = int(monthly[fy_months].sum()), int(monthly.reindex(prior_months).sum())
    stats = {
        "latest_month": month_label(latest), "latest": int(monthly[latest]),
        "latest_change": pct(monthly[latest], monthly.get(year_ago)),
        "fy": fy, "fytd": fytd, "fytd_change": pct(fytd, prior),
        "peak_month": month_label(monthly.idxmax()), "peak": int(monthly.max()),
        "total": int(monthly.sum()),
    }
    payload = {
        "months": months,
        "main": pack(df, BORDER_DIMS, months, "month", "encounters"),
        "sectors": pack(sectors, SECTOR_DIMS, months, "month", "encounters"),
        "annual": [[int(r.fiscal_year), r.series, int(r.value), bool(r.partial)]
                   for r in annual.itertuples()],
        "detailFrom": meta["detail_from_month"],
        "events": cfg["events"],
        "annualEvents": cfg["annual_events"],
    }
    return payload, stats


def legal_payload(cfg, meta):
    annual = pd.read_csv(DATA / "legal_annual.csv")
    classes = pd.read_csv(DATA / "legal_classes.csv")
    countries = pd.read_csv(DATA / "legal_countries.csv")
    regions = pd.read_csv(DATA / "legal_regions.csv")
    nonimm = pd.read_csv(DATA / "legal_nonimmigrants.csv")
    years = sorted(countries["fiscal_year"].unique())
    latest = int(years[-1])

    green = annual[annual["series"].str.startswith("Green cards")].set_index("year")["value"]
    natz = annual[annual["series"] == "Naturalizations"].set_index("year")["value"]
    refugees = annual[annual["series"] == "Refugee arrivals"].set_index("year")["value"]
    by_group = countries[countries["fiscal_year"] == latest].groupby("group")["green_cards"].sum()
    top = countries[(countries["fiscal_year"] == latest) & (countries["country"] != "Not broken out by country")] \
        .groupby("country")["green_cards"].sum().sort_values(ascending=False)
    family = int(by_group.get("Immediate relatives of citizens", 0) + by_group.get("Family-sponsored preferences", 0))
    stats = {
        "fy": latest,
        "green": int(green[latest]), "green_change": pct(green[latest], green.get(latest - 1)),
        "natz": int(natz[latest]), "natz_change": pct(natz[latest], natz.get(latest - 1)),
        "refugees": int(refugees[latest]), "refugees_change": pct(refugees[latest], refugees.get(latest - 1)),
        "family_share": round(family / green[latest] * 100, 1),
        "employment_share": round(by_group.get("Employment-based preferences", 0) / green[latest] * 100, 1),
        "top_country": top.index[0], "top_country_n": int(top.iloc[0]),
        "top_country_share": round(top.iloc[0] / green[latest] * 100, 1),
        "green_peak_year": int(green.idxmax()), "green_peak": int(green.max()),
    }
    payload = {
        "annual": {s: [[int(y), int(v)] for y, v in g[["year", "value"]].values]
                   for s, g in annual.groupby("series")},
        "classes": [[int(r.fiscal_year), r.group, r._3, int(r.new_arrivals), int(r.adjustments), int(r.total)]
                    for r in classes.itertuples()],
        "years": [int(y) for y in years],
        "countries": pack(countries, COUNTRY_DIMS, years, "fiscal_year", "green_cards"),
        "regions": pack(regions, REGION_DIMS, years, "fiscal_year", "green_cards"),
        "nonimmigrants": [[int(r.fiscal_year), r.category, r.visa, "" if pd.isna(r.code) else r.code,
                           int(r.admissions)] for r in nonimm.itertuples()],
        "events": cfg["events"],
    }
    return payload, stats


def map_payload():
    df = pd.read_csv(DATA / "acs_areas.csv", dtype={"code": str, "state": str})
    df["code"] = df["code"].fillna("")          # the national row has no code
    cols = acs.VALUE_COLUMNS

    def num(v):
        return None if pd.isna(v) else (int(v) if float(v).is_integer() else float(v))

    levels = {lvl: [[r.code, *[num(getattr(r, c)) for c in cols]] for r in g.itertuples()]
              for lvl, g in df.groupby("level")}
    us = df[df["level"] == "us"].iloc[0]
    top = df[df["level"] == "state"].sort_values("pct_foreign_born", ascending=False).iloc[0]
    stats = {
        "vintage": int(us["vintage"]),
        "us_pct": round(float(us["pct_foreign_born"]), 1),
        "us_foreign_born": int(us["foreign_born"]),
        "us_naturalized": round(float(us["pct_naturalized"]), 1),
        "us_recent": round(float(us["pct_recent"]), 1),
        "top_state": acs.STATE_NAMES.get(top["code"], top["code"]),
        "top_state_pct": round(float(top["pct_foreign_born"]), 1),
        "top_state_n": int(top["foreign_born"]),
    }
    payload = {
        "vintage": stats["vintage"],
        "columns": ["code"] + cols,
        "measures": [{"key": k, "label": l, "unit": u, "desc": d} for k, l, u, d in acs.MEASURES],
        "levels": levels,
        "stateNames": acs.STATE_NAMES,
    }
    return payload, stats


def num(v):
    return None if pd.isna(v) else (int(v) if float(v).is_integer() else float(v))


def groups_payload():
    g = pd.read_csv(MICRO / "acs_groups.csv", dtype={"code": str})
    g["code"] = g["code"].fillna("")
    g["region"] = g["region"].fillna("")
    rows = [[r.level, r.code, r.group, r.region, *[num(getattr(r, c)) for c in GROUP_COLS]] for r in g.itertuples()]
    us = g[g["level"] == "us"].set_index("group")
    all_imm = us.loc["All immigrants"]
    countries = us[~us.index.isin(["All immigrants", "U.S.-born"])]
    stats = {
        "groups": int(len(countries)),
        "immigrants": int(all_imm["population"]),
        "top": countries["population"].idxmax(), "top_pct": round(float(countries["pct_of_immigrants"].max()), 1),
        "most_educated": countries[countries["population"] >= 100_000]["pct_bachelors"].idxmax(),
        "most_educated_pct": round(float(countries[countries["population"] >= 100_000]["pct_bachelors"].max()), 1),
        "naturalized": round(float(all_imm["pct_naturalized"]), 1),
    }
    payload = {"columns": ["level", "code", "group", "region"] + GROUP_COLS,
               "measures": [{"key": k, "label": l, "unit": u, "who": w} for k, l, u, w in GROUP_MEASURES],
               "rows": rows, "stateNames": acs.STATE_NAMES}
    return payload, stats


def map_extras():
    """Birthplace layers for the map and the CPS trend, from the microdata aggregates."""
    a = pd.read_csv(MICRO / "acs_group_areas.csv", dtype={"code": str})
    a = a[a["group"] != "All residents"]
    layers = {}
    for (group, level), g in a.groupby(["group", "level"]):
        layers.setdefault(group, {})[level] = [[r.code, num(r.population), num(r.pct_of_residents), num(r.pct_of_immigrants)]
                                               for r in g.itertuples()]
    c = pd.read_csv(MICRO / "cps_annual.csv")
    cps = {"years": [int(y) for y in c["year"]],
           "series": {col: [num(v) for v in c[col]] for col in c.columns if col not in ("year", "records")}}
    return {"groupAreas": layers, "cps": cps}


def render(env, template, out, **ctx):
    html = env.get_template(template).render(**ctx)
    (SITE / out).write_text(html, encoding="utf-8")
    return len(html)


def build():
    cfg = load_config()
    meta = json.loads((DATA / "meta.json").read_text())
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    # "</" cannot appear inside an inline <script>; JSON allows "<\/".
    env.filters["scriptjson"] = lambda obj: json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")

    SITE.mkdir(exist_ok=True)
    (SITE / "data").mkdir(exist_ok=True)

    legal, legal_stats = legal_payload(cfg["legal"], meta["legal"])
    border, border_stats = border_payload(cfg["border"], meta["border"])
    common = dict(cfg=cfg, meta=meta, sources=meta["sources"])

    n1 = render(env, "index.html", "index.html", page=cfg["legal"], info=meta["legal"],
                stats=legal_stats, data=legal, **common)
    n2 = render(env, "border.html", "border.html", page=cfg["border"], info=meta["border"],
                stats=border_stats, data=border,
                first_label=month_label(meta["border"]["first_month"]),
                detail_label=month_label(meta["border"]["detail_from_month"]),
                latest_label=month_label(meta["border"]["latest_month"]), **common)

    map_data, map_stats = map_payload()
    map_data.update(map_extras())
    n3 = render(env, "map.html", "map.html", page=cfg["map"], info=meta.get("acs", {}),
                stats=map_stats, data=map_data, **common)
    groups_data, groups_stats = groups_payload()
    n4 = render(env, "groups.html", "groups.html", page=cfg["groups"], info=meta.get("acs", {}),
                stats=groups_stats, data=groups_data, **common)

    for name in DOWNLOADS:
        shutil.copy(DATA / name, SITE / "data" / name)
    for name in ("acs_groups.csv", "acs_group_areas.csv", "cps_annual.csv"):
        shutil.copy(MICRO / name, SITE / "data" / name)
    for asset in ("favicon.svg", "preview.png", "apple-touch-icon.png"):
        src = TEMPLATES / asset
        if src.exists():
            shutil.copy(src, SITE / asset)

    print(f"built site/index.html ({n1 / 1e6:.2f} MB), site/border.html ({n2 / 1e6:.2f} MB), "
          f"site/map.html ({n3 / 1e6:.2f} MB) and site/groups.html ({n4 / 1e6:.2f} MB)")


if __name__ == "__main__":
    build()
