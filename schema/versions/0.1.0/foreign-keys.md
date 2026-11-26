# SQLite foreign keys

Generated from the versioned schema.

## records

| Child columns | Parent columns | On update | On delete |
|---|---|---|---|
| `body_measurement(point_id)` | `body_measurement_point(id)` | NO ACTION | RESTRICT |
| `body_measurement(user_id)` | `user(id)` | NO ACTION | CASCADE |
| `body_weight(user_id)` | `user(id)` | NO ACTION | CASCADE |
| `cardio_activities(exercise_id)` | `exercise_table(id)` | NO ACTION | SET NULL |
| `cardio_activities(session_id)` | `workout_sessions(id)` | NO ACTION | CASCADE |
| `cardio_activity_summaries(cardio_activity_id)` | `cardio_activities(id)` | NO ACTION | CASCADE |
| `cardio_recovery_tests(cardio_activity_id)` | `cardio_activities(id)` | NO ACTION | CASCADE |
| `daily_heart_rate(user_id)` | `user(id)` | NO ACTION | CASCADE |
| `daily_sleep(user_id)` | `user(id)` | NO ACTION | CASCADE |
| `daily_steps(user_id)` | `user(id)` | NO ACTION | CASCADE |
| `exercise_sets(exercise_id)` | `exercise_table(id)` | NO ACTION | RESTRICT |
| `exercise_sets(session_id)` | `workout_sessions(id)` | NO ACTION | CASCADE |
| `food_nutrients(food_id)` | `foods(id)` | NO ACTION | NO ACTION |
| `food_nutrients(nutrient_id)` | `nutrients(id)` | NO ACTION | NO ACTION |
| `food_portions(food_id)` | `foods(id)` | NO ACTION | NO ACTION |
| `foods(parent_food_id)` | `foods(id)` | NO ACTION | NO ACTION |
| `foods(source_id)` | `food_sources(id)` | NO ACTION | NO ACTION |
| `hourly_heart_rate(daily_heart_rate_id)` | `daily_heart_rate(id)` | NO ACTION | CASCADE |
| `hourly_steps(daily_steps_id)` | `daily_steps(id)` | NO ACTION | CASCADE |
| `intervention_outcome_metric(intervention_id)` | `interventions(id)` | NO ACTION | CASCADE |
| `intervention_periods(intervention_id)` | `interventions(id)` | NO ACTION | NO ACTION |
| `intervention_periods(source_log_entry_id)` | `log_entries(id)` | NO ACTION | NO ACTION |
| `intervention_periods(workout_session_id)` | `workout_sessions(id)` | NO ACTION | NO ACTION |
| `intervention_supplements(intervention_id)` | `interventions(id)` | NO ACTION | NO ACTION |
| `intervention_supplements(supplement_id)` | `supplements(id)` | NO ACTION | NO ACTION |
| `log_entries(parent_log_entry_id)` | `log_entries(id)` | NO ACTION | NO ACTION |
| `log_entries(portion_id)` | `food_portions(id)` | NO ACTION | NO ACTION |
| `log_entry_nutrients(log_entry_id)` | `log_entries(id)` | NO ACTION | CASCADE |
| `log_entry_nutrients(nutrient_id)` | `nutrients(id)` | NO ACTION | RESTRICT |
| `morning_hrv(user_id)` | `user(id)` | NO ACTION | CASCADE |
| `sleep_segments(daily_sleep_id)` | `daily_sleep(id)` | NO ACTION | CASCADE |
| `supplement_nutrients(nutrient_id)` | `nutrients(id)` | NO ACTION | NO ACTION |
| `supplement_nutrients(supplement_id)` | `supplements(id)` | NO ACTION | NO ACTION |
| `supplements(parent_supplement_id)` | `supplements(id)` | NO ACTION | NO ACTION |
| `workout_sessions(user_id)` | `user(id)` | NO ACTION | CASCADE |

## brain-lab

| Child columns | Parent columns | On update | On delete |
|---|---|---|---|
| `brain_assessment(hypothesis_id)` | `brain_hypothesis(id)` | NO ACTION | CASCADE |
| `brain_assessment(latest_evaluation_uuid)` | `brain_evaluation(uuid)` | NO ACTION | CASCADE |
| `brain_evaluation(hypothesis_id)` | `brain_hypothesis(id)` | NO ACTION | CASCADE |
| `brain_evaluation(supersedes_evaluation_uuid)` | `brain_evaluation(uuid)` | NO ACTION | SET NULL |
| `brain_evaluation_evidence(evaluation_id)` | `brain_evaluation(id)` | NO ACTION | CASCADE |
| `brain_evaluation_evidence(source_uuid)` | `intervention_periods(uuid)` | NO ACTION | CASCADE |
| `brain_hypothesis_intervention(hypothesis_id)` | `brain_hypothesis(id)` | NO ACTION | CASCADE |
| `brain_hypothesis_intervention(intervention_id)` | `interventions(id)` | NO ACTION | CASCADE |
| `brain_hypothesis_intervention(intervention_period_id, intervention_id)` | `intervention_periods(id, intervention_id)` | NO ACTION | CASCADE |
| `brain_hypothesis_metric(hypothesis_id)` | `brain_hypothesis(id)` | NO ACTION | CASCADE |
| `brain_memory_link(from_node_id)` | `brain_memory_node(id)` | NO ACTION | CASCADE |
| `brain_memory_link(source_evaluation_uuid)` | `brain_evaluation(uuid)` | NO ACTION | CASCADE |
| `brain_memory_link(to_node_id)` | `brain_memory_node(id)` | NO ACTION | CASCADE |
| `intervention_periods(intervention_id)` | `interventions(id)` | NO ACTION | NO ACTION |

The Brain evidence-to-evaluation foreign key is deferred until commit.
Polymorphic nutrition entity references and cross-file source lineage use application-level validation.
