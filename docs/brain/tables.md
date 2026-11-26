# Brain table dictionary

TYR Open Data 0.1.0 Brain Lab schema. The [Brain contract](README.md) describes relationships, integrity and implementation limits. All timestamps below use Unix seconds. SQL defaults, complete checks and foreign-key actions are in the [versioned DDL](../../schema/versions/0.1.0/brain-lab.sql).

## `brain_hypothesis`

One registered hypothesis definition. Semantic revision advances the definition version. Prospective revisions require fresh registration. Earlier evaluations keep their frozen definition. An archive or revision can invalidate the current assessment.

Primary key is `id`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `uuid` | `TEXT` | No | Unique lowercase UUID-shaped identifier. TYR creates v4 UUIDs. The SQL shape check does not enforce v4 version bits. |
| `title` | `TEXT` | No | Nonblank short hypothesis label. |
| `statement` | `TEXT` | No | Nonblank testable claim or question. |
| `domain` | `TEXT` | No | Nonblank domain label. |
| `hypothesis_type` | `TEXT` | No | Design category `intervention`, `association` or `descriptive`. |
| `claim_type` | `TEXT` | No | Requested claim level `descriptive`, `association` or `causal`. |
| `origin_type` | `TEXT` | No | Provenance class `user`, `observation`, `imported` or `unknown`. |
| `origin_ref` | `TEXT` | Yes | Optional source reference. The schema declares no foreign key for it. |
| `registered_at` | `INTEGER` | No | Registration instant of this definition, in Unix seconds. |
| `registration_mode` | `TEXT` | No | Timing class `prospective`, `retrospective`, `mixed` or `unknown`. |
| `definition_version` | `INTEGER` | No | Positive integer revision of the registered definition. |
| `created_at` | `INTEGER` | No | Creation instant in Unix seconds. |
| `updated_at` | `INTEGER` | No | Most recent update instant recorded for this row, in Unix seconds. |
| `archived_at` | `INTEGER` | Yes | Archive instant in Unix seconds. NULL indicates the row has no archive timestamp. |

## `brain_hypothesis_metric`

Binds a hypothesis to a declared, registered metric and role. The binding records an analytical intent. It does not evaluate a condition or fit a model.

Primary key is `id`.

