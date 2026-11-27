# TYR Brain Lab research integration

Phase 4A exercises a host-side inference broker with public synthetic observations and mock responses. The deterministic reference is the published v0.3.0 evidence-aware worker at `ff5ec53`. The portable SQLite projections, nine Brain tables, separate Lab, existing benchmark and isolated runner retain their v0.3.0 behavior. The research ledger is separate from both the records and Brain Lab databases.

## Run offline

From the repository root, with Python 3.10 or newer and SQLite 3.41.0 or newer:

```sh
python3 -B benchmark/research/run.py --dry-run
research_dir=$(mktemp -d)
python3 -B benchmark/research/run.py --workspace "$research_dir"
python3 -B benchmark/research/run.py --workspace "$research_dir"
```

The first command stages the same public fixtures temporarily and reports request size and conservative reservations. The next two commands use a private SQLite ledger and produce the same completed schedule. The 24 runs cover three arms on eight cases. Mock predictions and simulated usage exercise the machinery. They do not measure model quality or real tokenization. `research.sqlite` contains normalized submissions, tool metadata and simulated accounting. The evaluator can pass the `submission` objects to existing scoring version 2 after inference, with the separately generated public labels. Provider accounting is outside the submission wrapper so it can be audited separately.

| Arm | Phase 4A implementation | Input and limits |
| --- | --- | --- |
| A | v0.3.0 evidence-aware reference | Same case and task. Read-only local access to the SQLite projection and deterministic calculations. |
| B | Interpretation | Fixed numeric observation packet and task. One structured Responses request, no functions. |
| C | Tool-assisted interpretation | The same starting packet and task, with a choice of one typed investigation. A second structured request is permitted only after a validated tool call. |
| D | Proposed verification pass | Defer until public experiments establish a useful critic protocol and sufficient budget. |

The full-precision record values, assigned civil dates and case-local reference IDs are rendered into bounded JSON arrays. Snapshot columns carry numeric weight, caffeine and workout observations. Sleep columns carry the next-wake civil day, duration and clock minutes. Missing values remain null. A has native SQLite and deterministic method access. B and C receive the same scoped projection with no owner or source metadata. C receives additional computed evidence only for its selected target. These differences are part of the intervention being measured.

## Model-facing tools and results

The tool contract is `research-tools-v1`. Both operations take exactly one `target` from `window_1`, `window_2`, `window_3` or `weight`. The broker sets the assigned dates.

- `coverage` reports expected days and weight observations or eligible sleep pairs, timing-arm counts and exclusion counts using the existing Brain Lab rules.
- `evaluate` adds the existing v0.3.0 evidence-aware finding and row references for that target. The relationship method can check the other assigned windows of the same case for common support. Its result returns the selected target only.

Receipts retain the tool version, method, operation, target, measurements, dates, unit, outcome and supplied evidence. The model-facing `tyr_model_prediction_v2` schema defines separate branches for decisive and inconclusive results. It enforces effect thresholds and nullability, restricts change dates to those bracketed by observations, and uses one boolean flag per confounder. The broker supplies the case ID, version and claim types when it translates accepted output into the existing v1 benchmark prediction. The scorer and deterministic arm use that same v1 contract.

The packet's `witnesses` field lists case- and target-specific evidence IDs built from observations. A sleep ID binds one eligible earlier pair and one eligible later pair. A weight ID binds the first and last eligible weight observations in the assigned window. These references establish traceability and date coverage for the selected rows. They do not establish the effect or the adequacy of the full sample. The model selects the target's ID for a decisive finding or uses null for an inconclusive finding. The broker expands only an exact matching ID and validates the resulting in-window references. It rejects invented or cross-target IDs and malformed predictions. A tool's original references stay in its local receipt. The model sees the tool result and uses the same packet IDs as the direct interpretation arm.

