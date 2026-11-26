"""Write fictional observations into the versioned TYR records projection."""

from datetime import timedelta

from create_empty import create_empty
from schema_support import clean_connect, digest, load_contract, quote, schema_objects
from synthetic_model import local_instant, day_key

SOURCE = "tyrDevice"

# Every reference value is authored for this generator.
NUTRIENTS = (
    (1, "CALORIES", "Energy", "kcal"),
    (2, "PROTEIN", "Protein", "g"),
    (3, "CARBS", "Carbohydrate", "g"),
    (4, "FAT", "Fat", "g"),
    (5, "CAFFEINE", "Caffeine", "mg"),
    (6, "MAGNESIUM", "Magnesium", "mg"),
)
FOODS = (
    (1, "Synthetic grain bowl", 100.0, "Synthetic portion", 310.0, {1: 154, 2: 8, 3: 21, 4: 4, 5: 0}),
    (2, "Synthetic fruit bowl", 100.0, "Synthetic portion", 270.0, {1: 135, 2: 4, 3: 24, 4: 3, 5: 0}),
    (3, "Synthetic caffeine drink", 250.0, "Synthetic drink", 250.0, {1: 2, 2: 0, 3: 0, 4: 0, 5: 80}),
)


def insert(db, table, **values):
    columns = ", ".join(map(quote, values))
    placeholders = ", ".join("?" for _ in values)
    db.execute(f"INSERT INTO {quote(table)} ({columns}) VALUES ({placeholders})", tuple(values.values()))


def load_reference_data(db):
    insert(db, "user", id=1)
    insert(db, "body_measurement_point", id=1, key="waist", name="Waist")
    insert(db, "exercise_table", id=1, name_key="synthetic_goblet_squat", system_created=0,
           category="strength", equipment_type="kettlebell", per_dumbbell=0)
    insert(db, "exercise_table", id=2, name_key="synthetic_stationary_bike", system_created=0,
           category="cardio", equipment_type="bike", per_dumbbell=0)
    insert(db, "food_sources", id=1, code="SYNTHETIC")
    for nid, code, name, unit in NUTRIENTS:
        insert(db, "nutrients", id=nid, code=code, name=name, unit=unit, category="synthetic",
               is_trackable=1, is_custom=1)
    for fid, name, base, portion_name, portion_grams, amounts in FOODS:
        insert(db, "foods", id=fid, name=name, source_id=1, is_custom=1,
               default_gram_weight=base, is_deleted=0)
        insert(db, "food_portions", id=fid, food_id=fid, description=portion_name,
               gram_weight=portion_grams, is_base=int(base == portion_grams), sort_order=0, is_available=1)
        for nutrient, amount in amounts.items():
            insert(db, "food_nutrients", food_id=fid, nutrient_id=nutrient,
                   amount_per_base_unit=amount, coverage_status="COMPLETE")
    insert(db, "supplements", id=1, name="Synthetic mineral capsule", form="capsule",
           category_key="minerals", is_custom=1, dose_amount=1.0, dose_unit="capsule", is_deleted=0)
    insert(db, "supplement_nutrients", supplement_id=1, nutrient_id=6, amount_per_dose=40.0)


def write_food_log(db, row_id, day, food, minute, meal_type, portions):
    fid, _, base_grams, _, portion_grams, composition = food
    consumed = round(portion_grams * portions, 2)
    amounts = {nutrient: round(amount * consumed / base_grams, 4)
               for nutrient, amount in composition.items()}
    insert(db, "log_entries", id=row_id, user_id=1, day_key=day_key(day.civil),
           logged_at=local_instant(day.civil, minute, day.offset), entity_type="FOOD", entity_id=fid,
           quantity_kind="PORTION", quantity=portions, portion_id=fid, meal_type=meal_type,
           source_type="MANUAL", meal_modifier_operation="NORMAL", consumed_grams_snapshot=consumed,
           consumed_grams_basis="ESTIMATED" if fid != 3 else "EXACT",
           nutrient_coverage_snapshot="COMPLETE", calories_kcal=amounts[1], protein_g=amounts[2],
           carbs_g=amounts[3], fat_g=amounts[4], caffeine_mg=amounts[5])
    for nutrient, amount in amounts.items():
        insert(db, "log_entry_nutrients", log_entry_id=row_id, nutrient_id=nutrient,
               amount=amount, coverage_status="COMPLETE")
    return amounts


