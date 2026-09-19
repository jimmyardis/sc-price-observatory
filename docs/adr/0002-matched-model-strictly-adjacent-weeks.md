# 2. Price relatives use strictly adjacent collection weeks

**Status:** accepted (2026-09-16)

The spec says only items observed in both t and t-1 at the same store enter a relative. We take that literally: an item that returns after a gap re-links at its observed price and contributes **no** relative that week (BLS would compare it against its imputed price). This slightly under-uses data but can never read a reappearance as a price change, which is the property we most need to defend.

"t-1" means the geo's previous *collection* week. If an entire week is missing for a geo (collector outage), the next relative spans the gap rather than chaining a false 0% week.

Imputed prices (stratum relative, or all-strata relative if the stratum has no matches) feed basket cost and `imputed_share` only, never the next week's relative.