The broker marks a missing model effect as `unavailable` and an independent effect as `model_estimate`. When the tool supplies no effect, an independent estimate keeps that label and must pass the usual evidence and threshold checks. When the tool supplies an effect, a submitted number must match within 0.01 of the relevant unit and use the same weight split where applicable. The broker then marks it `matches_tool`. The model's interpretation remains distinct from the calculation. No free text enters the submissions. The preset task captures reassessment through the sequence of the three relationship windows. This phase writes no persistent Brain findings.

## Trust boundary

The trusted controller regenerates public fixtures in a new owner-only temporary workspace. Its argument surface provides no packet path, user data, arbitrary prompt, model ID or provider URL. The packet builder reads the generated, hash-bound records through Brain Lab's read-only source access. Shape and hash checks complement provenance from the generator. A matching application ID, owner number or externally supplied hash alone would not establish synthetic provenance.

The controller hands only case-local projection data to the adapter. The generator's evaluator sibling is never read by the broker. Any future evaluator handoff needs trusted admission bindings, separate permissions and a review of the exact outgoing bytes. The current generator and broker run under the same trusted host account. The code boundary protects against model-directed access to the directory, not against arbitrary code already running as that account.

The VM is neither a client nor a proxy for the host broker. No runner launch, guest, filesystem, or network policy changes are required. The provider can return a prediction or request one of two fixed local operations. It cannot supply a path, filename, connection, SQL statement, arbitrary date, case ID for a tool, or remote tool. Unknown tools, malformed arguments, multiple calls and calls in unapproved stages are rejected. All model-controlled text and opaque reasoning are discarded after validation. A valid tool result is reconstructed into a fresh stateless request. Replaying provider-controlled items or opening a provider conversation would enlarge the boundary.

The OpenAI SDK path constructs foreground `/v1/responses` requests with `store=false`, disabled input truncation, Standard processing, low reasoning effort, strict schemas and a 2,000-token maximum that includes reasoning. It uses a fixed HTTPS endpoint, no environment proxies or redirects, and no HTTP retries. The offline launcher accepts only the in-memory mock transport. The separate `smoke.py` launcher requires positive experiment authorization, reads an owner-only project credential file outside the checkout, and binds a fresh ledger to the one-case live schedule. The SDK path is also tested through in-process mock HTTP.

The ledger keeps request digests, validated results, usage, returned model, response identifiers, versioned settings and source digests. It does not retain raw transcripts, reasoning, keys, or error text. Mode 0600 protects the ledger in an owner-only workspace. The owner controls retention and deletion. Exact local scoring can be replayed from retained submissions and admitted fixtures. Fresh cloud responses can differ even with a pinned snapshot. OpenAI's default abuse monitoring may retain request content for up to 30 days. `store=false` controls Responses application state. [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data)

## Budget model

The broker reserves the published full 400,000-token context window as input at the uncached price, plus the entire requested output limit, including reasoning. Each request is also limited to 48,000 serialized bytes. A separately approved smoke launch covers one synthetic case, the deterministic arm and the tool-assisted arm. It permits at most two provider requests, one tool iteration and zero retries under a $0.65 ledger cap. Two requests capped at 2,000 output tokens reserve $0.618000.

The `--higher-output-cap` variant reserves 512 output tokens for C's tool selection and 3,900 for its final response, for a maximum reservation of $0.619854. The ledger binds the cap to each stage. The historical eight-case live comparison would reserve $7.499232 with these full-context rates and also exceeds the per-case limit. Its live entry points reject the schedule before reading a credential or dispatching. Its offline mock and saved-result workflows remain available. Historical costs describe the usage recorded at the time. Confirm the applicable Global Standard tariff, project and credit eligibility at a separately authorized live gate.

