# Optional model protocol adapters

The candidate includes an OpenAI Responses request/response adapter, a provider-neutral local JSON adapter and an in-memory mock transport. It has no HTTP sender, credential discovery or live provider configuration. The OpenAI adapter prepares text input, an explicit output-token limit and `store=false`, then validates the mock assistant output and reported usage. [Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create).

The built-in mock workers open only synthetic benchmark packets. They model abstention and report mock usage. The local adapter expects JSON fields for text, model identity and prompt and generated token counts. External offline model programs can submit through the [task contract](task.md).

## Request limits and resume

Use `benchmark/providers.py` to configure a mock experiment’s total requests, per-request retries, output limit, total tokens and monetary ceiling. Prices are caller-supplied integer microdollars per million tokens. The default monetary ceiling and rates are zero. Billable simulations require explicit opt-in plus configured rates. A personal-data simulation requires a separate opt-in. No handler can transmit personal data during Phase 5.

Dry-run mode serializes the request and returns a worst-case mock reservation against the configured ceilings. It has no mock dispatch or ledger write. The mock input bound uses the serialized byte count plus fixed framing. A future live driver would require model-specific input accounting and separately approved rates.

The private SQLite ledger reserves worst-case tokens and cost before dispatch. Completed responses are keyed by the canonical request fingerprint and returned on resume without dispatching again. An attempt explicitly known to be unsent can retry within the per-request and total-attempt limits. An ambiguous outcome retains its reservation and blocks automatic retries for that request. The ledger records the returned model, reported usage, simulated charge and actual zero API cost separately. Pass a dedicated `--ledger` file to `worker.py` to test a durable resume for one packet. The bundled demo uses temporary ledgers to keep independent passes independent.

## Future paid protocol

A future paid experiment requires owner review of the proposed dataset and disclosure, provider and model identifier, request count, independently verified token budget and current rates, expected cost range, maximum authorized cost, retry policy, and benchmark method. Use synthetic inputs by default. Personal data requires authorization for the particular transfer. A later live integration should use an environment variable or secret manager for credentials, with credentials kept out of repositories and ledgers. Completion of this mock workflow grants no permission to make a paid request.
