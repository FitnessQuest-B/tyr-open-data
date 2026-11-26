# Observation-only benchmark task

You receive one folder containing `task.json` and `records.sqlite`. The database uses the TYR Open Data 0.1.0 projection. Use read-only mode. Match dates to the calendar labels in the packet. Use the packet’s opaque case ID in your submission.

For each of the three fixed relationship windows, evaluate whether a later logged positive caffeine dose is associated with at least 15 minutes less following-night sleep. Earlier and later are divided at nutrition clock minute 900, inclusive for later. Pair the recorded nutrition day with the next stored sleep wake date. Describe a result as `supported`, `notSupported` or `inconclusive`. Report late minus earlier in minutes, or JSON null when the effect cannot be estimated. Consider training, weekend, dose size, logging gaps and baseline change. Only report considerations you can support from observations.

For the weight-change window, look for a change of at least 1 kg in recorded weights. Submit `change`, `no_change` or `inconclusive`. Submit the estimated change date only for `change`, with after minus before in kg. Use JSON null for an unavailable estimate. A breakpoint chosen on the same observations is exploratory.

Use observational claims and cite at most twelve row references per decision. Caffeine references can use `daily_snapshot.caffeine_last_dose_minute`, `daily_snapshot.caffeine_mg`, `daily_snapshot.workout_session_count` and `daily_sleep.total_minutes`. Weight references use `daily_snapshot.body_weight`. Use SQLite row IDs in the corresponding table. To earn credit for a decisive caffeine result, cite a positive timed dose and its following wake-date sleep row in each timing arm. For `change`, cite weights on both sides of the proposed shift. For `no_change`, cite weights on at least two different days in the window. All supplied references for a decisive result must be valid and in scope. An inconclusive result may omit references.

## Submission shape

The outer object has `version` set to 1, `worker` set to your implementation name, `elapsed_milliseconds` set to an integer, `provider` set to null for external offline results, and `predictions` as shown below. Use exactly the three window keys supplied in the task. The example shows the format only.

```json
{
  "version": 1,
  "case_id": "00000000000000000000000000000000",
  "relationship": {
    "window_1": {"decision":"inconclusive","claim_type":"association","effect":null,"references":[],"confounders":[]},
    "window_2": {"decision":"inconclusive","claim_type":"association","effect":null,"references":[],"confounders":[]},
    "window_3": {"decision":"inconclusive","claim_type":"association","effect":null,"references":[],"confounders":[]}
  },
  "change": {"decision":"inconclusive","split":null,"effect":null,"references":[],"claim_type":"descriptive"}
}
```

A reference is an object with `table`, `row_id` and `column`. Confounder values are `training_day`, `weekend`, `dose_size`, `logging_gaps` and `baseline_change`. A decisive relationship result needs a numeric estimate of −15 minutes or lower for `supported` and above −15 minutes for `notSupported`. A detected breakpoint needs a date inside the assigned window and an estimate of at least 1 kg in either direction. If you supply an estimate for `no_change`, its magnitude must be below 1 kg. The only submitted targets are those specified in the packet.
