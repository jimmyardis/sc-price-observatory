# Config changelog

Item list, weights, basket, and method changes, with effective dates. Freeze the item list quarterly.

## 2026-09-19: basket tfp2021-v1 (proposed), weights 2025-12 (verified)
- Household is now the USDA reference family of four (was a draft family of three).
- Basket quantities are generated from the Thrifty Food Plan, 2021 (reference family table, report pp. 37-38) by `execution/calibrate_basket.py`: category pounds are split by ERS per-capita availability, and units are converted with sourced factors (TFP 15.34 fl oz/lb; FoodData Central densities; ERS egg weight; FNS Food Buying Guide canned-to-dry bean yield; coffee from TFP's "1 cup per day" at the SCA 55 g/L ratio). Status `proposed` until reviewed.
- Weights are the official BLS CPI-U relative importances for December 2025, reconciled to group totals. Stratum codes corrected against BLS series titles: FE01/FE02 → FE (Other meats), FH01 → FH (Eggs), FN02 (frozen juice) → FN03 (nonfrozen juices; our orange juice is refrigerated).
- `config_verified` now requires basket status `final`, not merely "not draft".

## 2026-09-19: regional method regional-0.1.0; time price projected flag
- New `config/regional_basket.json`: 22 concepts priced from BLS South average prices, 21 excluded with reasons. Start 2006-01. Imputation: U.S. item relative, then South basket relative, then carry ≤ 2 months. Suppressed above 0.25 imputed share.
- `wage_is_projected` now starts at the last QCEW quarter's midpoint, not its end, because values past the midpoint move when the next quarter publishes. No numbers had been published yet, so method 0.1.0 is unchanged.

## 2026-09-16: method 0.1.0 (Phase 0 scaffold)
- Item list v1: 60 items across 43 concepts; 17 concepts tracked in both store and national tier.
- Weights `2025-draft`: **placeholder**, not verified against BLS.
- Basket `2026Q3-draft`: **placeholder** quantities, family of three.
- Regions: draft county assignment (see `geo_sc.json` note).