Declared foreign keys include `(hypothesis_id)` → `brain_hypothesis(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `uuid` | `TEXT` | No | Unique lowercase UUID-shaped identity for this Brain object. The application generates v4 UUIDs. |
| `hypothesis_id` | `INTEGER` | No | Local identifier of the linked hypothesis. |
| `metric_key` | `TEXT` | No | Key from the enforced TYR canonical metric registry. |
| `role` | `TEXT` | No | Declared role `exposure`, `outcome`, `confounder`, `modifier` or `context`. |
| `window_days` | `INTEGER` | Yes | Optional positive number of days for the binding’s window. |
| `lag_days` | `INTEGER` | Yes | Optional lag in days. Define the sign and alignment in the analysis specification. |
| `condition_spec_json` | `TEXT` | Yes | Optional v1 JSON envelope for a condition. A portable interpretation language is outside the contract. |
| `created_at` | `INTEGER` | No | Creation instant in Unix seconds. |

## `brain_hypothesis_intervention`

Binds a hypothesis to a whole intervention or to one of its periods. Existence, period ownership and duplicate broad or period bindings are enforced in the sidecar. The association supplies intended analysis context.

Primary key is `id`.

Declared foreign keys include `(hypothesis_id)` → `brain_hypothesis(id)`, `(intervention_id)` → `interventions(id)`, `(intervention_period_id, intervention_id)` → `intervention_periods(id, intervention_id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `uuid` | `TEXT` | No | Unique lowercase UUID-shaped identity for this Brain object. The application generates v4 UUIDs. |
| `hypothesis_id` | `INTEGER` | No | Local identifier of the linked hypothesis. |
| `intervention_id` | `INTEGER` | No | Intervention identifier within this database. |
| `intervention_period_id` | `INTEGER` | Yes | Optional mirrored period ID. The composite foreign key requires the period to belong to the same intervention. |
| `relationship_role` | `TEXT` | No | The declared role `exposure`, `comparator` or `context`. |
| `created_at` | `INTEGER` | No | Creation instant in Unix seconds. |

## `brain_evaluation`

One executed test with a frozen specification, result and reproducibility metadata. The insert seals the evidence set. Selected maintenance paths can remove supporting links or purge the evaluation. Read an effect together with its design, uncertainty, coverage and stated claim level.

Primary key is `id`.

Declared foreign keys include `(hypothesis_id)` → `brain_hypothesis(id)`, `(supersedes_evaluation_uuid)` → `brain_evaluation(uuid)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `uuid` | `TEXT` | No | Unique lowercase UUID-shaped identity for this Brain object. The application generates v4 UUIDs. |
| `hypothesis_id` | `INTEGER` | No | Local identifier of the linked hypothesis. |
| `algorithm_id` | `TEXT` | No | Nonblank identifier of the evaluation algorithm. |
| `algorithm_version` | `TEXT` | No | Nonblank version of the evaluation algorithm. |
| `evaluation_mode` | `TEXT` | No | Declared `exploratory` or `confirmatory` execution mode. |
| `spec_registered_at` | `INTEGER` | No | Instant the specification was registered, in Unix seconds. |
| `test_window_start` | `INTEGER` | No | Evaluated window start in Unix seconds. Must precede its end. |
| `test_window_end` | `INTEGER` | No | Evaluated window end in Unix seconds. Must be at or before execution. |
| `executed_at` | `INTEGER` | No | Execution instant in Unix seconds. Must be at or after specification registration. |
| `spec_hash` | `TEXT` | No | 64 lowercase hex characters from SHA-256 of the canonical specification. |
| `specification_codec_version` | `INTEGER` | No | Version of the specification codec. The schema accepts 1. |
| `specification_json` | `TEXT` | No | Frozen canonical v1 envelope with the hypothesis definition, metric and intervention bindings, outcome definitions and analysis parameters. |
| `input_manifest_hash` | `TEXT` | Yes | Optional 64-character lowercase SHA-256 digest of input manifest material. Required for fingerprinted or replayable results. |
| `reproducibility_level` | `TEXT` | No | Declared `specification`, `fingerprinted` or `replayable` level. A digest can verify an input identity supplied later. |
| `supersedes_evaluation_uuid` | `TEXT` | Yes | Optional UUID of a predecessor for the same hypothesis with earlier or equal execution time. |
| `primary_metric_key` | `TEXT` | No | Canonical registry key for the primary metric assessed. |
| `effect_estimate` | `REAL` | Yes | Optional finite effect estimate. Its sign and scale depend on the stated test and unit. |
| `effect_unit` | `TEXT` | Yes | Unit for the effect or interval. Required when an effect or lower bound is present. |
| `interval_lower` | `REAL` | Yes | Optional finite lower bound. Bounds and method are supplied together. |
| `interval_upper` | `REAL` | Yes | Optional finite upper bound. Must be at or above the lower bound. |
| `interval_method` | `TEXT` | Yes | Method used to produce the interval, when present. |
| `interval_level` | `REAL` | Yes | Optional level on the interval scale, greater than zero and at most one. Requires interval bounds. |
| `sample_count` | `INTEGER` | Yes | Optional nonnegative count under the evaluation’s sampling rule. |
| `coverage_ratio` | `REAL` | Yes | Optional ratio from 0 to 1. The denominator belongs to the analysis specification. |
| `evidence_decision` | `TEXT` | No | Recorded `supported`, `notSupported`, `inconclusive`, `adverse` or `conflicting` outcome. |
| `result_claim_type` | `TEXT` | No | Reported `descriptive`, `association` or `causal` claim class. Causal declarations have additional metadata guards. |
| `failure_class` | `TEXT` | Yes | Optional `ineffective`, `adverse`, `insufficientData` or `methodLimitation` classification. |
| `limitations_code` | `TEXT` | Yes | Optional method or result limitation code. |
| `diagnostics_codec_version` | `INTEGER` | Yes | Version 1 when diagnostics JSON is supplied. |
| `diagnostics_json` | `TEXT` | Yes | Optional versioned object with algorithm-specific diagnostics. |
| `analysis_family_id` | `TEXT` | Yes | Optional logical grouping for related analyses or multiple comparisons. |
| `validation_method` | `TEXT` | Yes | Optional validation method label. A causal result requires a nonblank value and qualifying registration. |

## `brain_evaluation_evidence`

One aggregate or source descriptor for an evaluation, metric, role and cohort. The parent foreign key is deferred. Before the parent is inserted, evidence can be staged in the same transaction. A source reference identifies a particular intervention period only for its typed evidence kind.

Primary key is `id`.

Declared foreign keys include `(evaluation_id)` → `brain_evaluation(id)`, `(source_uuid)` → `intervention_periods(uuid)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `uuid` | `TEXT` | No | Unique lowercase UUID-shaped identity for this Brain object. The application generates v4 UUIDs. |
| `evaluation_id` | `INTEGER` | No | Parent evaluation ID. The foreign key is deferred until commit. |
| `metric_key` | `TEXT` | No | Canonical metric key being summarized. |
| `metric_role` | `TEXT` | No | Role `exposure`, `outcome`, `confounder`, `modifier` or `context`. |
| `cohort_role` | `TEXT` | No | Cohort label `baseline`, `exposure`, `comparator`, `followUp` or `other`. |
| `source_type` | `TEXT` | No | Evidence kind `dailySnapshot`, `rollingBaseline`, `measurement`, `interventionPeriod` or `aggregate`. |
| `source_uuid` | `TEXT` | Yes | Intervention-period UUID required for `interventionPeriod`. Other source types use NULL here. |
| `window_start` | `INTEGER` | No | Window start instant in Unix seconds. |
| `window_end` | `INTEGER` | No | Window end instant in Unix seconds. Must be later than the start. |
| `sample_count` | `INTEGER` | No | Nonnegative observed count. |
| `expected_count` | `INTEGER` | Yes | Optional positive expected count. Check the study’s definition before computing coverage. |
| `mean` | `REAL` | Yes | Optional finite mean in the canonical metric unit. |
| `standard_deviation` | `REAL` | Yes | Optional finite nonnegative SD in metric units, under the declared method. |
| `minimum` | `REAL` | Yes | Optional finite minimum. When all three exist, it bounds the mean from below. |
| `maximum` | `REAL` | Yes | Optional finite maximum. When all three exist, it bounds the mean from above. |
| `coverage_ratio` | `REAL` | Yes | Optional ratio from 0 to 1, distinct from percentage columns in the records schema. |
| `confidence_code` | `TEXT` | Yes | Optional source-native quality or confidence label. |
| `canonical_unit` | `TEXT` | No | Enforced registry unit for the stated metric. |
| `source_fingerprint` | `TEXT` | Yes | Optional source aggregate fingerprint. Replay requires inputs and the fingerprint convention. |
| `extra_codec_version` | `INTEGER` | Yes | Version 1 when extra evidence JSON is supplied. |
| `extra_json` | `TEXT` | Yes | Optional versioned object for evidence-specific detail and provenance. |

## `brain_assessment`

At most one current interpretation per active hypothesis. It is a replaceable projection over the latest compatible evaluation. A change to evaluation or hypothesis state can remove it. Use evaluation history for results across time.

Primary key is `hypothesis_id`.

Declared foreign keys include `(hypothesis_id)` → `brain_hypothesis(id)`, `(latest_evaluation_uuid)` → `brain_evaluation(uuid)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `hypothesis_id` | `INTEGER` | No | Primary key and foreign key of the assessed hypothesis. |
| `evidence_decision` | `TEXT` | No | Current `unassessed`, `supported`, `notSupported`, `inconclusive`, `adverse` or `conflicting` decision. |
| `claim_strength` | `TEXT` | No | Claim level `none`, `descriptive`, `association` or `causal`. |
| `applicability` | `TEXT` | No | Applicability `unknown`, `current`, `historical`, `recheckRequired` or `notApplicable`. |
| `failure_disposition` | `TEXT` | Yes | Optional `ineffective`, `adverse`, `insufficientEvidence` or `methodLimited` disposition. |
| `evidence_strength` | `TEXT` | No | Recorded `none`, `weak`, `moderate` or `strong` evidence grade. The policy determines its meaning. |
| `latest_evaluation_uuid` | `TEXT` | Yes | UUID of the latest compatible evaluation for this hypothesis. NULL corresponds to `unassessed`. |
| `policy_version` | `TEXT` | No | Nonblank version of the assessment policy. |
| `assessed_at` | `INTEGER` | No | Assessment instant in Unix seconds. |
| `review_reason_code` | `TEXT` | Yes | Optional justification or review code. |
| `validity_context_codec_version` | `INTEGER` | Yes | Version 1 when validity context JSON is supplied. |
| `validity_context_json` | `TEXT` | Yes | Optional v1 validity context. The trigger validates referenced live context event UUIDs. |

## `brain_context_event`

A recorded or inferred context interval. Use it to annotate possible competing explanations and changes in baseline. Certainty is separate from source. A context row can contain sensitive personal information.

Primary key is `id`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `uuid` | `TEXT` | No | Unique lowercase UUID-shaped identity for this Brain object. The application generates v4 UUIDs. |
| `context_type` | `TEXT` | No | Type `illness`, `travel`, `medicationChange`, `scheduleDisruption`, `lifestyleTransition` or `other`. |
| `started_at` | `INTEGER` | No | Start instant in Unix seconds. |
| `ended_at` | `INTEGER` | Yes | Optional end in Unix seconds, at or after the start when supplied. |
| `source_type` | `TEXT` | No | Source class `userReported`, `inferred`, `imported` or `unknown`. |
| `source_ref` | `TEXT` | Yes | Optional source reference. There is no declared foreign key for it. |
| `certainty` | `TEXT` | No | Recorded certainty `confirmed`, `reported`, `inferred` or `unknown`. The schema checks compatibility with source class. |
| `notes` | `TEXT` | Yes | Optional sensitive context description. |
| `created_at` | `INTEGER` | No | Creation instant in Unix seconds. |
| `updated_at` | `INTEGER` | No | Most recent update instant recorded for this row, in Unix seconds. |
| `is_deleted` | `INTEGER` | No | Deletion flag, encoded as 0 or 1. The schema requires agreement with `deleted_at`. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |

## `brain_memory_node`

One knowledge note or source wrapper. A source wrapper resolves to an existing hypothesis, evaluation, or live context event and is unique for its typed source. It can be removed when the underlying source is removed.

Primary key is `id`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `uuid` | `TEXT` | No | Unique lowercase UUID-shaped identity for this Brain object. The application generates v4 UUIDs. |
| `node_type` | `TEXT` | No | Node kind `note` or `source`. |
| `source_entity_type` | `TEXT` | Yes | Wrapped type `hypothesis`, `evaluation` or `contextEvent`. Required only for source nodes. |
| `source_entity_uuid` | `TEXT` | Yes | UUID of the wrapped entity. The trigger resolves the typed reference and protects the provenance identity. |
| `title` | `TEXT` | No | Nonblank node title. |
| `summary` | `TEXT` | Yes | Optional text summary. It may contain interpretations and sensitive information. |
| `retrieval_tier` | `TEXT` | No | Classification `primary`, `secondary` or `archive` for a future retrieval policy. |
| `review_state` | `TEXT` | No | Review status `unreviewed`, `verified` or `stale`. Verified status requires a validation timestamp. |
| `summary_version` | `INTEGER` | Yes | Positive version paired with a non-null summary. |
| `last_validated_at` | `INTEGER` | Yes | Most recent validation instant, in Unix seconds, where supplied. |
| `created_at` | `INTEGER` | No | Creation instant in Unix seconds. |
| `updated_at` | `INTEGER` | No | Most recent update instant recorded for this row, in Unix seconds. |
| `archived_at` | `INTEGER` | Yes | Archive instant in Unix seconds. NULL indicates the row has no archive timestamp. |

## `brain_memory_link`

One typed edge between two distinct memory nodes. Direction matters except for the symmetric `contradicts` and `relevantTo` kinds. An edge records a relationship asserted by a writer. Its label does not validate the underlying evidence.

Primary key is `id`.

Declared foreign keys include `(from_node_id)` → `brain_memory_node(id)`, `(source_evaluation_uuid)` → `brain_evaluation(uuid)`, `(to_node_id)` → `brain_memory_node(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `uuid` | `TEXT` | No | Unique lowercase UUID-shaped identity for this Brain object. The application generates v4 UUIDs. |
| `from_node_id` | `INTEGER` | No | Local ID of the source node. |
| `to_node_id` | `INTEGER` | No | Local ID of the target node. |
| `relation_type` | `TEXT` | No | Kind `supports`, `contradicts`, `refines`, `dependsOn`, `relevantTo`, `supersedes` or `derivedFrom`. |
| `source_evaluation_uuid` | `TEXT` | Yes | Optional evaluation UUID giving the provenance of this edge. |
| `is_active` | `INTEGER` | No | Stored 0 or 1 flag for the current edge state. |
| `link_version` | `INTEGER` | No | Relationship vocabulary version. The schema accepts 1. |
| `created_at` | `INTEGER` | No | Creation instant in Unix seconds. |
