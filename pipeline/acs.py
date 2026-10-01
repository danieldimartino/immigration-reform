"""
The Census Bureau's ACS 5-year summary file: which tables, rows and
geographies the map uses, and how the measures are computed from them.

The summary file is a set of public pipe-delimited files, one per table,
with a row for every geography in the country (no API key needed). Each
table's columns are named <table>_E<line> (estimate) and <table>_M<line>
(margin of error); the line numbers are documented in the "table shells"
file, and transform.py checks the labels there against ROWS below before
trusting them, so a re-numbered table stops the run instead of mislabelling
a measure.
"""

DATA_URL = "{base}/data/5YRData/acsdt5y{vintage}-{table}.dat"
SHELLS_URL = "{base}/documentation/ACS{vintage}5YR_Table_Shells.txt"

# GEO_ID prefixes: summary level, then a delineation code, then "US".
LEVELS = {
    "us": "0100000US",
    "state": "0400000US",
    "metro": "310M700US",      # metropolitan and micropolitan statistical areas
    "puma": "795P200US",       # 2020 public use microdata areas
}

# Sentinel codes the Census uses in place of an estimate.
NOT_AVAILABLE = {-222222222, -333333333, -555555555, -666666666, -888888888, -999999999}

# Table -> {line: label the shells file must show}. Every line listed is read.
ROWS = {
    "B05002": {1: "Total:", 13: "Foreign-born:", 14: "Naturalized U.S. citizen", 21: "Not a U.S. citizen",
               15: "Europe", 16: "Asia", 17: "Africa", 18: "Oceania", 19: "Latin America", 20: "Northern America",
               22: "Europe", 23: "Asia", 24: "Africa", 25: "Oceania", 26: "Latin America", 27: "Northern America"},
    "B05005": {4: "Foreign-born:", 9: "Foreign-born:", 14: "Foreign-born:", 19: "Foreign-born:"},
    "B16005": {24: "Foreign born:",
               28: 'Speak English "well"', 29: 'Speak English "not well"', 30: 'Speak English "not at all"',
               33: 'Speak English "well"', 34: 'Speak English "not well"', 35: 'Speak English "not at all"',
               38: 'Speak English "well"', 39: 'Speak English "not well"', 40: 'Speak English "not at all"',
               43: 'Speak English "well"', 44: 'Speak English "not well"', 45: 'Speak English "not at all"'},
    "B06009": {25: "Foreign born:", 29: "Bachelor's degree", 30: "Graduate or professional degree"},
    "B06012": {17: "Foreign born:", 18: "Below 100 percent of the poverty level"},
    "B06011": {1: "Total:", 5: "Foreign born"},
}
TABLES = list(ROWS)

# The measures shown on the map, in menu order. `unit` is "%" or "$" or "".
MEASURES = [
    ("pct_foreign_born", "Immigrant share of population", "%",
     "Foreign-born residents as a percent of all residents"),
    ("foreign_born", "Immigrant population", "",
     "Number of foreign-born residents"),
    ("pct_naturalized", "Naturalized citizens", "%",
     "Share of immigrants who are naturalized U.S. citizens"),
    ("pct_recent", "Arrived 2010 or later", "%",
     "Share of immigrants who entered the country in 2010 or later"),
    ("pct_latin_america", "Born in Latin America", "%",
     "Share of immigrants born in Mexico, Central America, South America or the Caribbean"),
    ("pct_asia", "Born in Asia", "%", "Share of immigrants born in Asia"),
    ("pct_europe", "Born in Europe", "%", "Share of immigrants born in Europe"),
    ("pct_africa", "Born in Africa", "%", "Share of immigrants born in Africa"),
    ("pct_limited_english", "Limited English", "%",
     "Share of immigrants age 5+ who speak English less than \"very well\""),
    ("pct_bachelors", "Bachelor's degree or higher", "%",
     "Share of immigrants age 25+ with a bachelor's degree or higher"),
    ("pct_poverty", "In poverty", "%",
     "Share of immigrants living below the poverty line"),
    ("median_income", "Median income of immigrants", "$",
     "Median income in the past 12 months, people age 15+ with income"),
]
MEASURE_KEYS = [m[0] for m in MEASURES]
VALUE_COLUMNS = ["population", "foreign_born"] + [k for k in MEASURE_KEYS if k != "foreign_born"]
COLUMNS = ["level", "code", "state"] + VALUE_COLUMNS + ["vintage"]

STATE_NAMES = {
    "01": "Alabama", "02": "Alaska", "04": "Arizona", "05": "Arkansas", "06": "California",
    "08": "Colorado", "09": "Connecticut", "10": "Delaware", "11": "District of Columbia",
    "12": "Florida", "13": "Georgia", "15": "Hawaii", "16": "Idaho", "17": "Illinois",
    "18": "Indiana", "19": "Iowa", "20": "Kansas", "21": "Kentucky", "22": "Louisiana",
    "23": "Maine", "24": "Maryland", "25": "Massachusetts", "26": "Michigan", "27": "Minnesota",
    "28": "Mississippi", "29": "Missouri", "30": "Montana", "31": "Nebraska", "32": "Nevada",
    "33": "New Hampshire", "34": "New Jersey", "35": "New Mexico", "36": "New York",
    "37": "North Carolina", "38": "North Dakota", "39": "Ohio", "40": "Oklahoma", "41": "Oregon",
    "42": "Pennsylvania", "44": "Rhode Island", "45": "South Carolina", "46": "South Dakota",
    "47": "Tennessee", "48": "Texas", "49": "Utah", "50": "Vermont", "51": "Virginia",
    "53": "Washington", "54": "West Virginia", "55": "Wisconsin", "56": "Wyoming", "72": "Puerto Rico",
}


def level_of(geo_id):
    for level, prefix in LEVELS.items():
        if geo_id.startswith(prefix):
            return level
    return None


def estimate(value):
    """A summary-file cell as a number, or None where the Census prints a sentinel."""
    if value in (None, ""):
        return None
    v = float(value)
    return None if v in NOT_AVAILABLE or v < 0 else v


def share(num, den):
    return None if not den or num is None else round(num / den * 100, 2)


def compute(t):
    """
    Measures for one geography. `t[table][line]` is the estimate (or None).
    Returns population, foreign-born count and every MEASURE_KEYS value.
    """
    b = t["B05002"]
    fb = b[13]
    regions = {name: (b[i] or 0) + (b[j] or 0) for name, i, j in
               (("europe", 15, 22), ("asia", 16, 23), ("africa", 17, 24),
                ("latin_america", 19, 26))}
    entered = t["B05005"]
    entered_total = sum(v or 0 for v in (entered[4], entered[9], entered[14], entered[19]))
    lang = t["B16005"]
    limited = sum(lang[i] or 0 for i in (28, 29, 30, 33, 34, 35, 38, 39, 40, 43, 44, 45))
    edu, pov, inc = t["B06009"], t["B06012"], t["B06011"]
    return {
        "population": b[1],
        "foreign_born": fb,
        "pct_foreign_born": share(fb, b[1]),
        "pct_naturalized": share(b[14], fb),
        "pct_recent": share(entered[4], entered_total),
        "pct_latin_america": share(regions["latin_america"], fb),
        "pct_asia": share(regions["asia"], fb),
        "pct_europe": share(regions["europe"], fb),
        "pct_africa": share(regions["africa"], fb),
        "pct_limited_english": share(limited, lang[24]),
        "pct_bachelors": share((edu[29] or 0) + (edu[30] or 0), edu[25]),
        "pct_poverty": share(pov[18], pov[17]),
        "median_income": inc[5],
    }
