-- TYR Open Data 0.1.0, generated from approved v92 schema objects.
PRAGMA application_id=1415139908;
PRAGMA user_version=1;

CREATE TABLE "user" (
    "id" INTEGER NOT NULL,
    PRIMARY KEY ("id")
);

CREATE TABLE "body_measurement_point" (
    "id" INTEGER NOT NULL,
    "key" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    PRIMARY KEY ("id"),
    UNIQUE ("key")
);

CREATE TABLE "body_measurement" (
    "id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "deleted_at" INTEGER,
    "point_id" INTEGER NOT NULL,
    "value_cm" REAL NOT NULL,
    "measured_at" INTEGER NOT NULL,
    PRIMARY KEY ("id"),
    UNIQUE ("user_id", "point_id", "measured_at"),
    CHECK ("value_cm" >= 0),
    FOREIGN KEY ("point_id") REFERENCES "body_measurement_point" ("id") ON UPDATE NO ACTION ON DELETE RESTRICT,
    FOREIGN KEY ("user_id") REFERENCES "user" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "body_weight" (
    "id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "weight_kg" REAL NOT NULL,
    "measured_at" INTEGER NOT NULL,
    "source" TEXT NOT NULL,
    "deleted_at" INTEGER,
    PRIMARY KEY ("id"),
    FOREIGN KEY ("user_id") REFERENCES "user" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "exercise_table" (
    "id" INTEGER NOT NULL,
    "name_key" TEXT NOT NULL,
    "system_created" INTEGER NOT NULL,
    "category" TEXT NOT NULL,
    "equipment_type" TEXT NOT NULL,
    "stretch_metric_pref" TEXT,
    "per_dumbbell" INTEGER NOT NULL,
    PRIMARY KEY ("id"),
    UNIQUE ("name_key"),
    CHECK ("system_created" IN (0, 1)),
    CHECK ("per_dumbbell" IN (0, 1))
);

CREATE TABLE "workout_sessions" (
    "id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "started_at" INTEGER NOT NULL,
    "ended_at" INTEGER,
    "perceived_exertion" INTEGER,
    "source" TEXT NOT NULL,
    "confidence" INTEGER NOT NULL,
    "deleted_at" INTEGER,
    PRIMARY KEY ("id"),
    FOREIGN KEY ("user_id") REFERENCES "user" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "exercise_sets" (
    "id" INTEGER NOT NULL,
    "session_id" INTEGER NOT NULL,
    "exercise_id" INTEGER NOT NULL,
    "set_index" INTEGER NOT NULL,
    "superset_group" INTEGER,
    "set_type" TEXT,
    "reps" INTEGER,
    "load_kg" REAL,
    "distance_m" REAL,
    "duration_sec" INTEGER,
    "working_one_rep_max_kg_at_log" REAL,
    "avg_speed_kmh" REAL,
    "avg_power_w" REAL,
    "avg_cadence_rpm" REAL,
    "incline" REAL,
    "resistance" REAL,
    "rpe" REAL,
    "performed_at" INTEGER,
    "source" TEXT NOT NULL,
    "confidence" INTEGER NOT NULL,
    PRIMARY KEY ("id"),
    UNIQUE ("session_id", "set_index"),
    FOREIGN KEY ("exercise_id") REFERENCES "exercise_table" ("id") ON UPDATE NO ACTION ON DELETE RESTRICT,
    FOREIGN KEY ("session_id") REFERENCES "workout_sessions" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "cardio_activities" (
    "id" INTEGER NOT NULL,
    "session_id" INTEGER NOT NULL,
    "exercise_id" INTEGER,
    "activity_type" TEXT NOT NULL,
    "started_at" INTEGER NOT NULL,
    "ended_at" INTEGER,
    "duration_sec" INTEGER,
    "distance_m" REAL,
    "source" TEXT NOT NULL,
    "capture_mode" TEXT NOT NULL,
    "confidence" INTEGER NOT NULL,
    "deleted_at" INTEGER,
    PRIMARY KEY ("id"),
    FOREIGN KEY ("exercise_id") REFERENCES "exercise_table" ("id") ON UPDATE NO ACTION ON DELETE SET NULL,
    FOREIGN KEY ("session_id") REFERENCES "workout_sessions" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "cardio_activity_summaries" (
    "id" INTEGER NOT NULL,
    "cardio_activity_id" INTEGER NOT NULL,
    "duration_sec" INTEGER,
    "distance_m" REAL,
    "calories_total" REAL,
    "avg_hr_bpm" REAL,
    "max_hr_bpm" INTEGER,
    "median_hr_bpm" REAL,
    "min_hr_bpm" INTEGER,
    "hr_coverage_pct" REAL,
    "zone1_sec" INTEGER NOT NULL,
    "zone2_sec" INTEGER NOT NULL,
    "zone3_sec" INTEGER NOT NULL,
    "zone4_sec" INTEGER NOT NULL,
    "zone5_sec" INTEGER NOT NULL,
    "avg_speed_kmh" REAL,
    "max_speed_kmh" REAL,
    "avg_power_w" REAL,
    "max_power_w" REAL,
    "avg_cadence_rpm" REAL,
    "avg_incline" REAL,
    "avg_resistance" REAL,
    "elevation_gain_m" REAL,
    "machine_coverage_pct" REAL,
    "calculation_version" INTEGER NOT NULL,
    "computed_at" INTEGER NOT NULL,
    PRIMARY KEY ("id"),
    UNIQUE ("cardio_activity_id"),
    FOREIGN KEY ("cardio_activity_id") REFERENCES "cardio_activities" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "cardio_recovery_tests" (
    "id" INTEGER NOT NULL,
    "cardio_activity_id" INTEGER NOT NULL,
    "measured_at" INTEGER NOT NULL,
    "test_type" TEXT NOT NULL,
    "recovery60_sec_bpm_drop" INTEGER,
    "recovery120_sec_bpm_drop" INTEGER,
    PRIMARY KEY ("id"),
    UNIQUE ("cardio_activity_id", "test_type"),
    FOREIGN KEY ("cardio_activity_id") REFERENCES "cardio_activities" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "daily_steps" (
    "id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "date" INTEGER NOT NULL,
    "total_steps" INTEGER NOT NULL,
    "source" TEXT NOT NULL,
    "deleted_at" INTEGER,
    PRIMARY KEY ("id"),
    UNIQUE ("user_id", "date"),
    FOREIGN KEY ("user_id") REFERENCES "user" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "hourly_steps" (
    "id" INTEGER NOT NULL,
    "daily_steps_id" INTEGER NOT NULL,
    "hour" INTEGER NOT NULL,
    "steps" INTEGER NOT NULL,
    "deleted_at" INTEGER,
    PRIMARY KEY ("id"),
    UNIQUE ("daily_steps_id", "hour"),
    FOREIGN KEY ("daily_steps_id") REFERENCES "daily_steps" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "daily_heart_rate" (
    "id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "date" INTEGER NOT NULL,
    "avg_bpm" REAL NOT NULL,
    "min_bpm" REAL,
    "max_bpm" REAL,
    "resting_bpm" INTEGER,
    "sample_count" INTEGER NOT NULL,
    "source" TEXT NOT NULL,
    "deleted_at" INTEGER,
    PRIMARY KEY ("id"),
    UNIQUE ("user_id", "date"),
    FOREIGN KEY ("user_id") REFERENCES "user" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "hourly_heart_rate" (
    "id" INTEGER NOT NULL,
    "daily_heart_rate_id" INTEGER NOT NULL,
    "hour" INTEGER NOT NULL,
    "avg_bpm" REAL NOT NULL,
    "min_bpm" REAL,
    "max_bpm" REAL,
    "sample_count" INTEGER NOT NULL,
    "deleted_at" INTEGER,
    PRIMARY KEY ("id"),
    UNIQUE ("daily_heart_rate_id", "hour"),
    FOREIGN KEY ("daily_heart_rate_id") REFERENCES "daily_heart_rate" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "daily_sleep" (
    "id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "date" INTEGER NOT NULL,
    "total_minutes" INTEGER NOT NULL,
    "deep_minutes" INTEGER,
    "light_minutes" INTEGER,
    "rem_minutes" INTEGER,
    "awake_minutes" INTEGER,
    "stage_quality" TEXT NOT NULL,
    "sleep_start" INTEGER,
    "sleep_end" INTEGER,
    "sleep_start_minute" INTEGER,
    "sleep_end_minute" INTEGER,
    "sleep_midpoint_minute" INTEGER,
    "source" TEXT NOT NULL,
    "deleted_at" INTEGER,
    PRIMARY KEY ("id"),
    UNIQUE ("user_id", "date"),
    FOREIGN KEY ("user_id") REFERENCES "user" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "sleep_segments" (
    "id" INTEGER NOT NULL,
    "daily_sleep_id" INTEGER NOT NULL,
    "start" INTEGER NOT NULL,
    "end" INTEGER NOT NULL,
    "stage" TEXT NOT NULL,
    "duration_minutes" INTEGER NOT NULL,
    "deleted_at" INTEGER,
    PRIMARY KEY ("id"),
    FOREIGN KEY ("daily_sleep_id") REFERENCES "daily_sleep" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "morning_hrv" (
    "id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "date" INTEGER NOT NULL,
    "measured_at" INTEGER NOT NULL,
    "value_ms" REAL NOT NULL,
    "metric" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "deleted_at" INTEGER,
    PRIMARY KEY ("id"),
    UNIQUE ("user_id", "date"),
    FOREIGN KEY ("user_id") REFERENCES "user" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "food_sources" (
    "id" INTEGER NOT NULL,
    "code" TEXT NOT NULL,
    PRIMARY KEY ("id"),
    UNIQUE ("code")
);

CREATE TABLE "foods" (
    "id" INTEGER NOT NULL,
    "name" TEXT NOT NULL,
    "source_id" INTEGER NOT NULL,
    "is_custom" INTEGER NOT NULL,
    "parent_food_id" INTEGER,
    "default_gram_weight" REAL NOT NULL,
    "is_deleted" INTEGER NOT NULL,
    PRIMARY KEY ("id"),
    CHECK ("is_custom" IN (0, 1)),
    CHECK ("is_deleted" IN (0, 1)),
    FOREIGN KEY ("parent_food_id") REFERENCES "foods" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION,
    FOREIGN KEY ("source_id") REFERENCES "food_sources" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION
);

CREATE TABLE "food_nutrients" (
    "food_id" INTEGER NOT NULL,
    "nutrient_id" INTEGER NOT NULL,
    "amount_per_base_unit" REAL NOT NULL,
    "coverage_status" TEXT NOT NULL,
    PRIMARY KEY ("food_id", "nutrient_id"),
    FOREIGN KEY ("food_id") REFERENCES "foods" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION,
    FOREIGN KEY ("nutrient_id") REFERENCES "nutrients" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION
);

CREATE TABLE "food_portions" (
    "id" INTEGER NOT NULL,
    "food_id" INTEGER NOT NULL,
    "description" TEXT NOT NULL,
    "gram_weight" REAL NOT NULL,
    "is_base" INTEGER NOT NULL,
    "sort_order" INTEGER NOT NULL,
    "is_available" INTEGER NOT NULL,
    PRIMARY KEY ("id"),
    UNIQUE ("food_id", "description"),
    CHECK ("is_base" IN (0, 1)),
    CHECK ("is_available" IN (0, 1)),
    FOREIGN KEY ("food_id") REFERENCES "foods" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION
);

CREATE TABLE "nutrients" (
    "id" INTEGER NOT NULL,
    "code" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "unit" TEXT NOT NULL,
    "category" TEXT NOT NULL,
    "is_trackable" INTEGER NOT NULL,
    "is_custom" INTEGER NOT NULL,
    PRIMARY KEY ("id"),
    UNIQUE ("code"),
    CHECK ("is_trackable" IN (0, 1)),
    CHECK ("is_custom" IN (0, 1))
);

CREATE TABLE "supplements" (
    "id" INTEGER NOT NULL,
    "name" TEXT NOT NULL,
    "form" TEXT,
    "category_key" TEXT NOT NULL,
    "is_custom" INTEGER NOT NULL,
    "parent_supplement_id" INTEGER,
    "dose_amount" REAL,
    "dose_unit" TEXT,
    "is_deleted" INTEGER NOT NULL,
    PRIMARY KEY ("id"),
    CHECK ("is_custom" IN (0, 1)),
    CHECK ("is_deleted" IN (0, 1)),
    FOREIGN KEY ("parent_supplement_id") REFERENCES "supplements" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION
);

CREATE TABLE "supplement_nutrients" (
    "supplement_id" INTEGER NOT NULL,
    "nutrient_id" INTEGER NOT NULL,
    "amount_per_dose" REAL,
    PRIMARY KEY ("supplement_id", "nutrient_id"),
    FOREIGN KEY ("nutrient_id") REFERENCES "nutrients" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION,
    FOREIGN KEY ("supplement_id") REFERENCES "supplements" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION
);

CREATE TABLE "log_entries" (
    "id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "day_key" INTEGER NOT NULL,
    "logged_at" INTEGER NOT NULL,
    "entity_type" TEXT NOT NULL,
    "entity_id" INTEGER,
    "quantity_kind" TEXT NOT NULL,
    "quantity" REAL NOT NULL,
    "portion_id" INTEGER,
    "meal_type" TEXT NOT NULL,
    "deleted_at" INTEGER,
    "source_type" TEXT NOT NULL,
    "parent_log_entry_id" INTEGER,
    "consumed_grams_snapshot" REAL,
    "consumed_grams_basis" TEXT,
    "nutrient_coverage_snapshot" TEXT,
    "calories_kcal" REAL,
    "protein_g" REAL,
    "fat_g" REAL,
    "carbs_g" REAL,
    "fiber_g" REAL,
    "sugar_g" REAL,
    "caffeine_mg" REAL,
    "meal_modifier_operation" TEXT NOT NULL,
    PRIMARY KEY ("id"),
    FOREIGN KEY ("parent_log_entry_id") REFERENCES "log_entries" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION,
    FOREIGN KEY ("portion_id") REFERENCES "food_portions" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION
);

CREATE TABLE "log_entry_nutrients" (
    "log_entry_id" INTEGER NOT NULL,
    "nutrient_id" INTEGER NOT NULL,
    "amount" REAL NOT NULL,
    "coverage_status" TEXT NOT NULL,
    PRIMARY KEY ("log_entry_id", "nutrient_id"),
    FOREIGN KEY ("log_entry_id") REFERENCES "log_entries" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
    FOREIGN KEY ("nutrient_id") REFERENCES "nutrients" ("id") ON UPDATE NO ACTION ON DELETE RESTRICT
);

CREATE TABLE "interventions" (
    "id" INTEGER NOT NULL,
    "uuid" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "category" TEXT,
    "intervention_type" TEXT NOT NULL,
    "is_custom" INTEGER NOT NULL,
    "is_deleted" INTEGER NOT NULL,
    PRIMARY KEY ("id"),
    UNIQUE ("uuid"),
    CHECK ("is_custom" IN (0, 1)),
    CHECK ("is_deleted" IN (0, 1))
);

CREATE TABLE "intervention_periods" (
    "id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "uuid" TEXT NOT NULL,
    "intervention_id" INTEGER NOT NULL,
    "started_at" INTEGER NOT NULL,
    "ended_at" INTEGER,
    "start_day_key" INTEGER NOT NULL,
    "end_day_key" INTEGER,
    "workout_session_id" INTEGER,
    "source_log_entry_id" INTEGER,
    "source_type" TEXT,
    "is_deleted" INTEGER NOT NULL,
    "deleted_at" INTEGER,
    PRIMARY KEY ("id"),
    UNIQUE ("id", "intervention_id"),
    UNIQUE ("uuid"),
    CHECK ("is_deleted" IN (0, 1)),
    FOREIGN KEY ("intervention_id") REFERENCES "interventions" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION,
    FOREIGN KEY ("source_log_entry_id") REFERENCES "log_entries" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION,
    FOREIGN KEY ("workout_session_id") REFERENCES "workout_sessions" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION
);

CREATE TABLE "intervention_outcome_metric" (
    "id" INTEGER NOT NULL,
    "intervention_id" INTEGER NOT NULL,
    "metric_key" TEXT NOT NULL,
    "expected_direction" TEXT NOT NULL,
    "is_primary" INTEGER NOT NULL,
    "expected_onset_days" INTEGER,
    "washout_days" INTEGER,
    "minimum_meaningful_change" REAL,
    "minimum_meaningful_change_unit" TEXT,
    "is_deleted" INTEGER NOT NULL,
    "deleted_at" INTEGER,
    PRIMARY KEY ("id"),
    CHECK ("is_primary" IN (0, 1)),
    CHECK ("is_deleted" IN (0, 1)),
    FOREIGN KEY ("intervention_id") REFERENCES "interventions" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);

CREATE TABLE "intervention_supplements" (
    "intervention_id" INTEGER NOT NULL,
    "supplement_id" INTEGER NOT NULL,
    "dose_amount" REAL,
    "dose_unit" TEXT,
    "frequency_per_day" REAL,
    PRIMARY KEY ("intervention_id", "supplement_id"),
    FOREIGN KEY ("intervention_id") REFERENCES "interventions" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION,
    FOREIGN KEY ("supplement_id") REFERENCES "supplements" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION
);

CREATE TABLE "daily_snapshot" (
    "id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "snapshot_date" TEXT NOT NULL,
    "snapshot_version" INTEGER NOT NULL,
    "calculation_version" INTEGER NOT NULL,
    "hrv_deviation_pct" REAL,
    "hrv_metric" TEXT,
    "hrv_baseline_sample_size" INTEGER,
    "hrv_baseline_coverage_pct" REAL,
    "bedtime_minute" INTEGER,
    "wake_minute" INTEGER,
    "sleep_midpoint_minute" INTEGER,
    "total_sleep_minutes" INTEGER,
    "deep_sleep_minutes" INTEGER,
    "rem_sleep_minutes" INTEGER,
    "light_sleep_minutes" INTEGER,
    "deep_sleep_pct" REAL,
    "rem_sleep_pct" REAL,
    "workout_session_count" INTEGER,
    "workout_minutes" INTEGER,
    "cardio_minutes" INTEGER,
    "strength_volume_load" REAL,
    "strength_working_sets" INTEGER,
    "strength_failure_sets" INTEGER,
    "caloric_intake" REAL,
    "protein_grams" REAL,
    "protein_per_kg_body_weight" REAL,
    "carbs_grams" REAL,
    "fat_grams" REAL,
    "caffeine_mg" REAL,
    "caffeine_last_dose_minute" INTEGER,
    "eating_window_start_minute" INTEGER,
    "eating_window_end_minute" INTEGER,
    "eating_window_minutes" INTEGER,
    "logged_meal_count" INTEGER,
    "meal_timing_sd_minutes14_day" REAL,
    "workout_timing_sd_minutes14_day" REAL,
    "total_steps" INTEGER,
    "sleep_data_coverage_pct" REAL,
    "heart_rate_data_coverage_pct" REAL,
    "step_data_coverage_pct" REAL,
    "nutrition_data_coverage_pct" REAL,
    "body_weight" REAL,
    "body_weight7_day_avg" REAL,
    "body_weight28_day_avg" REAL,
    "body_weight_trend7_vs28" REAL,
    "computed_at" INTEGER NOT NULL,
    PRIMARY KEY ("id"),
    UNIQUE ("user_id", "snapshot_date")
);

CREATE TABLE "baseline_metric" (
    "id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "metric_key" TEXT NOT NULL,
    "metric_domain" TEXT,
    "unit" TEXT,
    "window_days" INTEGER NOT NULL,
    "computed_date" TEXT NOT NULL,
    "mean" REAL,
    "median" REAL,
    "p25" REAL,
    "p75" REAL,
    "standard_deviation" REAL,
    "linear_slope" REAL,
    "min_value" REAL,
    "max_value" REAL,
    "sample_size" INTEGER NOT NULL,
    "coverage_pct" REAL,
    "coverage_status" TEXT,
    "meets_minimum_coverage" INTEGER NOT NULL,
    "first_observed_date" TEXT,
    "last_observed_date" TEXT,
    "excluded_day_count" INTEGER NOT NULL,
    "computed_at" INTEGER NOT NULL,
    PRIMARY KEY ("id"),
    UNIQUE ("user_id", "metric_key", "window_days", "computed_date"),
    CHECK ("meets_minimum_coverage" IN (0, 1))
);
