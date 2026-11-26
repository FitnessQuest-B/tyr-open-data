# Body measurements and training

TYR Open Data 0.1.0 records projection from TYR v92. The [data dictionary index](README.md) defines the shared conventions. See the [measurement guide](../measurements/README.md) for temporal and analytical semantics.

## `user`

At most one owner in an admitted TYR export. The projection exposes only its local join key. Files and devices have independent identifiers.

Primary key is `id`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |

## `body_measurement_point`

Reference row per tracked anatomical point. Join by local ID to interpret a circumference or other length. Keep measurement technique consistent over time.

Primary key is `id`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `key` | `TEXT` | No | Catalogue key for the measurement point. |
| `name` | `TEXT` | No | Human-readable point label. |

## `body_measurement`

One body measurement at a point and time. Treat the value as a recorded, commonly user-entered length. Use the same point and measurement method when comparing observations.

Primary key is `id`.

Declared foreign keys include `(point_id)` → `body_measurement_point(id)`, `(user_id)` → `user(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `user_id` | `INTEGER` | No | Local owner identifier. Join to the projected `user.id` with the source file in scope. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |
| `point_id` | `INTEGER` | No | Identifier of the anatomical point in `body_measurement_point`. |
| `value_cm` | `REAL` | No | Recorded centimetres. The schema requires a nonnegative value. |
| `measured_at` | `INTEGER` | No | Measurement instant in Unix seconds. A travel-stable local date is outside this projection. |

## `body_weight`

One recorded body-weight observation. TYR can retain multiple records on one day. A study that wants one value per day needs an explicit day and source-selection rule.

Primary key is `id`.

Declared foreign keys include `(user_id)` → `user(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `user_id` | `INTEGER` | No | Local owner identifier. Join to the projected `user.id` with the source file in scope. |
| `weight_kg` | `REAL` | No | Recorded mass in kg. TYR manual entry accepts 20–400 kg. That is an app input rule. |
| `measured_at` | `INTEGER` | No | Measurement instant in Unix seconds. A travel-stable local date is outside this projection. |
| `source` | `TEXT` | No | Stored origin class, such as manual or a platform health import. See the measurement guide. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |

## `exercise_table`

Reference row for an exercise, including some user-created entries. Category and equipment guide interpretation of measurements. Full load semantics and machine-specific metadata are outside the projection.

Primary key is `id`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `name_key` | `TEXT` | No | Stored exercise lookup or naming key. Custom entries can carry user text. |
| `system_created` | `INTEGER` | No | Flag indicating an app-supplied exercise. |
| `category` | `TEXT` | No | Exercise classification, which can distinguish special or protocol exercises. |
| `equipment_type` | `TEXT` | No | Equipment classification used by the exercise. |
| `stretch_metric_pref` | `TEXT` | Yes | Configured measurement preference for applicable flexibility exercises. |
| `per_dumbbell` | `INTEGER` | No | Flag for per-dumbbell load storage. Interpret load with the relevant exercise semantics. |

## `workout_sessions`

One recorded session. Use the session ID to join sets and cardio activities. A row can represent an ongoing session or retained deletion.

Primary key is `id`.

Declared foreign keys include `(user_id)` → `user(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `user_id` | `INTEGER` | No | Local owner identifier. Join to the projected `user.id` with the source file in scope. |
| `started_at` | `INTEGER` | No | Session start instant in Unix seconds. Group into local days only with an explicit time basis. |
| `ended_at` | `INTEGER` | Yes | Session end instant in Unix seconds, when recorded. |
| `perceived_exertion` | `INTEGER` | Yes | User-entered session-level exertion value. The schema leaves the scale unspecified. |
| `source` | `TEXT` | No | Capture class. The app uses `manual`, `ftms`, `import` and `api`. |
| `confidence` | `INTEGER` | No | Stored confidence score, 0–100 in the application. It describes fidelity of capture. It has no statistical confidence interpretation. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |

## `exercise_sets`

One logged set in a session. The session ID and set index are unique together. Interpret distance and time with the exercise protocol and avoid pooling warm-ups, working sets and test attempts without a rule.

Primary key is `id`.

Declared foreign keys include `(exercise_id)` → `exercise_table(id)`, `(session_id)` → `workout_sessions(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `session_id` | `INTEGER` | No | Parent workout session identifier. |
| `exercise_id` | `INTEGER` | No | Reference to the exercise catalogue entry. |
| `set_index` | `INTEGER` | No | Position in the session, typically zero-based. |
| `superset_group` | `INTEGER` | Yes | Optional local grouping key for a superset or circuit. |
| `set_type` | `TEXT` | Yes | Stored set classification such as `normal`, `warmup`, `failure`, `drop`, `superset` or `circuit`. Historical values can differ. |
| `reps` | `INTEGER` | Yes | Recorded repetition count. The current app table checks for a nonnegative value. |
| `load_kg` | `REAL` | Yes | Entered or captured load in kg. Apply the exercise’s equipment and bodyweight semantics. The app table checks for a nonnegative value. |
| `distance_m` | `REAL` | Yes | Recorded distance in metres, including applicable fitness protocols. The app table checks for a nonnegative value. |
| `duration_sec` | `INTEGER` | Yes | Recorded duration in seconds. The app table checks for a nonnegative value. |
| `working_one_rep_max_kg_at_log` | `REAL` | Yes | Estimated working one-rep maximum in kg at logging time. It can be absent and is distinct from a measured attempt. |
| `avg_speed_kmh` | `REAL` | Yes | Captured mean speed in km/h, when applicable. |
| `avg_power_w` | `REAL` | Yes | Captured mean power in watts, when applicable. |
| `avg_cadence_rpm` | `REAL` | Yes | Captured mean cadence in revolutions per minute, when applicable. |
| `incline` | `REAL` | Yes | Recorded grade in percentage points, when available. |
| `resistance` | `REAL` | Yes | Machine-specific resistance. Confirm the equipment scale before comparisons. |
| `rpe` | `REAL` | Yes | Per-set rating of perceived exertion. The app table checks 0–10. |
| `performed_at` | `INTEGER` | Yes | Actual set performance instant in Unix seconds, when recorded. |
| `source` | `TEXT` | No | Capture class. The app uses `manual`, `ftms`, `import` and `api`. |
| `confidence` | `INTEGER` | No | Stored confidence score, 0–100 in the application. It describes fidelity of capture. It has no statistical confidence interpretation. |

## `cardio_activities`

One cardio bout in a workout session. Duration and distance may also occur on sets or on a derived summary. Reconcile overlapping representations before aggregation.

Primary key is `id`.

Declared foreign keys include `(exercise_id)` → `exercise_table(id)`, `(session_id)` → `workout_sessions(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `session_id` | `INTEGER` | No | Parent workout session identifier. |
| `exercise_id` | `INTEGER` | Yes | Reference to the exercise catalogue entry. |
| `activity_type` | `TEXT` | No | Bout category. Current app values are `run`, `treadmill`, `walk`, `bike`, `elliptical`, `rower`, `stairClimber` and `other`. |
| `started_at` | `INTEGER` | No | Bout start instant in Unix seconds. |
| `ended_at` | `INTEGER` | Yes | Bout end instant in Unix seconds, when recorded. |
| `duration_sec` | `INTEGER` | Yes | Recorded duration in seconds. The source app checks nonnegative values. Timer-active time may differ from end minus start. |
| `distance_m` | `REAL` | Yes | Recorded distance in metres. The source app checks nonnegative values. |
| `source` | `TEXT` | No | Capture class. The app uses `manual`, `ftms`, `import` and `api`. |
| `capture_mode` | `TEXT` | No | Capture path. Current values include `manual`, `ftmsLive`, `healthConnectImport`, `derived` and `unknown`. |
| `confidence` | `INTEGER` | No | Stored confidence score, 0–100 in the application. It describes fidelity of capture. It has no statistical confidence interpretation. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |

## `cardio_activity_summaries`

Materialized summary, at most one per cardio bout. Fields may come from separate capture paths and can have different coverage within the same bout. Check collection mode and version before comparing summaries.

Primary key is `id`.

Declared foreign keys include `(cardio_activity_id)` → `cardio_activities(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `cardio_activity_id` | `INTEGER` | No | Parent cardio bout identifier. |
| `duration_sec` | `INTEGER` | Yes | Stored summary duration in seconds. The app table checks for a nonnegative value. |
| `distance_m` | `REAL` | Yes | Stored summary distance in metres. The app table checks for a nonnegative value. |
| `calories_total` | `REAL` | Yes | Stored exercise-energy total in kcal when available. Treat it as a device or source estimate. |
| `avg_hr_bpm` | `REAL` | Yes | Mean heart rate in bpm. The observed live-HR writer weights by supported timer-active spans. |
| `max_hr_bpm` | `INTEGER` | Yes | Maximum retained reading, in bpm. |
| `median_hr_bpm` | `REAL` | Yes | Median retained reading in bpm. The observed live path uses the median of valid readings. |
| `min_hr_bpm` | `INTEGER` | Yes | Minimum retained reading, in bpm. |
| `hr_coverage_pct` | `REAL` | Yes | Percent of timer-active duration with supported HR in the observed live path. Source check is 0–100. |
| `zone1_sec` | `INTEGER` | No | Stored seconds in HR zone 1. Interpret alongside zone input availability. |
| `zone2_sec` | `INTEGER` | No | Stored seconds in HR zone 2. Interpret alongside zone input availability. |
| `zone3_sec` | `INTEGER` | No | Stored seconds in HR zone 3. Interpret alongside zone input availability. |
| `zone4_sec` | `INTEGER` | No | Stored seconds in HR zone 4. Interpret alongside zone input availability. |
| `zone5_sec` | `INTEGER` | No | Stored seconds in HR zone 5. Interpret alongside zone input availability. |
| `avg_speed_kmh` | `REAL` | Yes | Stored mean speed in km/h. The observed live-machine writer weights supported samples by duration. |
| `max_speed_kmh` | `REAL` | Yes | Highest supported speed in km/h. |
| `avg_power_w` | `REAL` | Yes | Stored mean power in watts. Internal capture can omit this metric when signed power cannot be represented. |
| `max_power_w` | `REAL` | Yes | Highest supported power in watts, subject to the signed-power limitation. |
| `avg_cadence_rpm` | `REAL` | Yes | Stored mean cadence in revolutions per minute. |
| `avg_incline` | `REAL` | Yes | Stored mean grade in percentage points. |
| `avg_resistance` | `REAL` | Yes | Stored mean resistance on the device scale. |
| `elevation_gain_m` | `REAL` | Yes | Stored elevation gain in metres when available. |
| `machine_coverage_pct` | `REAL` | Yes | Percent of active time supported by machine metric observations in the observed live path. Source check is 0–100. |
| `calculation_version` | `INTEGER` | No | Stored numeric version of the cardio summary calculation. |
| `computed_at` | `INTEGER` | No | Instant at which the derived value was written or refreshed, in Unix seconds. |

## `cardio_recovery_tests`

One recovery test per activity and test type. Read a drop only in the context of the protocol and measurement timing.

Primary key is `id`.

Declared foreign keys include `(cardio_activity_id)` → `cardio_activities(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `cardio_activity_id` | `INTEGER` | No | Parent cardio bout identifier. |
| `measured_at` | `INTEGER` | No | Test measurement instant in Unix seconds. |
| `test_type` | `TEXT` | No | Stored protocol label. The app default is `postActivity`. |
| `recovery60_sec_bpm_drop` | `INTEGER` | Yes | Recorded heart-rate drop at the 60-second point, in bpm. |
| `recovery120_sec_bpm_drop` | `INTEGER` | Yes | Recorded heart-rate drop at the 120-second point, in bpm. |