def write_nutrition(db, day):
    if "nutrition" in day.omitted:
        return {}
    row_id = day.index * 10
    dose_minute = 1020 if day.late_dose else 630
    events = (
        (FOODS[1], 480, "breakfast", day.serving_factor),
        (FOODS[0], 750, "lunch", round(1.5 * day.serving_factor, 2)),
        (FOODS[0], 1140, "dinner", round(1.85 * day.serving_factor, 2)),
        (FOODS[2], dose_minute, "snack", day.dose_factor),
    )
    totals = {key: 0.0 for key in range(1, 6)}
    for slot, event in enumerate(events, start=1):
        amounts = write_food_log(db, row_id + slot, day, *event)
        for nutrient, amount in amounts.items():
            totals[nutrient] += amount
    if day.index % 3 == 0:
        insert(db, "log_entries", id=row_id + 5, user_id=1, day_key=day_key(day.civil),
               logged_at=local_instant(day.civil, 480, day.offset), entity_type="SUPPLEMENT",
               entity_id=1, quantity_kind="DOSE", quantity=1.0, meal_type="unspecified",
               source_type="MANUAL", meal_modifier_operation="NORMAL", nutrient_coverage_snapshot="COMPLETE")
        insert(db, "log_entry_nutrients", log_entry_id=row_id + 5, nutrient_id=6, amount=40.0,
               coverage_status="COMPLETE")
    return {
        **{field: round(totals[key], 4) for key, field in (
            (1, "caloric_intake"), (2, "protein_grams"), (3, "carbs_grams"), (4, "fat_grams"), (5, "caffeine_mg"))},
        "caffeine_last_dose_minute": dose_minute,
        "logged_meal_count": 4, "nutrition_data_coverage_pct": 100.0,
        "eating_window_start_minute": 480, "eating_window_end_minute": 1140, "eating_window_minutes": 660,
    }


def write_workout(db, day, identifier):
    if not day.workout:
        return {
            "workout_session_count": 0, "workout_minutes": 0, "cardio_minutes": 0,
            "strength_volume_load": 0.0, "strength_working_sets": 0, "strength_failure_sets": 0,
        }
    start = local_instant(day.civil, 1080, day.offset)
    load = 22 + 2 * (day.index % 5)
    insert(db, "workout_sessions", id=identifier, user_id=1, started_at=start,
           ended_at=start + 2700, perceived_exertion=6, source="manual", confidence=100)
    for ix in range(3):
        insert(db, "exercise_sets", id=day.index * 10 + ix + 1, session_id=identifier,
               exercise_id=1, set_index=ix, set_type="normal", reps=8, load_kg=load, rpe=6.0 + ix,
               performed_at=start + 180 * (ix + 1), source="manual", confidence=100)
    cardio_start = start + 900
    insert(db, "cardio_activities", id=identifier, session_id=identifier, exercise_id=2,
           activity_type="bike", started_at=cardio_start, ended_at=cardio_start + 1500,
           duration_sec=1500, distance_m=5500, source="manual", capture_mode="manual", confidence=100)
    return {
        "workout_session_count": 1, "workout_minutes": 45, "cardio_minutes": 25,
        "strength_volume_load": float(load * 24), "strength_working_sets": 3, "strength_failure_sets": 0,
    }


