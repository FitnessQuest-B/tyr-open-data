# Canonical measurement keys

These 20 keys and units match the v92 registry enforced by the included Brain insert triggers. The rolling column describes the current app baseline writer. A registry entry gives a key and unit. A populated measurement, available read projection or complete evaluation requires separate evidence.

| Metric key | Stored canonical unit | Source or meaning | Rolling |
|---|---|---|---|
| `total_sleep_minutes` | `minutes` | Selected daily sleep duration | Yes |
| `sleep_debt_minutes_7_day` | `minutes` | Registered sleep-debt concept. The reviewed daily snapshot writer does not populate this field and this records projection omits it. | No |
| `bedtime_minute` | `minute_of_day` | Local sleep start | Yes |
| `wake_minute` | `minute_of_day` | Local sleep end | Yes |
| `sleep_midpoint_minute` | `minute_of_day` | Local sleep midpoint | Yes |
| `workout_session_count` | `count` | Qualifying workout sessions | Yes |
| `workout_minutes` | `minutes` | Derived workout duration | Yes |
| `cardio_minutes` | `minutes` | Derived cardio duration | Yes |
| `strength_volume_load` | `kg_reps` | Sum of effective load × reps | Yes |
| `strength_working_sets` | `sets` | Qualifying strength working sets | Yes |
| `strength_failure_sets` | `sets` | Strength sets marked as failure | Yes |
| `calories` | `kcal` | Resolved recorded calorie intake | Yes |
| `protein_grams` | `grams` | Resolved recorded protein | Yes |
| `carbs_grams` | `grams` | Resolved recorded carbohydrate | Yes |
| `fat_grams` | `grams` | Resolved recorded fat | Yes |
| `total_steps` | `steps` | Daily step count when eligible | Yes |
| `body_weight` | `kg` | Selected daily mass | Yes |
| `resting_hr` | `bpm` | Resting HR evidence | No |
| `average_hr` | `bpm` | Average HR evidence | No |
| `hrv_morning` | `ms` | Morning HRV with method and provenance | No |

Caffeine amounts and timing are present in the records projection. The v92 Brain registry contains neither a caffeine amount key nor a dose-time key. Use a documented external definition for exploratory interpretation. Treat any future native metric addition as a contract change. The native `minute_of_day` metrics above describe the 0–1439 sleep clock, while caffeine timing uses the nutrition-day scale.

See [calculation and coverage rules](derived.md) and the [Brain contract](../brain/README.md).
