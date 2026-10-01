# Aggregates from IPUMS microdata

Produced by `tools/extract_microdata.py` on 2026-09-30. The microdata
stays in OneDrive and is never committed; only these aggregates are, as the IPUMS
terms of use allow for published statistics.

- `acs_groups.csv`: characteristics of immigrants by country of birth (groups with at
  least 25,000 residents nationally; state rows need 5,000 residents and
  100 records), with "All immigrants" and "U.S.-born" for comparison. Source:
  IPUMS USA, American Community Survey 2020–2024 five-year sample, person weights.
- `acs_group_areas.csv`: population of every profiled group by state, and of the
  25 largest groups by metro area and PUMA (counts under 200 omitted).
- `cps_annual.csv`: the foreign-born population by year, citizenship, recency of
  arrival and region of birth. Source: IPUMS CPS, March supplement (ASEC) 1994–2025.

Immigrants are the foreign-born excluding people born abroad to U.S.-citizen parents.
Medians are weighted. Full-time wage covers wage earners working 50+ weeks and 35+ hours.

Citations:
Steven Ruggles, Sarah Flood, Matthew Sobek, et al. IPUMS USA: Version 15.0 [dataset].
Minneapolis, MN: IPUMS, 2024. https://doi.org/10.18128/D010.V15.0
Sarah Flood, Miriam King, Renae Rodgers, et al. IPUMS CPS: Version 12.0 [dataset].
Minneapolis, MN: IPUMS, 2024. https://doi.org/10.18128/D030.V12.0

Groups profiled (132): Afghanistan, Africa, Ns/nec, Albania, Algeria, Argentina, Armenia, Asia, Nec/ns, Australia, Austria, Azerbaijan, Bahamas, Bangladesh, Barbados, Belgium, Belize/british Honduras, Bhutan, Bolivia, Bosnia, Brazil, Bulgaria, Burma (myanmar), Byelorussia, Cambodia (kampuchea), Cameroon, Canada, Cape Verde, Caribbean, Ns, Chile, China, Colombia, Congo, Costa Rica, Croatia, Cuba, Czech Republic, Denmark, Dominica, Dominican Republic, Eastern Africa, Nec/ns, Ecuador, Egypt/united Arab Rep, El Salvador, England, Eritrea, Ethiopia, Europe, Ns, Fiji, Former Yugoslavia, France, Germany, Ghana, Greece, Grenada, Guatemala, Guyana/british Guiana, Haiti, Honduras, Hong Kong, Hungary, India, Indonesia, Iran, Iraq, Ireland, Israel/palestine, Italy, Ivory Coast, Jamaica, Japan, Jordan, Kazakhstan, Kenya, Kuwait, Laos, Lebanon, Liberia, Lithuania, Macedonia, Malaysia, Mexico, Micronesia, Moldavia, Morocco, Nepal, Netherlands, New Zealand, Nicaragua, Nigeria, Other Ussr/russia, Pakistan, Panama, Peru, Philippines, Poland, Portugal, Republic of Georgia, Romania, Saudi Arabia, Scotland, Senegal, Serbia, Sierra Leone, Singapore, Somalia, South Africa (union Of), South Korea, Spain, Sri Lanka (ceylon), St. Lucia, Sudan, Sweden, Switzerland, Syria, Taiwan, Tanzania, Thailand, Togo, Trinidad and Tobago, Turkey, Uganda, Ukraine, United Arab Emirates, United Kingdom (not specified), Uruguay, Ussr, Ns, Uzbekistan, Venezuela, Vietnam, Western Africa, Ns, Yemen Arab Republic (north), Zaire, Zimbabwe
