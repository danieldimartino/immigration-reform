# Working in this repository

This is a small data site: a pipeline that refreshes a dataset on a schedule,
and a static page built from it, published to GitHub Pages. It was created from
the MI data-site template and lives in the author's own GitHub account.

## Layout

```
config.json           every setting a person edits by hand
data/history/         committed one-time extraction of CBP's historical PDFs
data/border_*.csv     generated — border encounters, monthly / by sector / annual
data/legal_*.csv      generated — green cards, classes, countries, regions,
                      nonimmigrant admissions, long-run annual series
data/acs_areas.csv    generated once per ACS vintage — foreign-born measures by
                      state, metro area and PUMA (committed; see acs.py)
data/microdata/       committed aggregates from IPUMS microdata (never the
                      microdata itself): group profiles, group areas, CPS trend
data/meta.json        generated — row counts, update date, coverage, provenance
data/raw/             gitignored scratch space for downloads
pipeline/fetch.py     step 1 — download CBP CSVs and OHSS Excel workbooks
pipeline/transform.py step 2 — clean and shape it (most work happens here)
pipeline/ohss.py      reader for the OHSS workbook layout, used by step 2
pipeline/acs.py       ACS tables, rows and measures for the map, used by steps 1–4
pipeline/validate_data.py  step 3 — refuse to publish something broken
pipeline/build_site.py     step 4 — render templates/ into site/
templates/base.html   shared frame, styles, nav and footer — EDIT THESE
templates/_lib.js     shared chart and table code
templates/index.html  the legal-immigration page
templates/border.html the border-encounters page
templates/map.html    the immigrant map (Leaflet + Census TIGERweb boundaries)
templates/groups.html immigrant profiles by country of birth
tools/extract_microdata.py  one-time aggregation of the OneDrive microdata
tools/extract_cbp_history.py  one-time PDF extraction (not part of the daily run)
site/                 generated output — DO NOT EDIT BY HAND
```

Run everything with `python pipeline/run_update.py`.

## The data

Two official sources, both public domain. DHS's Office of Homeland Security
Statistics (OHSS) publishes the Yearbook of Immigration Statistics and the
green-cards-by-country workbook as Excel files whose names carry a publication
date, so `fetch.py` finds them by reading the pages that list them, newest
edition first. CBP's Nationwide Encounters CSVs work the same way. CBP's
pre-FY2020 Border Patrol figures exist only as PDFs; they were extracted once
into `data/history/` and are not refetched.

Title 42 expulsions are excluded everywhere (config `exclude_encounter_types`).
DHS rounds every cell to the nearest 10, so validation allows 5 per cell summed.

The map uses the Census Bureau's ACS 5-year summary file: public files, no API
key. They are large and change once a year, so `fetch.py` downloads them only
when `acs.vintage` in config.json is newer than the vintage in
`data/acs_areas.csv`; otherwise the committed file stands. `transform.py`
checks the table-shells file so a re-numbered row stops the run. To move to a
new vintage, change `acs.vintage` and run the pipeline.

IPUMS microdata (`*.dta`, several GB) lives in the author's OneDrive under
`Data/Census/` and is git-ignored. `tools/extract_microdata.py` reads it
locally and writes `data/microdata/*.csv`; rerun it when a new extract
arrives. Never commit microdata or anything that identifies a respondent.

## Conventions

- **Never edit `site/`.** It is regenerated on every run and your changes will
  be silently overwritten. Change `templates/index.html` instead.
- **Keep the four pipeline steps separate.** Fetching, transforming,
  validating, and rendering stay in their own files. Do not collapse them.
- **`config.json` is the only file a non-technical person should need to open.**
  If a new setting would be useful to them, add it there rather than hardcoding
  it in a script.
- **Add a validation check whenever you find a new way the data can be wrong.**
  A failing pipeline that keeps yesterday's good site is the desired behavior.
- Prefer stdlib and the four libraries already in `requirements.txt`. Ask
  before adding a dependency.

## Rules that are not negotiable

- **Never commit secrets.** API keys go in repository secrets and are read from
  the environment. If you find a key in a file, stop and say so.
- **Never put internal MI data in this repository.** No CRM exports, no donor
  records, no licensed or purchased datasets, nothing from Virtuous, Snowflake,
  or Piano. This repository is public and sits on a personal account, so there
  is no second pair of eyes. Published data must be public data the author is
  permitted to redistribute. If you are unsure about a file, stop and ask.
- **Never remove the provenance footer** — last updated, source, method note,
  CSV download. If the numbers are shown, their origin is shown with them.
- **Do not weaken `validate_data.py` to make a run pass.** If validation fails,
  the data or the transform is wrong. Fix that.

## Before the site is shared

Run `/publish` — see `.claude/commands/publish.md`.
