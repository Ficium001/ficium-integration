# ficium-integration

The only interface between the Ficium borrower app and the Ficium institution app. Both apps import this package, validate every event they send or receive against it, and sign and verify with the same code.

Design and migration plan: *Ficium integration contract v1* (Claude Doc).

## What's here

| Path | Contents |
| --- | --- |
| `schemas/envelope.v1.json` | The event envelope. Routes each `type` to its data schema and enforces which side may send it |
| `schemas/events/` | One schema per event type and version |
| `schemas/calls/` | The synchronous acceptance call, request and response |
| `schemas/common.v1.json` | Shared definitions: ids, money, rates, product types, request statuses |
| `fixtures/` | Valid and invalid examples for every event and call, plus signing vectors |
| `python/ficium_contract` | Python validator and signer |
| `ts/src` | TypeScript validator and signer |

## Rules

- **Rates are decimal fractions.** `0.0425` means 4.25% a year. `4.25` is rejected.
- **Direction is enforced.** Request events come only from `borrower`; bid, pipeline and market events only from `institution`; `chat.message` from either, with `data.sender_side` equal to `source`.
- **Phase 1 never carries direct identifiers.** Names, email, phone, address, date of birth, NIC number, real user ids and the employer name are rejected by schema.
- **Additive changes stay v1.** New optional fields are allowed; receivers ignore fields they don't know. The envelope itself is closed.
- **Breaking changes get v2.** The sender emits v1 and v2 until the receiver has moved. Receivers ship support first.

## Signing

`Ficium-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>." + raw body>`. One key per direction (`B2I_SIGNING_KEY`, `I2B_SIGNING_KEY`). Verifiers accept a list of keys so rotation needs no downtime, and reject signatures older than 300 seconds.

## Use

Python:

```bash
pip install "ficium-contract @ git+https://github.com/Ficium001/ficium-integration@v1.0.0"
```

```python
import ficium_contract as fc
fc.validate_event(envelope)
header = fc.sign(raw_body, key)
fc.verify(header, raw_body, [current_key, previous_key])
```

TypeScript:

```bash
npm install github:Ficium001/ficium-integration#v1.0.0
```

```ts
import { validateEvent, sign, verify } from "@ficium/contract";
```

## Checks

CI runs on every pull request: secret scan; schema meta-validation; every valid fixture passes and every invalid fixture fails in **both** Python and TypeScript; signing vectors reproduce in both languages; versions agree across `package.json`, `pyproject.toml` and the module; the installed wheel and npm package contain the schemas.