def clock_minute(stamp, offset):
    return (stamp // 60 + offset) % 1440


def write_sleep(db, previous):
    """Write the previous exposure day's night under its subsequent wake date."""
    wake_date = previous.civil + timedelta(days=1)
    identifier = previous.index + 2
    end = local_instant(wake_date, previous.wake_minute, previous.wake_offset)
    total = previous.sleep_minutes
    start = end - 60 * total
    mid = start + 30 * total
    transition = local_instant(wake_date, offset=previous.wake_offset)
    start_offset = previous.offset if start < transition else previous.wake_offset
    mid_offset = previous.offset if mid < transition else previous.wake_offset
    deep = total * 22 // 100
    rem = total * 24 // 100
    light = total - deep - rem
    clocks = {
        "bedtime_minute": clock_minute(start, start_offset),
        "wake_minute": clock_minute(end, previous.wake_offset),
        "sleep_midpoint_minute": clock_minute(mid, mid_offset),
    }
    insert(db, "daily_sleep", id=identifier, user_id=1, date=local_instant(wake_date),
           total_minutes=total, stage_quality="complete", source=SOURCE, sleep_start=start, sleep_end=end,
           sleep_start_minute=clocks["bedtime_minute"], sleep_end_minute=clocks["wake_minute"],
           sleep_midpoint_minute=clocks["sleep_midpoint_minute"], deep_minutes=deep,
           light_minutes=light, rem_minutes=rem)
    cursor = start
    for slot, (stage, duration) in enumerate((
        ("light", light // 2), ("deep", deep), ("light", light - light // 2), ("rem", rem)
    ), start=1):
        next_stamp = cursor + duration * 60
        insert(db, "sleep_segments", id=previous.index * 10 + slot, daily_sleep_id=identifier,
               start=cursor, end=next_stamp, stage=stage, duration_minutes=duration)
        cursor = next_stamp
    return {
        **clocks, "total_sleep_minutes": total, "deep_sleep_minutes": deep, "light_sleep_minutes": light,
        "rem_sleep_minutes": rem, "deep_sleep_pct": round(100 * deep / total, 6),
        "rem_sleep_pct": round(100 * rem / total, 6), "sleep_data_coverage_pct": 100.0,
    }


def write_observations(db, days):
    load_reference_data(db)
    for day in days:
        identifier = day.index + 1
        date_anchor = local_instant(day.civil)
        snapshot = {
            **write_workout(db, day, identifier),
            **write_nutrition(db, day),
        }
        if day.index > 0 and "sleep" not in days[day.index - 1].omitted:
            snapshot.update(write_sleep(db, days[day.index - 1]))
        if "weight" not in day.omitted:
            measured_at = local_instant(day.civil, 450, day.offset)
            insert(db, "body_weight", id=identifier, user_id=1, weight_kg=day.weight_kg,
                   measured_at=measured_at, source="manual")
            snapshot["body_weight"] = day.weight_kg
            if day.index % 14 == 0:
                insert(db, "body_measurement", id=identifier, user_id=1, point_id=1,
                       value_cm=round(0.78 * day.weight_kg + 22, 1), measured_at=measured_at)
        if "steps" not in day.omitted:
            insert(db, "daily_steps", id=identifier, user_id=1, date=date_anchor,
                   total_steps=day.steps, source=SOURCE)
            snapshot.update(total_steps=day.steps, step_data_coverage_pct=100.0)
            for ix, (hour, share) in enumerate(((8, 0.06), (12, 0.12), (18, 0.17)), start=1):
                insert(db, "hourly_steps", id=day.index * 10 + ix, daily_steps_id=identifier,
                       hour=hour, steps=int(day.steps * share))
        if "heart_rate" not in day.omitted:
            resting = day.resting_bpm
            insert(db, "daily_heart_rate", id=identifier, user_id=1, date=date_anchor,
                   avg_bpm=resting + 12.0, min_bpm=resting - 4.0,
                   max_bpm=resting + (66.0 if day.workout else 38.0), resting_bpm=resting,
                   sample_count=60, source=SOURCE)
            snapshot["heart_rate_data_coverage_pct"] = 100.0
        if day.index > 0 and "hrv" not in day.omitted:
            # HRV on this wake day depends on the preceding simulated night's duration.
            insert(db, "morning_hrv", id=identifier, user_id=1, date=date_anchor,
                   measured_at=local_instant(day.civil, 480, day.offset),
                   value_ms=days[day.index - 1].hrv_ms, metric="rmssd", source=SOURCE)
        # Version zero identifies synthetic, partial calculations. It is common to all scenarios.
        insert(db, "daily_snapshot", id=identifier, user_id=1, snapshot_date=day.civil.isoformat(),
               snapshot_version=1, calculation_version=0,
               computed_at=local_instant(day.civil + timedelta(days=2)), **snapshot)


def records_summary(db, contract):
    artifact = contract["artifacts"]["records"]
    if (
        db.execute("PRAGMA application_id").fetchone() != (artifact["application_id"],)
        or db.execute("PRAGMA user_version").fetchone() != (artifact["file_schema_version"],)
        or schema_objects(db) != artifact["objects"]
    ):
        raise ValueError("Generated records do not match the versioned projection")
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("Synthetic database integrity check failed")
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("Synthetic database contains an invalid foreign key")
    counts = {}
    hashes = {}
    for table, profile in contract["export_projections"].items():
        projection = ", ".join(map(quote, profile["columns"]))
        keys = ", ".join(map(quote, profile["primary_key"]))
        rows = db.execute(f"SELECT {projection} FROM {quote(table)} ORDER BY {keys}").fetchall()
        counts[table] = len(rows)
        hashes[table] = digest(rows)
    return counts, digest({"objects": artifact["objects"], "tables": hashes})


def build_records(destination, days):
    _, contract = load_contract("0.1.0")
    create_empty("records", destination, version=contract["specification_version"])
    with clean_connect(destination) as db:
        db.execute("PRAGMA foreign_keys=ON")
        with db:
            write_observations(db, days)
        counts, logical_hash = records_summary(db, contract)
        if counts["daily_snapshot"] != len(days):
            raise ValueError("Every generated calendar day must have one daily snapshot")
    return contract, counts, logical_hash
