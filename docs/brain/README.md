# TYR Brain v92 contract

The separate Brain Lab database exposes nine Brain tables with selected portable v92 integrity rules. The [table dictionary](tables.md) covers the columns and relationships. The [schema](../../schema/versions/0.1.0/brain-lab.sql) defines defaults, enums, checks, indexes and trigger behavior.

## Record lifecycle

| Layer | How to read it |
|---|---|
| Hypothesis and bindings | `brain_hypothesis` captures a registered definition. `brain_hypothesis_metric` declares metric roles and `brain_hypothesis_intervention` links interventions or specific periods. Registration records design intent and timing. |
| Evaluation and evidence | `brain_evaluation` stores a frozen execution record. `brain_evaluation_evidence` stores cohort and provenance summaries attached by evaluation ID. A UUID predecessor can link a later evaluation to an earlier one on the same hypothesis. |
| Current assessment | `brain_assessment` projects the latest compatible evaluation onto the active hypothesis under a named policy. It is a current view of evidence, applicability and claim strength. It has no assessment-history table. |
| Context and knowledge | `brain_context_event` records contextual intervals with source and certainty. `brain_memory_node` stores notes or typed source wrappers. `brain_memory_link` connects two nodes and can cite a producing evaluation. |

There are two supporting identity relations inside the Lab file. `interventions(id, uuid)` and `intervention_periods(id, intervention_id, uuid)` mirror just enough identity for declared foreign keys. The period’s intervention must match the binding. Lab constraints operate inside one file. A separate records export remains a separate source.

## Evaluations and integrity

- Eight Brain tables have a local integer ID and unique UUID-shaped text. The assessment uses the hypothesis ID as its primary key. Brain objects do not carry a general owner key. Bind findings to a specific subject and export in any later Lab workflow.
- Brain v1 canonical JSON keeps array order and uses UTF-16 key ordering and Dart number serialization. The specification digest is SHA-256 of the encoded UTF-8 envelope. Plain SQLite supports reads. Evaluation insertion requires the matching `tyr_brain_specification_valid` function on the trusted writer connection. The offline Lab registers a portable validator for the signed-integer JSON subset its typed writer emits. Numeric SQL effects remain REAL values. Floating-point numbers inside Brain JSON and unverified encodings are rejected.
- Evidence staging uses a deferred evaluation foreign key. An evaluation insert seals the associated evidence. Evaluation and evidence contents are protected against ordinary updates. Deleting evidence or an intervention identity can invalidate or purge dependent results. App source-erasure hooks for workout and health inputs are outside the portable sidecar.
- The evaluation stores the spec, window, effect, optional interval and reproducibility declaration. The hypothesis definition and other declared references can be checked when it is inserted. A hash can identify evidence; replay depends on retaining suitable inputs and a runnable method. A coverage ratio is 0–1. Read the evaluation’s denominator definition.
- Causal-result declarations require qualifying prospective registration, a confirmatory evaluation and additional validation metadata. These are storage guards. A causal interpretation still depends on study design and competing explanations.
- Source wrappers point to a hypothesis, evaluation or live context event by type and UUID. Removal or retirement of a context source can invalidate dependent state. The link vocabulary provides direction and provenance. A link caption or review grade carries the writer’s claim.

## Knowledge link direction

| Stored relation | Meaning from source to target |
|---|---|
| `supports` | The source supplies evidence in favour of the target. |
| `contradicts` | The connected findings conflict. Either node can be the source. |
| `refines` | The source narrows or qualifies the target. |
| `dependsOn` | The source requires the target as a prerequisite. |
| `relevantTo` | The two nodes provide context for each other. Either node can be the source. |
| `supersedes` | The source replaces the target for a stated purpose. |
| `derivedFrom` | The source was derived from the target. |

## Decisions and changing evidence

| User-facing state | Stored value |
|---|---|
| Supported | `supported` |
| Not supported | `notSupported` |
| Unsure | `inconclusive` |
| Awaiting evidence for a current assessment | `unassessed` |
| Other stored outcomes | `adverse` and `conflicting` |

A failed hypothesis can be retained as an evaluation with coverage, limits and any contrary evidence. If the person or measurement changes, preserve earlier evaluations while representing present applicability separately. A subsequent evaluation can supersede an earlier one. Current assessment rows can be invalidated by definition, binding or evaluation changes. Historical retention remains subject to owner-directed evidence removal.

## Implemented behavior and Lab policy

The private v92 source contains an observational intervention comparison and a transactional save service. The service uses a previously registered hypothesis and declared bindings, matches eligible baseline and exposure days, and saves a descriptive, exploratory, fingerprinted result as `inconclusive`. It does not produce an assessment. The audit found no mobile workflow calling these services. The standalone [Brain Lab](../../brain-lab/README.md) provides its own deterministic exploratory writer and read workflows. It makes no changes to that private save path.

The offline Lab retains failed and inconclusive tests, tracks assessment history in its own ledger, and can reassess a hypothesis on a later window in the same bound source. It can render a Markdown review with evidence references. An export with a different fingerprint makes that Lab binding stale. Native custom metrics and model providers are outside the current contract. See the [measurement registry](../measurements/metric-registry.md) for supported Brain keys.
