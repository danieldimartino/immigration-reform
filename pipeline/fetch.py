"""
STEP 1 — get the raw data.

Two official sources, both public-domain federal statistics:

  CBP Nationwide Encounters (monthly CSVs)
    data/raw/cbp_latest.csv    the newest rolling file, found by reading the page
    data/raw/cbp_archive.csv   the fixed FY2020–FY2023 file, for the earlier years

  DHS Office of Homeland Security Statistics (Excel workbooks)
    data/raw/ohss_lpr_by_country.xlsx     green cards by country, class and year
    data/raw/yearbook_<topic>.xlsx        Yearbook of Immigration Statistics tables

OHSS files carry a publication date in their names, so each is found by
reading the page that lists it rather than by a fixed URL. Every URL actually
used is written to data/raw/sources.json for the provenance footer.

If a page cannot be read or a file is missing, this raises and the site keeps
its last good data. Historical Border Patrol figures that CBP publishes only
as PDFs are a one-time extraction, committed under data/history/ — see
tools/extract_cbp_history.py — and are not fetched here.
"""
import csv
import json
import re

import requests

import acs
from common import DATA, load_config

RAW_DIR = DATA / "raw"
CBP_LATEST = RAW_DIR / "cbp_latest.csv"
CBP_ARCHIVE = RAW_DIR / "cbp_archive.csv"
LPR_BY_COUNTRY = RAW_DIR / "ohss_lpr_by_country.xlsx"
YEARBOOK_TOPICS = ("lawful_permanent_residents", "naturalizations", "refugees",
                   "nonimmigrants", "enforcement")
SOURCES = RAW_DIR / "sources.json"
ACS_DIR = RAW_DIR / "acs"
ACS_OUT = DATA / "acs_areas.csv"

# Both sites refuse requests without a browser-like user agent.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; public-data-site; +https://github.com)"}

# e.g. /sites/default/files/2026-09/nationwide-encounters-fy23-fy26-aug-aor_0.csv
# The "aor" files break encounters out by Border Patrol sector and field office.
CBP_LINK = re.compile(
    r'href="(?P<path>/sites/default/files/(?P<folder>\d{4}-\d{2})/'
    r'nationwide-encounters-fy\d{2}-fy\d{2}-[a-z]{3}-aor(?:_\d+)?\.csv)"'
)
XLSX_LINK = re.compile(r'href="(?P<path>/(?:system|sites/default)/files/[^"]+\.xlsx)"')
YEARBOOK_YEAR = re.compile(r'href="/topics/immigration/yearbook/(\d{4})"')


def get(url, **kw):
    r = requests.get(url, headers=HEADERS, timeout=120, **kw)
    r.raise_for_status()
    return r


def yearbook_path(path):
    return RAW_DIR / f"yearbook_{path}.xlsx"


def find_cbp_url(page_url):
    links = [(m["folder"], m["path"]) for m in CBP_LINK.finditer(get(page_url).text)]
    if not links:
        raise SystemExit(f"FAIL: no monthly encounters CSV linked from {page_url}")
    # The upload folder is named by year-month, so the newest sorts last.
    return "https://www.cbp.gov" + max(links)[1]


def find_xlsx(page_url, name_contains):
    for m in XLSX_LINK.finditer(get(page_url).text):
        if name_contains in m["path"].rsplit("/", 1)[-1]:
            return "https://ohss.dhs.gov" + m["path"]
    return None


def find_yearbook_urls(index_url):
    """
    The newest Yearbook edition that publishes each topic. Editions lag
    unevenly (enforcement tables come out a year after the others), so each
    topic is taken from the most recent year that has it.
    """
    years = sorted({int(y) for y in YEARBOOK_YEAR.findall(get(index_url).text)}, reverse=True)
    if not years:
        raise SystemExit(f"FAIL: no yearbook editions linked from {index_url}")
    found = {}
    for year in years[:3]:
        page = get(f"{index_url}/{year}").text
        for m in XLSX_LINK.finditer(page):
            name = m["path"].rsplit("/", 1)[-1]
            for topic in YEARBOOK_TOPICS:
                if topic not in found and f"yearbook_{topic}" in name:
                    found[topic] = {"url": "https://ohss.dhs.gov" + m["path"], "edition": year}
        if len(found) == len(YEARBOOK_TOPICS):
            break
    missing = [t for t in YEARBOOK_TOPICS if t not in found]
    if missing:
        raise SystemExit(f"FAIL: Yearbook workbooks not found for {missing} in {years[:3]}")
    return found


