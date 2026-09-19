"""Publix collector — NOT IMPLEMENTED ON PURPOSE.

Publix has no licensed price API. Collecting from its website or app is gated on
spec open question 1 (ToS and legal posture). Get a real answer before writing
this. See directives/collect_publix.md for the contract this collector must meet
once that answer exists: PoliteClient from _base (one store per minute,
off-peak, honest user agent, hard stop on 429/403), raw payloads saved via
save_payload, observations inserted via insert_observations, promo prices tagged
price_type='promo'. No delivery-platform (Instacart etc.) prices, ever.
"""


def collect(db, cfg):
    raise NotImplementedError("Publix collection is blocked on the ToS/legal review (spec §11 Q1).")
