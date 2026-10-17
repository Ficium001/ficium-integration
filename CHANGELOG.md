# Changelog

## 1.3.0 — 2026-10-17

- `bid.placed`, `bid.updated`: a benefit may carry its value, so the borrower side can price it. Optional
  `value_amount` with `value_unit`, always together:
  - `rate_pa`: reduction of the yearly rate as a decimal fraction, like every rate here (0.25% off is `0.0025`).
    Values above `0.1` are rejected as a unit error.
  - `fee_fraction`: share of a fee waived, `0` to `1`.
  - `amount`: money in the bid's currency.
- The benefit item is now one shared definition (`common.v1.json#/$defs/benefit`) used by both events.
- Additive: every 1.2.0 event stays valid, and receivers on 1.2.0 ignore the new fields.

## 1.2.0 — 2026-10-02

- `request.published`: an allocation line's `amount` may be `null` (and is no longer required). Found by the contract gate on the first
  real backfill: 2 of 13 live requests have allocation lines with no amount because the borrower lets institutions decide the split.
  A line still needs a `product_type`. Loosening only; every v1.1.0 event stays valid.

## 1.1.0 — 2026-10-02

- `request.published`: the employer name is no longer part of Phase 1. It is removed from the allowed
  properties and `employer` is added to the rejected identifiers. In a market the size of Mauritius the employer
  alone can identify a borrower. This tightens validation, but no producer existed yet, so no sender is affected.

## 1.0.0 — 2026-10-01

- Envelope v1 with per-type routing and source rules.
- Nine event types: `ping`, `request.published`, `request.status_changed`, `chat.message`, `bid.placed`, `bid.updated`, `bid.withdrawn`, `pipeline.stage_advanced`, `market.intelligence`.
- Acceptance call request and response schemas.
- Python and TypeScript validators and HMAC-SHA256 signing, tested against shared fixtures and signing vectors.
