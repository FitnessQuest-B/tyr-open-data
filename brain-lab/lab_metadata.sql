CREATE TABLE lab_source (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    lab_id TEXT NOT NULL,
    metadata_version INTEGER NOT NULL CHECK (metadata_version = 1),
    source_manifest_json TEXT NOT NULL CHECK (json_valid(source_manifest_json)),
    created_at INTEGER NOT NULL
);

CREATE TABLE lab_run (
    run_key TEXT PRIMARY KEY NOT NULL,
    hypothesis_uuid TEXT NOT NULL REFERENCES brain_hypothesis(uuid),
    evaluation_uuid TEXT NOT NULL UNIQUE REFERENCES brain_evaluation(uuid),
    plan_json TEXT NOT NULL CHECK (json_valid(plan_json)),
    result_sha256 TEXT NOT NULL,
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    assessment_json TEXT NOT NULL CHECK (json_valid(assessment_json)),
    recorded_at INTEGER NOT NULL
);

CREATE TRIGGER lab_source_immutable_update
BEFORE UPDATE ON lab_source
BEGIN SELECT RAISE(ABORT, 'Lab source binding is immutable'); END;

CREATE TRIGGER lab_source_immutable_delete
BEFORE DELETE ON lab_source
BEGIN SELECT RAISE(ABORT, 'Lab source binding is immutable'); END;

CREATE TRIGGER lab_source_no_replacement
BEFORE INSERT ON lab_source WHEN EXISTS (SELECT 1 FROM lab_source)
BEGIN SELECT RAISE(ABORT, 'Lab source binding already exists'); END;

CREATE TRIGGER lab_run_immutable_update
BEFORE UPDATE ON lab_run
BEGIN SELECT RAISE(ABORT, 'Lab run records are append-only'); END;

CREATE TRIGGER lab_run_immutable_delete
BEFORE DELETE ON lab_run
BEGIN SELECT RAISE(ABORT, 'Lab run records are append-only'); END;

CREATE TRIGGER lab_run_no_replacement
BEFORE INSERT ON lab_run
WHEN EXISTS (SELECT 1 FROM lab_run WHERE run_key = NEW.run_key OR evaluation_uuid = NEW.evaluation_uuid)
BEGIN SELECT RAISE(ABORT, 'Lab run already exists'); END;
