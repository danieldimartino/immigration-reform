# U.S. Immigration Data Explorer

Two interactive, self-updating pages built from official U.S. government data:

- **Legal immigration** (`index.html`): green cards by country of birth, category
  and class since FY2005; new arrivals vs. adjustments of status; lawful permanent
  residents since 1820, naturalizations since 1907 and refugee arrivals since 1980;
  nonimmigrant (temporary visa) admissions by class.
- **Border encounters** (`border.html`): Border Patrol apprehensions by fiscal year
  since 1925, monthly since October 1999, and CBP's full encounter detail (nationality,
  family status, sector, port of entry) since October 2019. Title 42 expulsions are
  excluded throughout.
- **Immigrant map** (`map.html`): the foreign-born population of every state, metro
  area and PUMA from the Census Bureau's ACS 5-year estimates: share of residents,
  citizenship, period of entry, region of birth, English, education, poverty and
  income. Boundaries are drawn live from Census TIGERweb. A birthplace selector maps
  any of 130+ origin groups by state (the 25 largest by metro area and PUMA), and a
  CPS series tracks the immigrant population each year since 1994.
- **Immigrant groups** (`groups.html`): profiles of immigrants by country of birth
  (citizenship, arrival, age, education, English, work, income, housing, health
  coverage), nationally and by state, compared with all immigrants or the U.S.-born.

Built from the MI data-site template, modeled on
[flock-crime-tracker](https://github.com/CharlesFainLehman/flock-crime-tracker).

## The data

All sources are U.S. government works in the public domain. No API key is needed.

| Source | What it provides | How it is fetched |
|---|---|---|
| [DHS Office of Homeland Security Statistics, Yearbook of Immigration Statistics](https://ohss.dhs.gov/topics/immigration/yearbook) | Green cards since 1820 (Table 1) and by class (Table 6), naturalizations (Table 21), refugee arrivals (Table 13), nonimmigrant admissions (Table 26), port-of-entry encounters FY2005–2019 (Table 36) | The newest edition's Excel workbooks, found by reading the Yearbook pages |
| [OHSS, LPRs by country of birth and major class](https://ohss.dhs.gov/topics/immigration/lawful-permanent-residents/lprs-country-birth-and-major-classes-admission) | Green cards by country × class × year, FY2005 on | The workbook linked from that page |
| [CBP Nationwide Encounters](https://www.cbp.gov/document/stats/nationwide-encounters) | Monthly encounters by sector, nationality, demographic and type, FY2020 on | The newest monthly CSV plus CBP's fixed FY2020–23 file |
| [Census Bureau ACS 5-year summary file](https://www.census.gov/programs-surveys/acs/data/summary-file.html) | Foreign-born characteristics for states, metro areas and PUMAs (tables B05002, B05005, B16005, B06009, B06012, B06011) | Public pipe-delimited files, streamed and filtered to the ~3,400 areas needed; refetched only when `acs.vintage` in config changes |
| IPUMS USA (ACS 2020–2024 five-year) and IPUMS CPS (March supplement 1994–2025) microdata | Characteristics by country of birth; birthplace groups by area; the immigrant population by year | Aggregated once by `tools/extract_microdata.py` from Stata files kept in OneDrive; only the aggregates in `data/microdata/` are committed, as IPUMS terms allow |
| CBP historical PDFs ([annual 1925–2020](https://www.cbp.gov/document/stats/us-border-patrol-total-apprehensions-fy-1925-fy-2020), [monthly by sector 2000–2020](https://www.cbp.gov/document/stats/us-border-patrol-monthly-encounters-fy-2000-fy-2020)) | Border Patrol apprehensions before FY2020 | Extracted once by `tools/extract_cbp_history.py` into `data/history/`, which is committed |

Where files overlap, the newer (revised) figures win and validation checks that
they agree. DHS rounds every cell to the nearest 10; validation allows for that
and cross-checks the by-country workbook against the Yearbook's class table.

## What the pages do

- Filters at the top of each explorer apply to every chart and table below them,
  and the URL records them so any view can be shared as a link.
- Stacked charts break totals down by any dimension, with hover and keyboard
  tooltips, a table view, and policy milestones marked (edit them under `events`
  in `config.json`).
- Comparison tables between any two fiscal years, sortable, with an incomplete
  current year compared like for like against the same months.

## Start here

```bash
pip install -r requirements.txt
python pipeline/run_update.py
python -m http.server 8000 --directory site    # then open http://localhost:8000
```

1. **`config.json`**: titles, method notes, chart events, source pages.
2. **`pipeline/transform.py`**: the cleaning and shaping.
3. **`templates/`**: `base.html` (shared frame and styles), `_lib.js` (charts),
   `index.html` (legal immigration) and `border.html` (border encounters).

Never edit `site/`. It is regenerated every run.

## Publishing it

1. **Settings → Pages → Source: GitHub Actions.** Do this once, before the
   first run, or the deploy step fails. A template copies files, not settings,
   so this does not come across on its own.
2. Push to `main`. The workflow builds and deploys.
3. **Actions tab → Update data and publish → Run workflow** to trigger it by
   hand at any time.

The site lands at `https://<your-username>.github.io/<repo>/`. For a custom
domain, see the workshop handout.

Publishing needs the repository to be public, unless you have GitHub Pro.

## The daily job

`.github/workflows/update.yml` runs the pipeline every morning, commits any
changed data, and republishes. The commit history becomes a record of what
changed and when.

If you edit anything under `.github/workflows/`, your push will be rejected
unless your credentials carry the `workflow` scope. Fix it once with:

```bash
gh auth refresh -h github.com -s workflow
```

If your pipeline calls an API, add the key under **Settings → Secrets and
variables → Actions** and reference it in the workflow's `env:` block. Never
put a key in a file.

Scheduled workflows pause after about two months of no repository activity.
GitHub emails you; one commit turns it back on.

## When something breaks

The Actions tab holds the log for every run. A failed run is a log you can hand
to Claude verbatim — that is usually faster than describing the problem.

If validation fails, that is the system working. The live site keeps the last
good data until the underlying problem is fixed.
