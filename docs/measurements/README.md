# Measurements, provenance and time

This guide describes observed TYR v92 behavior for the supported 0.1.0 projection. See the [table dictionary](../data-dictionary/README.md), [derived calculations](derived.md) and [canonical metric registry](metric-registry.md) for the corresponding fields and formulas.

## Time and dates

| Field family | Encoding | Interpretation |
|---|---|---|
| Instants such as `measured_at`, `logged_at`, `started_at` and `computed_at` | Integer Unix seconds | Use elapsed time for event ordering and interval arithmetic. Event-level workout and body measurements can lack an independently stored historical local day in this projection. |
| Health `date` in daily steps, HR, sleep and morning HRV | Integer Unix seconds encoding the civil date at UTC midnight | Decode to a UTC calendar date for the label. Converting through the analysis machine’s local timezone can change the label. For overnight sleep, prefer the assigned sleep day over an inferred day from a start timestamp. |
| Nutrition `day_key` | Integer YYYYMMDD | A nutrition day starts at 03:00 local time. Logs from midnight through 02:59 belong to the previous nutrition day. Use the persisted key for historical grouping. |
| Intervention `start_day_key` and `end_day_key` | Integer YYYYMMDD | Stored civil range labels for intervention analysis. The nutrition cutoff applies only to nutrition. Use an instant-based interval when the analysis requires actual elapsed time. |
| `snapshot_date`, `computed_date`, and baseline observation dates | Text YYYY-MM-DD | Stored local calendar labels. A snapshot’s date and its computation instant have different purposes. |
| Hour buckets and sleep clock minutes | Hour label, ordinarily 0–23, or wall-clock minute, ordinarily 0–1439 | Match hours to their parent’s date. A clock label cannot uniquely encode a repeated hour at a daylight-saving transition. For sleep, use a circular clock or absolute event instants as the question requires. |
| Nutrition clock minutes in daily snapshots | Local minutes 180–1619 on the nutrition-day scale | Midnight through 02:59 appears as 1440–1619. Use the ordered scale for an eating-window span and account for the day boundary when pairing caffeine with sleep. Clock fields provide limited historical timezone evidence. |

Preserve recorded dates through travel and DST. The public projection omits offsets and route internals needed to reconstruct some histories. If only an instant is available, state any timezone assumption and test whether offsets change the result. Do not apply a blanket 24-hour denominator to local-day or exposure-duration analyses. Coverage by expected calendar days and coverage by elapsed minutes answer different questions.

## Source classes and coverage

- **Manual or user-entered** values record what a person entered. This can include body measurements, food amounts, intervention dates and exertion. Repeated measurements can use different procedures or scales.
- **Device or provider** observations include raw readings summarized by TYR or by a source. Health source examples include `manual`, `tyrDevice`, `tyrFtmsCardio`, `healthConnect` and `appleHealth`. Historical `synced`, `health_connect` and `apple_health` labels can carry less specific provenance. `fake` and `devSeed` indicate development inputs. For some daily health conflicts the app prioritizes manual, TYR device, platform sync, then development sources. The adapter does not replay that routing and conflict policy.
- **Catalogue or label estimates** cover food portions, nutrients and supplement amounts. Product labels and user estimates describe declared quantities. They do not establish observed intake, absorption or treatment effect.
- **Derived** values depend on source availability and calculation version. Document the raw sources, capture path and excluded periods when the projection lets you determine them. Materialized rows can be stale, and the v92 adapter does not recalculate them.
- **Coverage** is metric-specific. Percentages use a 0–100 scale and Brain ratios use 0–1. A snapshot can contain 100 for presence or eligible capture on a day. This can coexist with incomplete logging or sampling. Preserve NULL where available evidence does not determine a value.

The reader marks steps, heart rate and related summaries `limited` whenever routing is present or unknown. An explicit partial read returns storage rows. Report that limitation with any result. For a study denominator, define the expected observation grid, count observed and eligible values separately, and document treatment of tombstones, repeated observations and gaps. A stored zero only supports a zero-valued observation when the measurement and coverage make that interpretation valid.

## Use and limitations by domain

| Domain | Canonical storage or reported units | Appropriate analysis | Important limits |
|---|---|---|---|
| Body dimensions and weight | cm and kg | Compare the same point or weight procedure across observed visits. Use a declared day rule for a trend. | Manual weight accepts 20–400 kg in the app. Different scales, posture and measurement timing change comparability. Height and BMI are outside the public read profile. |
| Workouts and assessments | Counts, kg, m, s, km/h, watts, rpm, percentage grade and protocol-dependent values | Compare like exercises, set types and test protocols. Use stored working 1RM as a historical estimate. | Per-dumbbell and bodyweight/assisted semantics can differ. Machine resistance has a device-specific scale. App set RPE checks 0–10. Session exertion has no universal schema scale. |
| Steps and HR | Steps, bpm, sample count and time coverage | Compare consistently sampled dates or hours with comparable source streams. | Summing daily totals with hourly children double counts. Missing hours and low observation density limit daily inferences. Resting-only HR rows can carry a derived fallback for average HR. |
| Sleep | Minutes, time instants, clock minutes and stage labels | Analyze sleep timing or overall duration with explicit coverage. Use stage quality for stage-specific analyses. | Sleep intervals can overlap, and stage labels or clock offsets can be unavailable. Stage data does not establish clinical sleep status. |
| HRV | ms with a method label, such as RMSSD or SDNN | Compare same-method, sufficiently covered measurements under similar collection conditions. | Equal units are insufficient for pooling methods. Generic legacy provenance can leave the method uncertain. A method or device shift can look like a personal change. |
| Food and supplements | kcal, g, mg, µg, IU and declared dose units | Use stored nutrient identity and historical amounts to characterize documented intake. | Missing amounts stay unknown. Coverage classes describe evidence in the log or label. A label or dose schedule provides no proof of adherence. Do not assume that IU can be converted to mass without nutrient-specific rules. |
| Intervention and Brain evidence | Time, metric-specific amount/unit, effect size and coverage ratio | Compare stated exposure periods and outcomes under a declared design and meaningful-change unit. | Concurrent exposures, changes in recording and baseline drift can confound the comparison. A stored effect or graph link provides no independent causal validation. |

### Sleep stage quality

The ingestion classifier uses `complete`, `incomplete`, `unavailable` and `unknownLegacy`. Where a positive session duration and precise stage evidence exist, the complete threshold is 75%, using precise stage sleep plus awake-within-session minutes relative to session minutes. Missing precise stages can be unavailable while total sleep remains usable. Keep the stored classification. Recomputing by summing exported segments can disagree with the ingest path’s interval overlap and rounding rules.
