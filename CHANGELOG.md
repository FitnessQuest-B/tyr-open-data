# Changelog

## 0.4.0 release candidate

- Added an experimental host-side Responses API adapter with an optional SDK, reviewed public synthetic input scopes, structured predictions, evidence validation, bounded tools and a local request ledger.
- Added offline mock and replay workflows for deterministic, model-only and tool-assisted experimental arms. The SQLite specifications, offline benchmark and isolated runner retain the v0.3.0 interfaces.
- Reserved the full published model context plus bounded output before any dispatch. Reduced the prospective live smoke schedule to two requests and made the historical eight-case batch offline-only under its existing caps.
- Documented preliminary public experiments in which the host-routed sleep arm recovered six exact reassessments. A deterministic replay with equivalent evidence matched its sleep results. The tool-assisted arm missed all 12 intended weight abstentions in that selected pilot.
- Deferred private Phase 4D validation. The latest public synthetic panel left no measured headroom once the same-evidence deterministic comparator included a weekday check. The comparison leaves open how models prioritize and select worthwhile investigations across domains.

## 0.3.0

- Added an experimental benchmark worker that checks local weight coverage and uncertainty before calling a step, and checks temporal stability before deciding a relationship window.
- Added a 120-case verification suite and a paired comparison against the published v0.2.0 worker, with separate acceptance gates for weight abstention and exact reassessment.
- Switched benchmark VMs to direct Linux boot with pinned boot artifacts and bounded startup diagnostics.
- Added a calibrated 96-case reassessment suite with uneven mixed windows, moderate adjacent changes and matched controls.

## 0.2.0

- Added an experimental offline benchmark for external agents with a CPU-only Linux arm64 supervisor, a disposable VM per case, rootless OCI execution and bounded outputs.
- Added tooling for a private 48-case synthetic pilot with varied layouts, audited evidence adequacy and case-level diagnostics.
- Added bounded runner readiness checks, stage-specific failure receipts, a drift-aware experimental weight detector, and audited reassessment coverage in both directions.

## 0.1.0

- Defined 32 read projections for TYR application schema v92.
- Added blank SQLite creation and separate Brain Lab schema artifacts.
- Added standalone compatibility checks for fresh and upgraded v92 exports, with explicit limited coverage for routed health data.
- Documented all v92 projections, measurement semantics and the nine Brain tables.
- Added agent instructions and verified read-only SQLite and Python examples.
- Added four configurable synthetic subjects, deterministic SQLite generation and separate agent and evaluator packages.
- Added offline Brain Lab analysis, isolated persistence, source fingerprinting, evidence replay and a Markdown review workflow.
- Added held-out offline benchmark scoring, detached worker packets, and OpenAI Responses and local JSON adapters tested with mock responses.
- Added effect and evidence requirements to benchmark scoring version 2 and set the supported SQLite floor to 3.41.0.
