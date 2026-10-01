# Historical Border Patrol apprehensions

Extracted from CBP's PDFs by `tools/extract_cbp_history.py` on 2026-09-29. Not refreshed by the daily pipeline.

- `usbp_apprehensions_annual.csv`: FY1925–FY2019, from
  <https://www.cbp.gov/sites/default/files/assets/documents/2021-Aug/U.S.%20Border%20Patrol%20Total%20Apprehensions%20%28FY%201925%20-%20FY%202020%29%20%28508%29.pdf>
- `usbp_apprehensions_monthly_sector.csv`: FY2000–FY2019 by Border Patrol sector, from
  <https://www.cbp.gov/sites/default/files/assets/documents/2021-Aug/U.S.%20Border%20Patrol%20Monthly%20Encounters%20%28FY%202000%20-%20FY%202020%29%20%28508%29.pdf>

FY2020 onward comes from CBP's Nationwide Encounters CSVs, which separate
Title 42 expulsions from Title 8 apprehensions; the PDFs do not.

Checks at extraction: every month's sectors add up to the PDF's monthly total; yearly sums of the monthly file against the annual file:
all years agree.
