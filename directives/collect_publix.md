# Directive: collect_publix

**Status: BLOCKED — do not build yet.** Publix has no licensed price API. Collection from its website or app waits on spec §11 Q1 (ToS and legal posture). Get a real answer, not an assumption.

## Contract, once unblocked
- Module `execution/collectors/publix.py` exposes `collect(db, cfg) -> summary`
- Uses `PoliteClient` with `min_interval=60` (one store per minute), runs off-peak on the same Tuesday-overnight window, sends the honest user agent, backs off exponentially, and **hard-stops on 429/403**
- Every raw response goes through `save_payload("publix", body)`; its hash goes on each observation
- Promo, sale, or loyalty prices are tagged `price_type='promo'` (or `member`). Anything unclassifiable is `unknown`, and QA blocks the week above 10% unknown
- Pack size is parsed per observation with `parse_pack_size`, never taken from the mapping
- **Never** use delivery-platform prices (Instacart and similar). Their markups are retailer-set and unannounced
- Stores go in `stores` with `store_id='publix:<num>'`, county by coordinates

## Resilience
The index must survive losing this banner. If it gets blocked, the coverage rule rolls affected counties up, and nothing is silently interpolated.
