# Derived measurements in TYR v92

The descriptions below apply to the inspected writers. Historical rows may come from other calculation versions. See the [table dictionary](../data-dictionary/interventions-and-summaries.md) and [metric registry](metric-registry.md).

## Daily snapshots

The inspected writer uses snapshot shape 1 and calculation version 6. It refreshes a materialized combination of sleep, training, activity, nutrition and body weight by owner and stored civil date.

| Metric family | Inspected calculation |
|---|---|
| Sleep duration and stage percent | Duration comes from the selected daily sleep row. A known deep or REM amount divided by positive total sleep minutes gives the respective percentage. The writer prefers persisted sleep clock minutes and uses compatibility fallbacks where possible. |
| HRV deviation | Compare the day’s eligible value with the positive mean of trusted observations of the same method in the prior 30-day window, excluding the reported day. The writer requires at least three observations and 50% coverage. It records `100 × (today − mean) / mean` where eligible. Unknown legacy method can leave deviation and coverage absent. |
| Workout time | Sum whole nonnegative elapsed minutes of sessions with end times. If that sum is zero, use recorded set duration seconds divided by 60 and truncated to whole minutes. The result can include time beyond active movement. |
| Cardio time | Per session, use positive canonical cardio set durations when present. Otherwise use eligible activity durations, preferring recorded summary seconds, then activity seconds, then a positive elapsed interval. The day total is truncated to whole minutes. |
| Strength load and set counts | Sum effective load in kg multiplied by reps over eligible strength sets. Bodyweight or assistance calculations use exercise semantics and contributions that are partly outside the projection. The writer counts working and failure sets separately. An estimate can omit an unresolved load contributor. |
| Body weight | Compute seven- and 28-day means across eligible daily weights through the snapshot day. The stored trend is the seven-day mean minus the 28-day mean. Days without a resolved reading do not contribute a zero. |
| Daily nutrition | Resolve logged events, children and modifiers using captured nutrient values and compatible fallback rules. Protein per kg uses a positive recorded body weight. Calorie and nutrient totals describe recorded intake. |
| Caffeine and meal timing | Last dose minute is the latest resolved positive-caffeine group by log timestamp. Eating-window duration needs two distinct qualifying times. It uses latest minus earliest on the nutrition clock scale. Logged meal count uses distinct qualifying meal categories. |
| Timing variability | The 14-day windows through the snapshot day use first qualifying meal times or selected primary workout starts. A day’s primary workout prefers largest positive strength load, then longest positive cardio duration when there is no strength candidate. At least two observed timings are needed for the circular spread in minutes. |

Snapshot coverage fields for sleep, steps, HR and nutrition can record 100 for eligible presence. The nutrition field measures resolved event presence, and nutrients can still be missing. Workout zeros can summarize the absence of eligible sessions or durations in source data. These values need an independent observation and coverage policy if used as evidence of inactivity.

## Rolling baselines

The v92 service computes 7, 14, 30 and 90 prior calendar days for the 16 keys marked as rolling in the [registry](metric-registry.md). It excludes `computed_date`. Inclusion depends on the metric. For example, sleep, steps and nutrition use coverage-qualified values, and the app can read effective routed steps. Some legacy workout baselines use a conditional zero when a snapshot carries workout observation. The public reader returns stored results and cannot recreate all app routing or calculation inputs.

- Scalar statistics include arithmetic mean, population standard deviation, numeric median, min/max, linearly interpolated quartiles and an ordinary least-squares slope over day offsets.
- Clock metrics use a circular mean and root-mean-square shortest-arc distance to that mean, in minutes. Stored medians, quartiles and slopes still use numeric coordinates. Inspect midnight crossing and multimodality before interpreting those summaries.
- With one point, storage records zero SD and no slope. Zero points gives NULL summary statistics. Means can still be present below the eligibility threshold.
- Coverage is observed days divided by expected window days, expressed as a percentage. Missing and excluded days stay in the denominator. The stored minimum requires at least three observations and 50% coverage. Coverage labels are `complete` at 95% or more, `mostly_usable` at 75% or more, `partial` at 50% or more, `sparse` above zero and `unavailable` otherwise.
- Overlapping rolling windows share source observations. A high coverage score or 90-day span gives no inferential guarantee. Report the metric-specific sample size and temporal stability separately.

## Other calculation limits

**Cardio.** Live HR means are weighted by supported timer-active spans, while the median is based on valid readings. Support can be capped across sample gaps. Coverage is supported over active time. Machine means can use supported duration weights by channel. Overall machine coverage does not imply that every channel was measured. Zone seconds require usable HR and zone input, including max-HR context. Zero zone values can coexist with insufficient evidence. The projection does not provide enough raw samples or device context to reconstruct all summaries or zones.

**Strength and assessments.** TYR’s Brzycki-style estimator uses `load_kg / (1.0278 − 0.0278 × reps)` for eligible inputs and the recorded load for one rep. The implementation rejects invalid inputs and near-zero or negative denominators. A working max captured on a set is an estimate at logging time. Fitness tests rely on exercise identity and protocol. A fixed-distance timed mile uses its designated exercise, distance and positive duration. Flexibility test lengths are stored in metres in applicable set rows. Norms, medal grants, Quest state and protocol standards are separate from the observations and outside this profile.

**Nutrition.** Use `log_entry_nutrients` where a historical snapshot exists. The inspected fallback can use non-null headline fields for eligible legacy entries as unclassified evidence. It can suppress fallback for snapshot-shaped food records with no nutrient rows. The full resolver also interprets grouping and modifier operations, and some classification and recipe inputs are outside this projection. A simple sum or join to the current food catalogue can disagree with historical TYR totals. Coverage labels `COMPLETE`, `PARTIAL` and `UNCLASSIFIED` apply to the associated amount and provide no assurance about all intake or all nutrients.
