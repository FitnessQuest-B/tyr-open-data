# Interventions and derived summaries

TYR Open Data 0.1.0 records projection from TYR v92. The [data dictionary index](README.md) defines the shared conventions. See the [measurement guide](../measurements/README.md) for temporal and analytical semantics.

## `interventions`

Catalogue definition for a user-tracked intervention. Use recorded periods for exposure timing. Definition membership alone gives no evidence of adherence or an effect.

Primary key is `id`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `uuid` | `TEXT` | No | Stored UUID-style identity. Scope it to the type of record and source. |
| `name` | `TEXT` | No | Stored intervention label, which can be user-entered. |
| `category` | `TEXT` | Yes | Optional stored grouping label. |
| `intervention_type` | `TEXT` | No | Stored intervention classification. |
| `is_custom` | `INTEGER` | No | Stored custom-entry flag, encoded as 0 or 1. This is a catalogue classification. |
| `is_deleted` | `INTEGER` | No | Stored deletion flag, encoded as 0 or 1. Use it when selecting active records. |

## `intervention_periods`

One recorded period of intervention activity. It may be open-ended or linked to an app logging workflow. An interval represents the record of exposure. Adherence and actual dose need separate evidence.

Primary key is `id`.

Declared foreign keys include `(intervention_id)` → `interventions(id)`, `(source_log_entry_id)` → `log_entries(id)`, `(workout_session_id)` → `workout_sessions(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `user_id` | `INTEGER` | No | Local owner identifier. Join to the projected `user.id` with the source file in scope. |
| `uuid` | `TEXT` | No | Stored UUID-style identity. Scope it to the type of record and source. |
| `intervention_id` | `INTEGER` | No | Intervention identifier within this database. |
| `started_at` | `INTEGER` | No | Recorded start instant in Unix seconds. |
| `ended_at` | `INTEGER` | Yes | Recorded end instant in Unix seconds, when present. NULL can indicate an open period. |
| `start_day_key` | `INTEGER` | No | Stored civil start label as integer YYYYMMDD. This uses the intervention day convention. |
| `end_day_key` | `INTEGER` | Yes | Stored civil end label as integer YYYYMMDD, when present. |
| `workout_session_id` | `INTEGER` | Yes | Optional associated workout session. |
| `source_log_entry_id` | `INTEGER` | Yes | Optional ledger row that generated or documents the period. |
| `source_type` | `TEXT` | Yes | Optional origin/workflow label, such as manual, supplement automation or stack application. |
| `is_deleted` | `INTEGER` | No | Stored deletion flag, encoded as 0 or 1. Use it when selecting active records. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |

## `intervention_outcome_metric`

One declared outcome metric for an intervention. These fields describe intended direction and thresholds. Recorded results live in a separate evaluation or observation.

Primary key is `id`.

Declared foreign keys include `(intervention_id)` → `interventions(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `intervention_id` | `INTEGER` | No | Intervention identifier within this database. |
| `metric_key` | `TEXT` | No | Stored metric identifier. Consult the documented canonical unit map when the key is supported. |
| `expected_direction` | `TEXT` | No | Configured `increase`, `decrease`, `maintain` or `unknown` direction in current app logic. |
| `is_primary` | `INTEGER` | No | Flag marking the outcome as primary. |
| `expected_onset_days` | `INTEGER` | Yes | Optional number of days for ramp-in. The evaluator treats negative timing as invalid. |
| `washout_days` | `INTEGER` | Yes | Optional post-period exclusion window in days. The evaluator treats negative timing as invalid. |
| `minimum_meaningful_change` | `REAL` | Yes | Optional configured change threshold. Validate its unit and direction before applying it. |
| `minimum_meaningful_change_unit` | `TEXT` | Yes | Stored unit for the threshold, such as minutes, bpm, kg or percent. |
| `is_deleted` | `INTEGER` | No | Stored deletion flag, encoded as 0 or 1. Use it when selecting active records. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |

## `intervention_supplements`

Link from an intervention definition to a supplement. The configured regimen describes intended use. Use independent intake evidence to estimate dose or adherence.

Primary key is `intervention_id`, `supplement_id`.

Declared foreign keys include `(intervention_id)` → `interventions(id)`, `(supplement_id)` → `supplements(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `intervention_id` | `INTEGER` | No | Intervention identifier within this database. |
| `supplement_id` | `INTEGER` | No | Supplement catalogue identifier. |
| `dose_amount` | `REAL` | Yes | Configured amount on the linked dose scale, when supplied. |
| `dose_unit` | `TEXT` | Yes | Unit of the configured dose. |
| `frequency_per_day` | `REAL` | Yes | Configured frequency in doses per day, when supplied. |

## `daily_snapshot`

Materialized cross-domain daily record per owner and local date. A precomputed value can reflect historical logic, limited source coverage or a stale snapshot. Use the stored version and coverage and check the export projection status before pooling days.

Primary key is `id`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `user_id` | `INTEGER` | No | Local owner identifier. Join to the projected `user.id` with the source file in scope. |
| `snapshot_date` | `TEXT` | No | Stored civil day as YYYY-MM-DD. |
| `snapshot_version` | `INTEGER` | No | Version of the snapshot row shape. The reviewed v92 writer uses 1. |
| `calculation_version` | `INTEGER` | No | Version of the app calculation. The reviewed v92 writer uses 6. |
| `hrv_deviation_pct` | `REAL` | Yes | Percentage deviation from a prior same-method HRV baseline, where eligible. |
| `hrv_metric` | `TEXT` | Yes | Method used for the HRV measure underlying the deviation, when known. |
| `hrv_baseline_sample_size` | `INTEGER` | Yes | Count of eligible prior HRV observations in the baseline. |
| `hrv_baseline_coverage_pct` | `REAL` | Yes | Percent of the expected HRV baseline days with eligible observations. |
| `bedtime_minute` | `INTEGER` | Yes | Sleep start wall-clock minute, 0–1439 when available. The writer prefers stored sleep clock values. |
| `wake_minute` | `INTEGER` | Yes | Sleep end wall-clock minute, 0–1439 when available. |
| `sleep_midpoint_minute` | `INTEGER` | Yes | Sleep midpoint wall-clock minute, 0–1439 when available. |
| `total_sleep_minutes` | `INTEGER` | Yes | Minutes of sleep drawn from the selected daily sleep row, when available. |
| `deep_sleep_minutes` | `INTEGER` | Yes | Stored deep sleep duration, in minutes. |
| `rem_sleep_minutes` | `INTEGER` | Yes | Stored REM sleep duration, in minutes. |
| `light_sleep_minutes` | `INTEGER` | Yes | Stored light sleep duration, in minutes. |
| `deep_sleep_pct` | `REAL` | Yes | 100 × deep minutes divided by positive total sleep minutes, when inputs exist. |
| `rem_sleep_pct` | `REAL` | Yes | 100 × REM minutes divided by positive total sleep minutes, when inputs exist. |
| `workout_session_count` | `INTEGER` | Yes | Count of eligible workout sessions in the day window, when supplied. |
| `workout_minutes` | `INTEGER` | Yes | Derived workout duration in minutes. See the measurement guide for duration semantics. |
| `cardio_minutes` | `INTEGER` | Yes | Derived cardio duration in minutes with reconciliation of set and activity representations. |
| `strength_volume_load` | `REAL` | Yes | Estimated effective working load × reps summed across eligible sets, in kg·reps. Some bodyweight lineage inputs are outside this projection. |
| `strength_working_sets` | `INTEGER` | Yes | Count of sets counted as working sets by the writer. |
| `strength_failure_sets` | `INTEGER` | Yes | Count of sets counted as failure sets by the writer. |
| `caloric_intake` | `REAL` | Yes | Resolved logged calorie total in kcal, when available. Coverage is about logging evidence. |
| `protein_grams` | `REAL` | Yes | Resolved logged protein total, in grams. |
| `protein_per_kg_body_weight` | `REAL` | Yes | Protein grams divided by a positive same-day recorded body weight, where both are available. |
| `carbs_grams` | `REAL` | Yes | Resolved logged carbohydrate total, in grams. |
| `fat_grams` | `REAL` | Yes | Resolved logged fat total, in grams. |
| `caffeine_mg` | `REAL` | Yes | Resolved logged caffeine total, in milligrams. Can be incomplete or unknown. |
| `caffeine_last_dose_minute` | `INTEGER` | Yes | Clock minute of the latest resolved positive-caffeine group, on the nutrition day scale. |
| `eating_window_start_minute` | `INTEGER` | Yes | Earliest qualifying meal timing on the nutrition day scale when two distinct times exist. |
| `eating_window_end_minute` | `INTEGER` | Yes | Latest qualifying meal timing on the nutrition day scale when two distinct times exist. |
| `eating_window_minutes` | `INTEGER` | Yes | End minus start on the nutrition clock scale, in minutes. It represents the span between logged events. |
| `logged_meal_count` | `INTEGER` | Yes | Count of distinct qualifying meal categories in the day. |
| `meal_timing_sd_minutes14_day` | `REAL` | Yes | Circular timing spread in minutes of first qualifying meals on observed days in a trailing 14-day window. |
| `workout_timing_sd_minutes14_day` | `REAL` | Yes | Circular timing spread in minutes of selected primary workout starts in a trailing 14-day window. |
| `total_steps` | `INTEGER` | Yes | Stored step total drawn from the app's available daily history, when present. Eligibility can differ. |
| `sleep_data_coverage_pct` | `REAL` | Yes | Stored daily sleep presence indicator. The reviewed writer sets 100 for a selected sleep row, otherwise NULL. |
| `heart_rate_data_coverage_pct` | `REAL` | Yes | Stored presence and eligibility indicator. The reviewed writer sets 100 for eligible HR with positive sample count, otherwise NULL. |
| `step_data_coverage_pct` | `REAL` | Yes | Stored presence and eligibility indicator. The reviewed writer sets 100 for an eligible non-null step total, otherwise NULL. |
| `nutrition_data_coverage_pct` | `REAL` | Yes | Stored logging presence indicator. The reviewed writer sets 100 if any nutrition events were resolved, otherwise NULL. |
| `body_weight` | `REAL` | Yes | Selected daily body weight, in kg. |
| `body_weight7_day_avg` | `REAL` | Yes | Mean of eligible daily weight readings across a trailing seven-day window ending on the snapshot day, in kg. |
| `body_weight28_day_avg` | `REAL` | Yes | Mean of eligible daily weight readings across a trailing 28-day window ending on the snapshot day, in kg. |
| `body_weight_trend7_vs28` | `REAL` | Yes | Seven-day mean minus 28-day mean, in kg. NULL when either mean is unavailable. |
| `computed_at` | `INTEGER` | No | Instant at which the derived value was written or refreshed, in Unix seconds. |

## `baseline_metric`

Materialized rolling statistics by owner, metric, day window and computation date. Use both the observed sample size and the expected window. Derived rows may be sparse, absent or stale.

Primary key is `id`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `user_id` | `INTEGER` | No | Local owner identifier. Join to the projected `user.id` with the source file in scope. |
| `metric_key` | `TEXT` | No | Canonical metric key where known. The current rolling service computes a defined subset of keys. |
| `metric_domain` | `TEXT` | Yes | Optional stored topical grouping. |
| `unit` | `TEXT` | Yes | Stored metric unit. Validate it against the measurement guide. |
| `window_days` | `INTEGER` | No | Expected window length, in days. The v92 writer computes 7, 14, 30 and 90 day windows. |
| `computed_date` | `TEXT` | No | Civil computation date as YYYY-MM-DD. The rolling window excludes this day. |
| `mean` | `REAL` | Yes | Mean of observed eligible values. Clock metrics use a circular mean. |
| `median` | `REAL` | Yes | Numeric median of observed eligible values. |
| `p25` | `REAL` | Yes | 25th percentile via linear interpolation of sorted eligible values. |
| `p75` | `REAL` | Yes | 75th percentile via linear interpolation of sorted eligible values. |
| `standard_deviation` | `REAL` | Yes | Population SD for scalar values or RMS shortest clock-arc distance for clock metrics, in metric units or minutes. |
| `linear_slope` | `REAL` | Yes | Least-squares slope over eligible observations and day offsets, in metric units per day. May be NULL with insufficient spacing or observations. |
| `min_value` | `REAL` | Yes | Minimum observed eligible value. |
| `max_value` | `REAL` | Yes | Maximum observed eligible value. |
| `sample_size` | `INTEGER` | No | Count of included observations. |
| `coverage_pct` | `REAL` | Yes | 100 × observed over expected days under the current calculation. |
| `coverage_status` | `TEXT` | Yes | Stored bucket such as `complete`, `mostly_usable`, `partial`, `sparse` or `unavailable`. |
| `meets_minimum_coverage` | `INTEGER` | No | Stored eligibility flag. The current rule requires at least three observations and at least 50% coverage. |
| `first_observed_date` | `TEXT` | Yes | First included civil date as YYYY-MM-DD, when present. |
| `last_observed_date` | `TEXT` | Yes | Last included civil date as YYYY-MM-DD, when present. |
| `excluded_day_count` | `INTEGER` | No | Number of days from the requested window without an included observation. |
| `computed_at` | `INTEGER` | No | Instant at which the derived value was written or refreshed, in Unix seconds. |
