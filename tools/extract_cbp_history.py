"""
One-time extraction of CBP's historical Border Patrol figures, which CBP
publishes only as PDFs. Writes data/history/, which is committed and read by
the daily pipeline. Rerun only if CBP republishes these files.

    pip install pdfplumber        # not a pipeline dependency
    python tools/extract_cbp_history.py

Sources (U.S. Customs and Border Protection, public domain):
  U.S. Border Patrol Total Apprehensions (FY 1925 - FY 2020)
  U.S. Border Patrol Monthly Encounters (FY 2000 - FY 2020)

FY2020 is deliberately left out of both outputs: from March 2020 the PDFs mix
Title 42 expulsions into the counts, and from FY2020 CBP's CSV data separate
them, so the pipeline takes FY2020 onward from the CSVs instead.
"""
import csv
import re
import sys
from datetime import date
from pathlib import Path

import pdfplumber
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "history"
RAW = ROOT / "data" / "raw" / "pdf"

SOURCES = {
    "annual": "https://www.cbp.gov/sites/default/files/assets/documents/2021-Aug/"
              "U.S.%20Border%20Patrol%20Total%20Apprehensions%20%28FY%201925%20-%20FY%202020%29%20%28508%29.pdf",
    "monthly": "https://www.cbp.gov/sites/default/files/assets/documents/2021-Aug/"
               "U.S.%20Border%20Patrol%20Monthly%20Encounters%20%28FY%202000%20-%20FY%202020%29%20%28508%29.pdf",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; public-data-site; +https://github.com)"}
LAST_YEAR = 2019

MONTHS = ["October", "November", "December", "January", "February", "March",
          "April", "May", "June", "July", "August", "September"]
AGGREGATES = {"Coastal Border", "Northern Border", "Southwest Border", "Monthly Total"}


def download(key):
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / f"cbp_history_{key}.pdf"
    if not dest.exists():
        r = requests.get(SOURCES[key], headers=HEADERS, timeout=120)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def num(s):
    s = str(s).replace(",", "").strip()
    return None if s in ("N/A", "-", "") else int(s)      # N/A: sector not yet open, or closed


def clean_sector(s):
    # "Big Bend\n(formerly Marfa)" -> "Big Bend"
    return re.sub(r"\s*\(formerly [^)]*\)", "", s.replace("\n", " ")).strip()


def extract_annual():
    out = {}
    with pdfplumber.open(download("annual")) as pdf:
        for table in pdf.pages[0].extract_tables():
            for row in table:
                if row and row[0] and row[0].strip().isdigit():
                    out[int(row[0])] = num(row[1])
    years = sorted(out)
    assert years[0] == 1925 and years[-1] == 2020 and len(years) == 96, years
    return {y: v for y, v in out.items() if y <= LAST_YEAR}


def extract_monthly(annual):
    rows, checks = [], []
    with pdfplumber.open(download("monthly")) as pdf:
        for page in pdf.pages:
            m = re.search(r"FY\s*(\d{4})", page.extract_text() or "")
            fy = int(m.group(1))
            if fy > LAST_YEAR:
                continue
            table = page.extract_tables()[0]
            header = [clean_sector(c) for c in table[0]]
            assert header[1:13] == MONTHS, header
            sectors, totals = {}, None
            for row in table[1:]:
                name = clean_sector(row[0])
                values = [num(v) for v in row[1:13]]
                if name == "Monthly Total":
                    totals = values
                elif name not in AGGREGATES:
                    sectors[name] = values
            assert totals, f"FY{fy}: no Monthly Total row"
            for i, month in enumerate(MONTHS):
                calendar_year = fy - 1 if i < 3 else fy
                mnum = (i + 9) % 12 + 1
                key = f"{calendar_year}-{mnum:02d}"
                assert sum(v[i] or 0 for v in sectors.values()) == totals[i], f"{key}: sectors != total"
                for name, v in sectors.items():
                    if v[i] is not None:
                        rows.append((key, fy, name, v[i]))
            checks.append((fy, sum(totals), annual[fy]))
    return rows, checks


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    annual = extract_annual()
    monthly, checks = extract_monthly(annual)

    with open(OUT / "usbp_apprehensions_annual.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fiscal_year", "apprehensions"])
        w.writerows(sorted(annual.items()))
    with open(OUT / "usbp_apprehensions_monthly_sector.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "fiscal_year", "sector", "apprehensions"])
        w.writerows(sorted(monthly))

    mismatches = [(fy, a, b) for fy, a, b in checks if a != b]
    (OUT / "README.md").write_text(
        "# Historical Border Patrol apprehensions\n\n"
        "Extracted from CBP's PDFs by `tools/extract_cbp_history.py` on "
        f"{date.today().isoformat()}. Not refreshed by the daily pipeline.\n\n"
        f"- `usbp_apprehensions_annual.csv`: FY1925–FY{LAST_YEAR}, from\n  <{SOURCES['annual']}>\n"
        f"- `usbp_apprehensions_monthly_sector.csv`: FY2000–FY{LAST_YEAR} by Border Patrol sector, from\n"
        f"  <{SOURCES['monthly']}>\n\n"
        "FY2020 onward comes from CBP's Nationwide Encounters CSVs, which separate\n"
        "Title 42 expulsions from Title 8 apprehensions; the PDFs do not.\n\n"
        "Checks at extraction: every month's sectors add up to the PDF's monthly total; "
        "yearly sums of the monthly file against the annual file:\n"
        + ("all years agree.\n" if not mismatches else
           "".join(f"- FY{fy}: monthly {a:,} vs annual {b:,}\n" for fy, a, b in mismatches))
    )
    print(f"annual: {len(annual)} years; monthly: {len(monthly)} rows; "
          f"{len(mismatches)} year(s) where monthly and annual PDFs disagree")
    for fy, a, b in mismatches:
        print(f"  FY{fy}: monthly {a:,} vs annual {b:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
