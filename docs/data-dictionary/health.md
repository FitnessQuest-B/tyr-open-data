# Activity, heart rate and sleep

TYR Open Data 0.1.0 records projection from TYR v92. The [data dictionary index](README.md) defines the shared conventions. See the [measurement guide](../measurements/README.md) for temporal and analytical semantics.

## `daily_steps`

One stored daily step aggregate per owner and day in this table. Provider imports, device measurements and manual entries have different provenance. Routed history has partial coverage in this projection.

Primary key is `id`.

Declared foreign keys include `(user_id)` → `user(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `user_id` | `INTEGER` | No | Local owner identifier. Join to the projected `user.id` with the source file in scope. |
| `date` | `INTEGER` | No | Persisted civil-day label encoded as UTC-midnight Unix seconds. Interpret the UTC calendar date as the label. |
| `total_steps` | `INTEGER` | No | Recorded aggregate step count. Missing days require a calendar denominator. |
| `source` | `TEXT` | No | Coded origin of the daily step row. Hourly child rows inherit this context. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |

## `hourly_steps`

Optional hour breakdown joined to `daily_steps`. Keep daily totals and hourly components at separate grains. Hours may be missing or have limited timezone resolution.

Primary key is `id`.

Declared foreign keys include `(daily_steps_id)` → `daily_steps(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `daily_steps_id` | `INTEGER` | No | Stored daily step parent identifier. |
| `hour` | `INTEGER` | No | Local clock bucket, ordinarily 0–23. The parent supplies its date label. |
| `steps` | `INTEGER` | No | Step count attributed to the bucket. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |

## `daily_heart_rate`

One stored day-level HR aggregate per owner and day in this table. Keep general HR readings and any reported resting HR distinct. Routed history has partial coverage in this projection.

Primary key is `id`.

Declared foreign keys include `(user_id)` → `user(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `user_id` | `INTEGER` | No | Local owner identifier. Join to the projected `user.id` with the source file in scope. |
| `date` | `INTEGER` | No | Persisted civil-day label encoded as UTC-midnight Unix seconds. |
| `avg_bpm` | `REAL` | No | Daily average bpm. The provider ingestion path averages HR samples and can fall back to resting bpm for a resting-only day. |
| `min_bpm` | `REAL` | Yes | Minimum received general HR reading in bpm, when available. |
| `max_bpm` | `REAL` | Yes | Maximum received general HR reading in bpm, when available. |
| `resting_bpm` | `INTEGER` | Yes | Reported resting HR in bpm, when available. It describes a separate metric. |
| `sample_count` | `INTEGER` | No | Count of general HR readings used by the ingest path. A resting-only row can have zero general readings. |
| `source` | `TEXT` | No | Coded origin of the daily HR row. Hourly child rows inherit this context. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |

## `hourly_heart_rate`

Optional stored hour breakdown joined to `daily_heart_rate`. An unweighted mean of hourly means has a different denominator from a sample-level mean.

Primary key is `id`.

Declared foreign keys include `(daily_heart_rate_id)` → `daily_heart_rate(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `daily_heart_rate_id` | `INTEGER` | No | Stored daily HR parent identifier. |
| `hour` | `INTEGER` | No | Local clock bucket, ordinarily 0–23. The parent supplies its date label. |
| `avg_bpm` | `REAL` | No | Mean HR in the bucket, in bpm. |
| `min_bpm` | `REAL` | Yes | Minimum HR in the bucket, in bpm, when available. |
| `max_bpm` | `REAL` | Yes | Maximum HR in the bucket, in bpm, when available. |
| `sample_count` | `INTEGER` | No | Number of readings in the bucket. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |

## `daily_sleep`

One stored sleep aggregate per owner and assigned sleep date. A session can cross midnight. Treat sleep stage and overall sleep timing as separate evidence.

Primary key is `id`.

Declared foreign keys include `(user_id)` → `user(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `user_id` | `INTEGER` | No | Local owner identifier. Join to the projected `user.id` with the source file in scope. |
| `date` | `INTEGER` | No | Persisted sleep day encoded as UTC-midnight Unix seconds. Overnight sessions are attributed using the stored sleep date. |
| `total_minutes` | `INTEGER` | No | Total sleep duration in minutes after source processing and overlap handling. |
| `deep_minutes` | `INTEGER` | Yes | Minutes classified as deep sleep, when available. |
| `light_minutes` | `INTEGER` | Yes | Minutes classified as light sleep, when available. |
| `rem_minutes` | `INTEGER` | Yes | Minutes classified as REM sleep, when available. |
| `awake_minutes` | `INTEGER` | Yes | Minutes attributed to awake intervals, when reported. |
| `stage_quality` | `TEXT` | No | Ingestion classification, such as `complete`, `incomplete`, `unavailable` or `unknownLegacy`. See the measurement guide. |
| `sleep_start` | `INTEGER` | Yes | Stored sleep start instant in Unix seconds, when available. |
| `sleep_end` | `INTEGER` | Yes | Stored sleep end instant in Unix seconds, when available. |
| `sleep_start_minute` | `INTEGER` | Yes | Recorded wall-clock start minute, 0–1439 when available. |
| `sleep_end_minute` | `INTEGER` | Yes | Recorded wall-clock end minute, 0–1439 when available. |
| `sleep_midpoint_minute` | `INTEGER` | Yes | Recorded wall-clock midpoint minute, 0–1439 when available. |
| `source` | `TEXT` | No | Coded origin of the sleep row. Segment rows inherit this context. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |

## `sleep_segments`

One source-processed stage segment attached to a daily sleep record. Analysis of stage time should account for overlaps and quality. Use the parent for the authoritative stored daily aggregate.

Primary key is `id`.

Declared foreign keys include `(daily_sleep_id)` → `daily_sleep(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `daily_sleep_id` | `INTEGER` | No | Stored daily sleep parent identifier. |
| `start` | `INTEGER` | No | Segment start instant in Unix seconds. |
| `end` | `INTEGER` | No | Segment end instant in Unix seconds. |
| `stage` | `TEXT` | No | Stored stage label, commonly `deep`, `light`, `rem`, `awake` or `unknown`. |
| `duration_minutes` | `INTEGER` | No | Stored segment duration, in minutes. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |

## `morning_hrv`

One stored morning HRV observation per owner and wake date. Analyze like methods together and document source changes.

Primary key is `id`.

Declared foreign keys include `(user_id)` → `user(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `user_id` | `INTEGER` | No | Local owner identifier. Join to the projected `user.id` with the source file in scope. |
| `date` | `INTEGER` | No | Persisted wake-date label encoded as UTC-midnight Unix seconds. |
| `measured_at` | `INTEGER` | No | Measurement instant in Unix seconds. |
| `value_ms` | `REAL` | No | Heart-rate variability value in milliseconds. |
| `metric` | `TEXT` | No | Method label such as `sdnn` or `rmssd`. Historical generic provenance can leave the actual method uncertain. |
| `source` | `TEXT` | No | Coded origin of the observation. Source and method both matter for comparisons. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |
