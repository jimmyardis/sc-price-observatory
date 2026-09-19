# 4. History before collection is a labeled regional reconstruction, never a back-cast

**Status:** accepted (2026-09-19)

Store-level South Carolina prices can't be recovered for the weeks before we started collecting. Kroger's API returns only current prices, web archives don't hold store-selected prices, and the only real historical source (Nielsen/Circana scanner data via the Kilts Center) is paid and needs an academic affiliation.

**Rejected:** rolling today's measured SC basket backwards with regional CPI. That is a national-style number with a formula on top, which is exactly what the README says this project exists to replace. It would look like measurement and wouldn't be.

**Chosen:** a separate series built only from published inputs, named for what it is: *regional prices, local wages*.

- Prices: BLS average prices for the South region (area 0300), one series per concept, no modeling. The basket is the standard basket's quantities restricted to the concepts BLS prices like-for-like (22 of 43), fixed for the whole history so months are comparable. The other 21 are listed with reasons in `config/regional_basket.json`. Yogurt and 2-liter soft drinks were dropped because their South series start in 2018, and 20 years of history with 22 concepts beats 8 years with 24.
- Wages: QCEW for each county, the same source as the measured time price. So the local part of the number is measured.
- Gaps: BLS doesn't publish every item every month. A missing price moves with the same item's U.S. change, else the South basket relative (the all-strata fallback of ADR 0002), else it's carried for at most 2 months. Gaps are filled only from the past, so publishing a new month never changes an old one. Imputed share is by cost, and above 0.25 the month is suppressed (April 2020 and the October 2025 shutdown month).
- Publication: its own snapshot schema (`regional@1`) and directory, its own `method_version`, and the same no-silent-revision rule. Every file says "a reconstruction, not a measurement".

**Also decided here:** hours computed on a *projected* wage (past the last published quarter's midpoint) are provisional. The next QCEW quarter moves them, so the silent-revision gate exempts them, in both the measured and regional snapshots. Before this change, the first new QCEW quarter would have blocked every later publication.
