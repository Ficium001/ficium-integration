# Changelog

## 1.6.0 — 2026-10-17

Architecture rule: everything between the borrower side and the institution side goes through the interface
API. No direct calls, database connections or storage access between them.

- `document_upload.response.upload_url` is now an interface endpoint,
  `PUT /integration/v1/deal-documents/uploads/{upload_id}/content`, never a storage URL. The borrower side PUTs
  the raw bytes there, signed over the bytes with the same scheme and keys as the calls. Enforced by pattern.
- `document_complete`: the institution checks the hash against the bytes it received on that endpoint.
- Nothing implemented the 1.5.0 storage-URL behaviour yet, so no deployed side breaks.

## 1.5.0 — 2026-10-17

Reusing documents the borrower already holds. When a bank requests a document, the borrower either shares a
matching copy from their vault or uploads a new one.

- Checklist item (`deal_document`): optional `document_type` (aligned with the vault's types) and
  `max_age_days`. Age is measured from the document's own date (payslip period, statement date). A copy older
  than `max_age_days`, or whose date is unknown, must be uploaded new.
- `document_upload.request`: required `source` (`vault` or `new`); `document_date` is required for a vault copy
  so the institution can check its age too.
- Nothing implements 1.4.0 yet, so tightening the upload call here breaks no one.

## 1.4.0 — 2026-10-17

Phase 2: borrowers upload a deal's documents themselves. Only for deals they accepted; files never pass
through either API.

- Event `deal.documents_updated` (institution → borrower): the deal's full checklist (what's needed, from
  whom, status, review note), sent whenever it changes. No file names or contents.
- Call `POST /integration/v1/deal-documents/uploads`: borrower asks for a one-time upload slot for one checklist
  item (PDF, JPEG or PNG, at most 10 MB); returns an https `upload_url` and its expiry.
- Call `POST /integration/v1/deal-documents/uploads/{upload_id}/complete`: borrower confirms with the file's
  SHA-256; returns the item's new state.
- New event type: receivers ship support before senders emit it (the borrower app upgrades first).
- Fix: the TypeScript `VERSION` constant said 1.2.0 in 1.3.0; the consistency check now covers it.

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