def acs_is_current(cfg):
    """True when data/acs_areas.csv already holds the configured ACS vintage."""
    if not ACS_OUT.exists():
        return False
    with open(ACS_OUT, newline="") as f:
        row = next(csv.DictReader(f), None)
    return bool(row) and row.get("vintage") == str(cfg["vintage"])


def fetch_acs(cfg):
    """
    Stream each ACS table and keep only the national, state, metro and PUMA
    rows. The files are large (tens of MB each) and change once a year, so
    this runs only when the configured vintage is not yet in
    data/acs_areas.csv.
    """
    if acs_is_current(cfg):
        print(f"ACS {cfg['vintage']} already processed - skipping the Census download")
        return None
    ACS_DIR.mkdir(parents=True, exist_ok=True)
    base = cfg["base_url"].format(vintage=cfg["vintage"])
    prefixes = tuple(acs.LEVELS.values())
    urls = {}
    for table in acs.TABLES:
        url = acs.DATA_URL.format(base=base, vintage=cfg["vintage"], table=table.lower())
        print(f"fetching {url}")
        kept = 0
        with requests.get(url, headers=HEADERS, timeout=600, stream=True) as r, \
                open(ACS_DIR / f"{table}.csv", "w", encoding="utf-8") as out:
            r.raise_for_status()
            for i, raw in enumerate(r.iter_lines()):
                line = raw.decode("utf-8", "replace")
                if i == 0 or line.startswith(prefixes):
                    out.write(line + "\n")
                    kept += i > 0
        if kept < 1000:
            raise SystemExit(f"FAIL: only {kept} geographies found in {table} - wrong file?")
        urls[table] = url
    url = acs.SHELLS_URL.format(base=base, vintage=cfg["vintage"])
    download(url, ACS_DIR / "shells.txt", b"Table ID")
    urls["shells"] = url
    return urls


def download(url, dest, magic):
    print(f"fetching {url}")
    content = get(url).content
    if not content.startswith(magic):
        raise SystemExit(f"FAIL: {url} did not return the expected file type")
    dest.write_bytes(content)


def fetch():
    cfg = load_config()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    sources = {}

    url = find_cbp_url(cfg["border"]["cbp_page_url"])
    download(url, CBP_LATEST, b"Fiscal Year")
    sources["cbp_latest"] = url
    download(cfg["border"]["cbp_archive_csv_url"], CBP_ARCHIVE, b"Fiscal Year")
    sources["cbp_archive"] = cfg["border"]["cbp_archive_csv_url"]

    url = find_xlsx(cfg["ohss"]["lpr_page_url"], "lpr_by_country")
    if not url:
        raise SystemExit(f"FAIL: no LPR-by-country workbook on {cfg['ohss']['lpr_page_url']}")
    download(url, LPR_BY_COUNTRY, b"PK")         # .xlsx files are zip archives
    sources["ohss_lpr_by_country"] = url

    for topic, info in find_yearbook_urls(cfg["ohss"]["yearbook_url"]).items():
        download(info["url"], yearbook_path(topic), b"PK")
        sources[f"yearbook_{topic}"] = info

    acs_urls = fetch_acs(cfg["acs"])
    if acs_urls:
        sources["acs"] = {"vintage": cfg["acs"]["vintage"], "files": acs_urls}
    elif SOURCES.exists():
        sources["acs"] = json.loads(SOURCES.read_text()).get("acs")

    SOURCES.write_text(json.dumps(sources, indent=2))
    print(f"raw data in {RAW_DIR.relative_to(DATA.parent)}")


if __name__ == "__main__":
    fetch()