An immediate SQLite transaction persists the reservation before dispatch. The one-pending-request rule serializes concurrent controllers. Pending requests, even if the process stopped before sending, remain fully reserved and prevent another dispatch. Valid usage settles against conservative uncached pricing even on a refusal or rejected prediction. Missing or over-reservation usage, unexpected model or tier, and uncertain transport outcomes keep the full reserve and latch a stop. Budget exhaustion also latches a stop. No automatic retry is allowed. A resumed schedule reuses settled stages with exactly matching envelopes and never resends them. Pending or uncertain entries require owner reconciliation before starting a new authorized experiment. The cap covers only the approved controller and ledger, so use a dedicated project key and prohibit other sessions from spending against the same authorization. [OpenAI pricing](https://developers.openai.com/api/docs/pricing) · [GPT-5.4 mini limits](https://developers.openai.com/api/docs/models/gpt-5.4-mini)

## Secure project preparation on macOS

1. In the API Platform, switch to the organization that holds the promotional credits. Create a dedicated **TYR Brain Lab** project. Check project and credit eligibility, billing currency, expiration and data controls in that organization. Keep automatic recharge off. Set conservative project alerts and limits in addition to the application budget.
2. Create a project-scoped key for the trusted host process. Use restricted permissions for Responses inference and limit model access to the approved configuration where supported. Keep the key out of chat, terminal arguments, shell startup files, repo files and VM environments.
3. In Keychain Access, create a generic password item in the login keychain. Use service `TYR Brain Lab OpenAI API`, your macOS short username as the account, and the project key in the password field. Clear the clipboard after saving. Confirm access only for the trusted launcher.
4. After separate live approval, the reviewed launcher should invoke `/usr/bin/security find-generic-password -w -s 'TYR Brain Lab OpenAI API' -a "$USER"` with stdout captured privately. Pass the value as `OPENAI_API_KEY` in only the approved broker process environment. Do not run the retrieval command by itself, echo or export the secret in a persistent shell, use shell tracing, or inherit that environment into evaluator or worker processes. Keep SDK debug logging disabled. [API project settings](https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform) · [Key safety](https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety)

The optional SDK requirements can be installed into a disposable virtual environment. The standard offline benchmark and broker test suite need no SDK or credentials. With the SDK installed, the research tests exercise its request serialization and no-redirect, no-retry transport using a fake key and in-process mock. [Official Python SDK](https://github.com/openai/openai-python)

## Review proposal for 4B and 4C

Prices checked on 2026-11-26, USD per million tokens, global Standard and uncached input. Availability in the intended project is unverified.

| Option | Exact API ID | Input / output | Research use |
| --- | --- | --- | --- |
| Economical and pinned | `gpt-5.4-mini-2026-03-17` | $0.75 / $4.50 | Historical first comparison. Low reasoning, with the output cap frozen per stage. 400,000 context and 128,000 maximum output. |
| Lower tariff alternative | `gpt-6-luna` | $0.10 / $0.50 | Later if lower cost matters more than a dated snapshot. The docs list the same ID as the current snapshot. |
| Stronger reasoning candidate | `gpt-6.2-sol` | $2.00 / $10.00 short context | Later comparison. Assess low or medium reasoning and cost before approval. The docs do not list a separate dated snapshot. |

All three document Responses, function calling and structured output support. Luna and Sol document 1,050,000-token context and 922,000 maximum input, with higher long-context pricing. Those limits are unnecessary for this pilot. [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) · [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) · [GPT-6.2 Sol](https://developers.openai.com/api/docs/models/gpt-6.2-sol) · [Standard rates](https://developers.openai.com/api/docs/pricing)

**4B smoke scope.** A separately authorized launch covers the deterministic A arm and C on one admitted public case. C receives one required function selection request and, after valid tool execution, one tool-free final request. Stop on any uncertainty and after this schedule. Use mocks for failure testing. The historical live smoke also ran B before the input reservation policy was enlarged.

At 7,000–13,000 input tokens and 500–1,500 output tokens per request, two requests would cost an estimated $0.015–$0.033 before cache savings. The ledger reserves the full-context worst case described above. It does not use expected spend for admission.

**4C proposal.** After reviewing 4B, first qualify a harder public development set offline. The eight starter cases yielded 24/24 correct relationship windows, 6/8 weight cases and 8/8 legacy reassessment classifications for A, with two positive reassessments in the supported-to-not-supported direction. Keep these cases for integration checks. Use a public set with both reassessment directions, coverage traps, mixed regimes, null controls and weight changes. Verify headroom and use exact reassessment transitions before selecting eight balanced public cases for a paired A–C development pilot. Assign the same windows in all arms. Include recovery, false positives and negatives, appropriate abstentions, unsupported causality, valid evidence, numerical consistency, confounding, coverage, tool selection and operational failures. Report all scheduled results, costs per completion and correct finding, and reason-coded failures. Separate refusal, timeout, transport ambiguity and budget denial from insufficient evidence, invalid references and numerical discrepancies. Prespecify a small repeated subset only if it fits a separately approved allocation. Use descriptive uncertainty for this development sample. Avoid comparative rankings or claims of independent validation.

**4D gate.** Review headroom and baseline errors by family before freezing prompts, model settings, tools, observations, eligibility, scoring, budgets, retry rules, replication and uncertainty. Use a separate evaluator with no access path from the provider worker. Review a bounded provenance mechanism for new synthetic cases, since the current broker admits only regenerated public fixtures. Treat cloud repeat results as replications with preserved provenance. Open-ended discovery, criticism, broader scenarios and longitudinal knowledge across successive exports are separate research decisions.

## Verify the approved Phase 4C batch offline

Run from the checkout with the reviewed public admission manifest and its eight packet directories. Use a fresh, ignored results directory outside the checkout and packet root.

```sh
python3 -B benchmark/research/batch.py \
  --manifest /path/to/pilot-admission.json \
  --packets /path/to/pilot-packets \
  --workspace /path/to/new-results-directory
```

The launcher pins the reviewed manifest digest and opaque case order. It checks the exact directory layout, task and SQLite fingerprints, and the compiled observation digests before dispatch. It copies the approved files into temporary read-only staging for analysis. Evaluator labels, selection reasons, and baseline scores stay outside the admitted packets. The default batch mode uses in-memory mocks.

C's 512-token selection turn can call one allowlisted local tool for one target, or return the exact JSON `{"action":"skip"}` under `tyr_tool_selection_v1`. Either valid choice unlocks one 3,900-token final request. On skip, that request matches B's. After a tool call, the request also includes the sanitized result. A malformed selection leaves the final stage unrun.

The eight-case mock ledger binds the scheduled stages, a 24-request maximum, zero retries, and the historical caps. It records every scheduled stage and exercises budget denial without sending requests. With full-context usage, the per-case $0.65 limit stops the first fully charged case after two requests totaling $0.619854. The CLI requires a fresh workspace.

The retained historical live flag fails preflight before credential access. Saved live receipts distinguish input, cached input and output usage for historical billing estimates. Scoring remains an evaluator-side operation.

## Phase 4C sleep remediation

Add `--offline-remediation` to the mock batch command and use a fresh workspace. The launcher verifies the original admitted packets before deriving `observation-packet-v3` and recording its digests. Both model arms receive the same sleep summary. The original packets and live run stay available for comparison. This mode blocks live transport.

The retained remediated live flag also fails the full-context preflight. The recorded historical remediated run used v3 packets. Offline verification continues to check those inputs.

The shared summary covers the three assigned sleep windows. It reports civil-window opportunities, eligible earlier and later caffeine pairs, date coverage, mean sleep duration, and signed later-minus-earlier contrasts in minutes. It also reports contrasts for shared training/weekend strata within each window, with support limits. Missing estimates are null. These are observed-data summaries without decision labels.

The final prompt makes the benchmark rule explicit. Assess the windows individually, then compare consecutive decisive decisions chronologically. An inconclusive middle window can leave its two decisive neighbors as the transition endpoints. The scorer and A's deterministic method retain their existing rules.

C's new optional `reassess_sleep` call accepts only the `sleep_reassessment` target. One call returns the three assigned windows, comparable contrasts using the same available strata across windows, leave-one-14-day-block-out ranges, and fixed-third contrasts with counts and matched support. A missing range or contrast indicates insufficient comparable input for that calculation. The ranges are sensitivity diagnostics. The tool gives the model measured contrasts, without verdicts or evaluator data. The selection prompt prioritizes reassessment while retaining the weight tools and typed skip. This analysis stays within the existing tool-result and request size limits.

## Offline window stability qualification

Use `batch.py --offline-stability` with the reviewed public pilot manifest, its packet directory and a fresh workspace. This mock-only mode uses `observation-packet-v13`, `paired-sleep-summary-v6`, `fixed-target-prompt-v11` and `tyr_tool_selection_v7`. The ledger records packet digests, analytical method versions, and cases with host-selected sleep. B and C receive the same endpoint and weight evidence. C can receive detailed per-third counts and comparable estimates across windows using the sleep tool.

The diagnostic starts with the existing whole-window support checks for coverage and matched timing groups. When those pass, it uses three fixed calendar segments with at least ten earlier and ten later pairs per segment and at least six per timing group in strata shared across all three segments. To flag a mixed window, both the raw and matched contrasts must extend to at most −18 and at least −12 minutes and each span at least 12 minutes. The three-minute margin on each side of −15 minutes is a screening parameter. The threshold for a supported prediction is −15 minutes. Contrast units are later minus earlier sleep minutes. Consistently small contrasts can support a `notSupported` decision when the evidence is adequate.

The shared `endpoint_support` object reports the whole-window coverage check, matched estimate and leave-one-14-day-block-out sensitivity range. A passing coverage check warrants evaluating the evidence. Estimates near the decision threshold, threshold-sensitive ranges and conflicting evidence can justify abstention. A missing range indicates insufficient information for that sensitivity calculation.

The separate `stability_screen` object records availability and a result only when the screen runs. An unavailable screen due to thin or poorly matched thirds leaves the endpoint coverage check independent. The `clustered-threshold-v1` check requires at least two eligible windows and every eligible matched estimate within three minutes of −15. It lists just those windows in `clustered_threshold_windows`. A clearly separated endpoint prevents the cluster rule from suppressing a potentially meaningful contrast with a borderline endpoint.

The structured schema permits only `inconclusive` if whole-window coverage fails, the screen detects mixing, or the window is part of a near-threshold cluster. The broker records a conflicting response as `required_window_abstention`. Compare consecutive decisive endpoints after applying these gates. All evidence and flags derive from the admitted observations.

A decisive sleep result names an `estimate_method` and uses that value, its threshold-consistent decision, and the window's evidence ID. Under `shared-strata-precedence-v1`, final requests include a `sleep_decision_basis` for each window. B, C after a skip or weight tool, and unflagged endpoints retain the `whole-window-matched-v1` default, subject to the existing abstention gates. When C runs `reassess_sleep`, any window listed in `tool_routing.sleep_review_windows` uses `across-window-matched-v1` for a decisive result if it includes at least ten pairs per timing group, retains at least half the paired observations, and its estimate and block-deletion range lie on the same side of −15 minutes (including equality on the supported side). A flagged comparison with inadequate common support, a missing range, or sensitivity to the threshold requires abstention. A tool result leaves the existing abstention gates in force.

The broker records the method in numerical provenance. It rejects conflicting estimates as `ungrounded_sleep` and decisive findings for abstention-only windows as `required_window_abstention`. An inconclusive result remains available and carries null effect, evidence and method. Raw differences remain descriptive. The scorer receives the existing prediction shape.

`grounded-weight-v1` supplies a shared calculation in kilograms. It starts with the published v0.3.0 evidence-aware result. When that result abstains, a second drift-aware method can nominate a step of at least 2 kg. Acceptance also requires at least 12 observations on each side in the nearest 28 days, observations close to the split and a same-direction local median shift of at least 2 kg. A decisive result binds the decision, effect, split and evidence exactly to the calculation. Step witnesses refer to weight rows near the split. A grounded `no_change` carries a null effect and split. B can use the computed decision or abstain.

C may use its one tool call to evaluate weight. The host checks the nominated split with a linear drift plus step fit on the nearest 42 days per side and repeats it while omitting one fixed seven-day block at a time. `local-weight-step-v1` challenges the nomination for inadequate local coverage, when all local fits fall short of the 1 kg cutoff in the nominated direction, or when both the grounded estimate and local lower sensitivity bound are below 1.5 kg. A sensitivity range that crosses 1 kg can be recorded as a warning on a stronger grounded result. These are reproducible checks on the same observations.

C must retain the grounded decision unless the weight tool challenges the same split. A challenge requires `inconclusive` with null effect, date and evidence. Skipping, choosing a sleep tool, or asking only for weight coverage leaves the grounded decision in force. The schema and broker enforce the arm's available decision. The tool receipt stores the local range, counts and reason, and the broker records a conflicting prediction as `weight_verification_conflict`.

C can use one investigation across both domains. Use `reassess_sleep` for comparable sleep effects or `evaluate` with the `weight` target for verification of the nominated step. Coverage is available for an assigned target. The final stage offers no further tools.

`cross-window-support-v1` lists the timing strata shared across the assigned windows, the local matched pair count, the retained earlier and later counts, and locally matched strata that drop out of the shared comparison. A change is material when it drops at least 20% of locally matched pairs while retaining at least ten pairs per timing group and half of the window's eligible pairs. The cue describes support from the observed rows. The across-window effect and sensitivity range still come from the sleep tool.

`mixed-tool-routing-v3` gives exact sleep reassessment priority in the one-tool pilot. The sleep cue applies when at least two endpoints are eligible and one has a material change in matched support. The weight cue applies when a nominated step is below 1.5 kg in absolute magnitude. When both cues apply, the broker runs the sleep tool directly and records `host_selected_sleep`. C receives the receipt in its final request, with no provider selection request, and the grounded weight default stays in force. A sleep tool failure ends that run with `tool_failure`. When exactly one cue applies, the broker recommends the corresponding tool. With neither cue, it recommends skip. In these cases C can still select any eligible tool or skip. Report host routing and model-selected actions separately, alongside separate sleep and weight outcomes.

### Sleep-only preparation

[`sleep_only.py`](sleep_only.py) compiles `sleep-only-observation-v1` and `sleep-only-request-v1` for in-memory mock qualification. The packet contains exactly three assigned caffeine–sleep windows, projected daily rows, window evidence IDs, computed sleep summaries and a sleep-only route. C receives an optional host sleep receipt when at least two endpoints are eligible and an eligible endpoint has a material change in matched support. B receives the same packet and a whole-window decision basis. C receives the applicable shared-strata decision basis. Both arms submit only the three sleep decisions.

`sleep-threshold-comparator-v1` uses the exact eligible threshold evidence in the same request C receives. The local scorer's inactive weight field is added after validation for legacy compatibility. The sleep-only adapter accepts only the in-memory mock transport. The public Phase 4C launch admission remains separate.

[`sleep_local.py`](sleep_local.py) prepares the separate, mock-only `sleep-only-observation-v2` contract. C's eligible estimate is `within-period-dose-matched-v1`. It matches exact recorded doses within 28-day periods and the applicable training and weekday strata. It requires at least two periods with four matched observations per timing arm and agreement on the threshold side across supported periods. The existing sleep gates apply. Every decisive result must use the exact calculation and its host-created witness drawn from matched observations. A window with inadequate support or conflicting period estimates must abstain. A qualified window can still be marked inconclusive based on its observed context. The deterministic comparator uses the same eligible estimates and evidence sent to C.
