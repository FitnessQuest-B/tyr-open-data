PRAGMA query_only = ON;

-- Replace the owner and civil bounds for an authorized projected records file.
-- The end day is exclusive. The calendar makes absent days visible.
WITH RECURSIVE
    parameters(user_id, first_day, end_day) AS (
        VALUES (1, '2025-01-01', '2025-01-08')
    ),
    calendar(day) AS (
        SELECT first_day FROM parameters WHERE first_day < end_day
        UNION ALL
        SELECT date(day, '+1 day') FROM calendar, parameters
        WHERE date(day, '+1 day') < end_day
    )
SELECT
    count(calendar.day) AS expected_days,
    count(snapshot.snapshot_date) AS snapshot_days,
    count(CASE WHEN snapshot.sleep_data_coverage_pct > 0
               THEN snapshot.total_sleep_minutes END) AS observed_sleep_days,
    avg(CASE WHEN snapshot.sleep_data_coverage_pct > 0
             THEN snapshot.total_sleep_minutes END) AS mean_observed_sleep_minutes,
    count(snapshot.caffeine_mg) AS recorded_caffeine_days,
    count(CASE WHEN snapshot.caffeine_mg = 0 THEN 1 END) AS recorded_zero_caffeine_days
FROM calendar CROSS JOIN parameters
LEFT JOIN daily_snapshot AS snapshot
    ON snapshot.user_id = parameters.user_id
   AND snapshot.snapshot_date = calendar.day;
