-- TYR Open Data 0.1.0, generated from approved v92 schema objects.
PRAGMA application_id=1415139906;
PRAGMA user_version=1;

CREATE TABLE "interventions" (
    "id" INTEGER NOT NULL,
    "uuid" TEXT NOT NULL,
    PRIMARY KEY ("id"),
    UNIQUE ("uuid")
);

CREATE TABLE "intervention_periods" (
    "id" INTEGER NOT NULL,
    "intervention_id" INTEGER NOT NULL,
    "uuid" TEXT NOT NULL,
    PRIMARY KEY ("id"),
    UNIQUE ("id", "intervention_id"),
    UNIQUE ("uuid"),
    FOREIGN KEY ("intervention_id") REFERENCES "interventions" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION
);

CREATE TABLE "brain_hypothesis" ("id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "uuid" TEXT NOT NULL CHECK(length(uuid) = 36 AND substr(uuid,9,1) = '-' AND substr(uuid,14,1) = '-' AND substr(uuid,19,1) = '-' AND substr(uuid,24,1) = '-' AND length(replace(uuid,'-','')) = 32 AND replace(uuid,'-','') NOT GLOB '*[^0-9a-f]*') UNIQUE, "title" TEXT NOT NULL, "statement" TEXT NOT NULL, "domain" TEXT NOT NULL, "hypothesis_type" TEXT NOT NULL, "claim_type" TEXT NOT NULL, "origin_type" TEXT NOT NULL, "origin_ref" TEXT NULL, "registered_at" INTEGER NOT NULL, "registration_mode" TEXT NOT NULL, "definition_version" INTEGER NOT NULL DEFAULT 1, "created_at" INTEGER NOT NULL DEFAULT (CAST(strftime('%s', CURRENT_TIMESTAMP) AS INTEGER)), "updated_at" INTEGER NOT NULL DEFAULT (CAST(strftime('%s', CURRENT_TIMESTAMP) AS INTEGER)), "archived_at" INTEGER NULL, CHECK (length(trim(title)) > 0 AND length(trim(statement)) > 0 AND length(trim(domain)) > 0), CHECK (typeof(registered_at) = 'integer'), CHECK (typeof(definition_version) = 'integer' AND definition_version > 0), CHECK (hypothesis_type IN ('intervention','association','descriptive')), CHECK (claim_type IN ('descriptive','association','causal')), CHECK (origin_type IN ('user','observation','imported','unknown')), CHECK (registration_mode IN ('prospective','retrospective','mixed','unknown')));

CREATE TABLE "brain_hypothesis_metric" ("id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "uuid" TEXT NOT NULL CHECK(length(uuid) = 36 AND substr(uuid,9,1) = '-' AND substr(uuid,14,1) = '-' AND substr(uuid,19,1) = '-' AND substr(uuid,24,1) = '-' AND length(replace(uuid,'-','')) = 32 AND replace(uuid,'-','') NOT GLOB '*[^0-9a-f]*') UNIQUE, "hypothesis_id" INTEGER NOT NULL REFERENCES brain_hypothesis (id) ON DELETE CASCADE, "metric_key" TEXT NOT NULL, "role" TEXT NOT NULL, "window_days" INTEGER NULL, "lag_days" INTEGER NULL, "condition_spec_json" TEXT NULL, "created_at" INTEGER NOT NULL DEFAULT (CAST(strftime('%s', CURRENT_TIMESTAMP) AS INTEGER)), CHECK (role IN ('exposure','outcome','confounder','modifier','context')), CHECK (window_days > 0), CHECK (condition_spec_json IS NULL OR CASE WHEN json_valid(condition_spec_json) THEN json_type(condition_spec_json, '$.version') IS 'integer' AND json_extract(condition_spec_json, '$.version') IS 1 AND json_type(condition_spec_json, '$.payload') IS 'object' ELSE 0 END));

CREATE TABLE "brain_hypothesis_intervention" ("id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "uuid" TEXT NOT NULL CHECK(length(uuid) = 36 AND substr(uuid,9,1) = '-' AND substr(uuid,14,1) = '-' AND substr(uuid,19,1) = '-' AND substr(uuid,24,1) = '-' AND length(replace(uuid,'-','')) = 32 AND replace(uuid,'-','') NOT GLOB '*[^0-9a-f]*') UNIQUE, "hypothesis_id" INTEGER NOT NULL REFERENCES brain_hypothesis (id) ON DELETE CASCADE, "intervention_id" INTEGER NOT NULL REFERENCES interventions (id) ON DELETE CASCADE, "intervention_period_id" INTEGER NULL, "relationship_role" TEXT NOT NULL, "created_at" INTEGER NOT NULL DEFAULT (CAST(strftime('%s', CURRENT_TIMESTAMP) AS INTEGER)), UNIQUE ("hypothesis_id", "intervention_id", "intervention_period_id", "relationship_role"), FOREIGN KEY (intervention_period_id, intervention_id) REFERENCES intervention_periods (id, intervention_id) ON DELETE CASCADE, CHECK (relationship_role IN ('exposure','comparator','context')));

CREATE TABLE "brain_evaluation" ("id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "uuid" TEXT NOT NULL CHECK(length(uuid) = 36 AND substr(uuid,9,1) = '-' AND substr(uuid,14,1) = '-' AND substr(uuid,19,1) = '-' AND substr(uuid,24,1) = '-' AND length(replace(uuid,'-','')) = 32 AND replace(uuid,'-','') NOT GLOB '*[^0-9a-f]*') UNIQUE, "hypothesis_id" INTEGER NOT NULL REFERENCES brain_hypothesis (id) ON DELETE CASCADE, "algorithm_id" TEXT NOT NULL, "algorithm_version" TEXT NOT NULL, "evaluation_mode" TEXT NOT NULL, "spec_registered_at" INTEGER NOT NULL, "test_window_start" INTEGER NOT NULL, "test_window_end" INTEGER NOT NULL, "executed_at" INTEGER NOT NULL, "spec_hash" TEXT NOT NULL, "specification_codec_version" INTEGER NOT NULL DEFAULT 1, "specification_json" TEXT NOT NULL, "input_manifest_hash" TEXT NULL, "reproducibility_level" TEXT NOT NULL, "supersedes_evaluation_uuid" TEXT NULL REFERENCES brain_evaluation (uuid) ON DELETE SET NULL, "primary_metric_key" TEXT NOT NULL, "effect_estimate" REAL NULL, "effect_unit" TEXT NULL, "interval_lower" REAL NULL, "interval_upper" REAL NULL, "interval_method" TEXT NULL, "interval_level" REAL NULL, "sample_count" INTEGER NULL, "coverage_ratio" REAL NULL, "evidence_decision" TEXT NOT NULL, "result_claim_type" TEXT NOT NULL, "failure_class" TEXT NULL, "limitations_code" TEXT NULL, "diagnostics_codec_version" INTEGER NULL, "diagnostics_json" TEXT NULL, "analysis_family_id" TEXT NULL, "validation_method" TEXT NULL, CHECK (length(trim(algorithm_id)) > 0 AND length(trim(algorithm_version)) > 0), CHECK (spec_registered_at <= executed_at AND test_window_start < test_window_end AND test_window_end <= executed_at), CHECK (length(spec_hash) = 64 AND spec_hash NOT GLOB '*[^0-9a-f]*'), CHECK (input_manifest_hash IS NULL OR (length(input_manifest_hash) = 64 AND input_manifest_hash NOT GLOB '*[^0-9a-f]*')), CHECK (evaluation_mode IN ('exploratory','confirmatory')), CHECK (reproducibility_level IN ('specification','fingerprinted','replayable')), CHECK (reproducibility_level = 'specification' OR input_manifest_hash IS NOT NULL), CHECK (evidence_decision IN ('supported','notSupported','inconclusive','adverse','conflicting')), CHECK (result_claim_type IN ('descriptive','association','causal')), CHECK (failure_class IN ('ineffective','adverse','insufficientData','methodLimitation')), CHECK (result_claim_type <> 'causal' OR (evaluation_mode = 'confirmatory' AND spec_registered_at < test_window_start AND nullif(trim(validation_method), '') IS NOT NULL)), CHECK (supersedes_evaluation_uuid <> uuid), CHECK (typeof(spec_registered_at) = 'integer' AND typeof(test_window_start) = 'integer' AND typeof(test_window_end) = 'integer' AND typeof(executed_at) = 'integer'), CHECK (sample_count IS NULL OR (typeof(sample_count) = 'integer' AND sample_count >= 0)), CHECK (coverage_ratio IS NULL OR (typeof(coverage_ratio) IN ('real','integer') AND coverage_ratio BETWEEN 0 AND 1)), CHECK ((effect_estimate IS NULL AND interval_lower IS NULL) OR nullif(trim(effect_unit), '') IS NOT NULL), CHECK (effect_estimate IS NULL OR (typeof(effect_estimate) IN ('real','integer') AND abs(effect_estimate) <= 1.7976931348623157e308)), CHECK ((interval_lower IS NULL) = (interval_upper IS NULL)), CHECK ((interval_lower IS NULL) = (interval_method IS NULL)), CHECK (interval_lower IS NULL OR (typeof(interval_lower) IN ('real','integer') AND typeof(interval_upper) IN ('real','integer') AND interval_lower <= interval_upper AND abs(interval_lower) <= 1.7976931348623157e308 AND abs(interval_upper) <= 1.7976931348623157e308)), CHECK (interval_level IS NULL OR (typeof(interval_level) IN ('real','integer') AND interval_lower IS NOT NULL AND interval_level > 0 AND interval_level <= 1)), CHECK (specification_codec_version = 1 AND CASE WHEN json_valid(specification_json) THEN json_type(specification_json, '$.version') IS 'integer' AND json_extract(specification_json, '$.version') IS 1 AND json_type(specification_json, '$.payload.hypothesis') IS 'object' AND json_type(specification_json, '$.payload.metricBindings') IS 'array' AND json_type(specification_json, '$.payload.interventionBindings') IS 'array' AND json_type(specification_json, '$.payload.interventionOutcomes') IS 'array' AND json_type(specification_json, '$.payload.analysisParameters') IS 'object' ELSE 0 END), CHECK ((diagnostics_codec_version IS NULL AND diagnostics_json IS NULL) OR (diagnostics_codec_version IS 1 AND CASE WHEN json_valid(diagnostics_json) THEN json_type(diagnostics_json, '$.version') IS 'integer' AND json_extract(diagnostics_json, '$.version') IS 1 AND json_type(diagnostics_json, '$.payload') IS 'object' ELSE 0 END)));

CREATE TABLE "brain_evaluation_evidence" ("id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "uuid" TEXT NOT NULL CHECK(length(uuid) = 36 AND substr(uuid,9,1) = '-' AND substr(uuid,14,1) = '-' AND substr(uuid,19,1) = '-' AND substr(uuid,24,1) = '-' AND length(replace(uuid,'-','')) = 32 AND replace(uuid,'-','') NOT GLOB '*[^0-9a-f]*') UNIQUE, "evaluation_id" INTEGER NOT NULL, "metric_key" TEXT NOT NULL, "metric_role" TEXT NOT NULL, "cohort_role" TEXT NOT NULL, "source_type" TEXT NOT NULL, "source_uuid" TEXT NULL REFERENCES intervention_periods (uuid) ON DELETE CASCADE, "window_start" INTEGER NOT NULL, "window_end" INTEGER NOT NULL, "sample_count" INTEGER NOT NULL, "expected_count" INTEGER NULL, "mean" REAL NULL, "standard_deviation" REAL NULL, "minimum" REAL NULL, "maximum" REAL NULL, "coverage_ratio" REAL NULL, "confidence_code" TEXT NULL, "canonical_unit" TEXT NOT NULL, "source_fingerprint" TEXT NULL, "extra_codec_version" INTEGER NULL, "extra_json" TEXT NULL, CHECK (metric_role IN ('exposure','outcome','confounder','modifier','context')), CHECK (cohort_role IN ('baseline','exposure','comparator','followUp','other')), CHECK (source_type IN ('dailySnapshot','rollingBaseline','measurement','interventionPeriod','aggregate')), FOREIGN KEY (evaluation_id) REFERENCES brain_evaluation (id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED, CHECK ((source_uuid IS NOT NULL) = (source_type = 'interventionPeriod')), CHECK (typeof(window_start) = 'integer' AND typeof(window_end) = 'integer' AND window_start < window_end), CHECK (typeof(sample_count) = 'integer' AND sample_count >= 0 AND (expected_count IS NULL OR (typeof(expected_count) = 'integer' AND expected_count > 0))), CHECK (coverage_ratio IS NULL OR (typeof(coverage_ratio) IN ('real','integer') AND coverage_ratio BETWEEN 0 AND 1)), CHECK (mean IS NULL OR (typeof(mean) IN ('real','integer') AND abs(mean) <= 1.7976931348623157e308)), CHECK (standard_deviation IS NULL OR (typeof(standard_deviation) IN ('real','integer') AND standard_deviation BETWEEN 0 AND 1.7976931348623157e308)), CHECK (minimum IS NULL OR (typeof(minimum) IN ('real','integer') AND abs(minimum) <= 1.7976931348623157e308)), CHECK (maximum IS NULL OR (typeof(maximum) IN ('real','integer') AND abs(maximum) <= 1.7976931348623157e308)), CHECK (minimum <= maximum), CHECK (minimum <= mean AND mean <= maximum), CHECK ((extra_codec_version IS NULL AND extra_json IS NULL) OR (extra_codec_version IS 1 AND CASE WHEN json_valid(extra_json) THEN json_type(extra_json, '$.version') IS 'integer' AND json_extract(extra_json, '$.version') IS 1 AND json_type(extra_json, '$.payload') IS 'object' ELSE 0 END)));

CREATE TABLE "brain_assessment" ("hypothesis_id" INTEGER NOT NULL REFERENCES brain_hypothesis (id) ON DELETE CASCADE, "evidence_decision" TEXT NOT NULL, "claim_strength" TEXT NOT NULL, "applicability" TEXT NOT NULL, "failure_disposition" TEXT NULL, "evidence_strength" TEXT NOT NULL, "latest_evaluation_uuid" TEXT NULL REFERENCES brain_evaluation (uuid) ON DELETE CASCADE, "policy_version" TEXT NOT NULL, "assessed_at" INTEGER NOT NULL, "review_reason_code" TEXT NULL, "validity_context_codec_version" INTEGER NULL, "validity_context_json" TEXT NULL, PRIMARY KEY ("hypothesis_id"), CHECK (evidence_decision IN ('unassessed','supported','notSupported','inconclusive','adverse','conflicting')), CHECK (claim_strength IN ('none','descriptive','association','causal')), CHECK (applicability IN ('unknown','current','historical','recheckRequired','notApplicable')), CHECK (failure_disposition IN ('ineffective','adverse','insufficientEvidence','methodLimited')), CHECK (evidence_strength IN ('none','weak','moderate','strong')), CHECK (length(trim(policy_version)) > 0), CHECK ((evidence_decision = 'unassessed') = (latest_evaluation_uuid IS NULL)), CHECK (evidence_decision <> 'unassessed' OR (claim_strength = 'none' AND evidence_strength = 'none')), CHECK (claim_strength <> 'causal' OR evidence_decision = 'supported'), CHECK ((validity_context_codec_version IS NULL AND validity_context_json IS NULL) OR (validity_context_codec_version IS 1 AND CASE WHEN json_valid(validity_context_json) THEN json_type(validity_context_json, '$.version') IS 'integer' AND json_extract(validity_context_json, '$.version') IS 1 AND json_type(validity_context_json, '$.payload') IS 'object' AND (json_type(validity_context_json, '$.payload.contextEventUuids') IS NULL OR json_type(validity_context_json, '$.payload.contextEventUuids') IS 'array') ELSE 0 END))) WITHOUT ROWID;

CREATE TABLE "brain_context_event" ("id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "uuid" TEXT NOT NULL CHECK(length(uuid) = 36 AND substr(uuid,9,1) = '-' AND substr(uuid,14,1) = '-' AND substr(uuid,19,1) = '-' AND substr(uuid,24,1) = '-' AND length(replace(uuid,'-','')) = 32 AND replace(uuid,'-','') NOT GLOB '*[^0-9a-f]*') UNIQUE, "context_type" TEXT NOT NULL, "started_at" INTEGER NOT NULL, "ended_at" INTEGER NULL, "source_type" TEXT NOT NULL, "source_ref" TEXT NULL, "certainty" TEXT NOT NULL, "notes" TEXT NULL, "created_at" INTEGER NOT NULL DEFAULT (CAST(strftime('%s', CURRENT_TIMESTAMP) AS INTEGER)), "updated_at" INTEGER NOT NULL DEFAULT (CAST(strftime('%s', CURRENT_TIMESTAMP) AS INTEGER)), "is_deleted" INTEGER NOT NULL DEFAULT 0 CHECK ("is_deleted" IN (0, 1)), "deleted_at" INTEGER NULL, CHECK (context_type IN ('illness','travel','medicationChange','scheduleDisruption','lifestyleTransition','other')), CHECK (source_type IN ('userReported','inferred','imported','unknown')), CHECK (certainty IN ('confirmed','reported','inferred','unknown')), CHECK (source_type <> 'inferred' OR certainty = 'inferred'), CHECK (certainty <> 'confirmed' OR source_type IN ('userReported','imported')), CHECK (ended_at >= started_at), CHECK (is_deleted = (deleted_at IS NOT NULL)));

CREATE TABLE "brain_memory_node" ("id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "uuid" TEXT NOT NULL CHECK(length(uuid) = 36 AND substr(uuid,9,1) = '-' AND substr(uuid,14,1) = '-' AND substr(uuid,19,1) = '-' AND substr(uuid,24,1) = '-' AND length(replace(uuid,'-','')) = 32 AND replace(uuid,'-','') NOT GLOB '*[^0-9a-f]*') UNIQUE, "node_type" TEXT NOT NULL, "source_entity_type" TEXT NULL, "source_entity_uuid" TEXT NULL, "title" TEXT NOT NULL, "summary" TEXT NULL, "retrieval_tier" TEXT NOT NULL, "review_state" TEXT NOT NULL, "summary_version" INTEGER NULL, "last_validated_at" INTEGER NULL, "created_at" INTEGER NOT NULL DEFAULT (CAST(strftime('%s', CURRENT_TIMESTAMP) AS INTEGER)), "updated_at" INTEGER NOT NULL DEFAULT (CAST(strftime('%s', CURRENT_TIMESTAMP) AS INTEGER)), "archived_at" INTEGER NULL, CHECK (node_type IN ('note','source')), CHECK (source_entity_type IN ('hypothesis','evaluation','contextEvent')), CHECK (retrieval_tier IN ('primary','secondary','archive')), CHECK (review_state IN ('unreviewed','verified','stale')), CHECK ((node_type = 'source') = (source_entity_type IS NOT NULL) AND (source_entity_type IS NULL) = (source_entity_uuid IS NULL)), CHECK ((summary IS NULL) = (summary_version IS NULL) AND summary_version > 0), CHECK (review_state <> 'verified' OR last_validated_at IS NOT NULL), CHECK (length(trim(title)) > 0));

CREATE TABLE "brain_memory_link" ("id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "uuid" TEXT NOT NULL CHECK(length(uuid) = 36 AND substr(uuid,9,1) = '-' AND substr(uuid,14,1) = '-' AND substr(uuid,19,1) = '-' AND substr(uuid,24,1) = '-' AND length(replace(uuid,'-','')) = 32 AND replace(uuid,'-','') NOT GLOB '*[^0-9a-f]*') UNIQUE, "from_node_id" INTEGER NOT NULL REFERENCES brain_memory_node (id) ON DELETE CASCADE, "to_node_id" INTEGER NOT NULL REFERENCES brain_memory_node (id) ON DELETE CASCADE, "relation_type" TEXT NOT NULL, "source_evaluation_uuid" TEXT NULL REFERENCES brain_evaluation (uuid) ON DELETE CASCADE, "is_active" INTEGER NOT NULL DEFAULT 1 CHECK ("is_active" IN (0, 1)), "link_version" INTEGER NOT NULL DEFAULT 1, "created_at" INTEGER NOT NULL DEFAULT (CAST(strftime('%s', CURRENT_TIMESTAMP) AS INTEGER)), UNIQUE ("from_node_id", "to_node_id", "relation_type"), CHECK (relation_type IN ('supports','contradicts','refines','dependsOn','relevantTo','supersedes','derivedFrom')), CHECK (from_node_id <> to_node_id), CHECK (link_version = 1));

CREATE INDEX brain_assessment_latest ON brain_assessment (latest_evaluation_uuid);

CREATE INDEX brain_context_event_timeline ON brain_context_event (is_deleted, started_at);

CREATE INDEX brain_context_event_type ON brain_context_event (context_type, started_at);

CREATE INDEX brain_evaluation_evidence_evaluation ON brain_evaluation_evidence (evaluation_id);

CREATE INDEX brain_evaluation_evidence_metric_role ON brain_evaluation_evidence (metric_key, metric_role);

CREATE INDEX brain_evaluation_evidence_source ON brain_evaluation_evidence (source_type, source_uuid);

CREATE INDEX brain_evaluation_history ON brain_evaluation (hypothesis_id, executed_at DESC, id DESC);

CREATE INDEX brain_evaluation_supersedes ON brain_evaluation (supersedes_evaluation_uuid);

CREATE INDEX brain_hypothesis_domain ON brain_hypothesis (domain, archived_at);

CREATE UNIQUE INDEX brain_hypothesis_intervention_binding ON brain_hypothesis_intervention (hypothesis_id, intervention_id, relationship_role) WHERE intervention_period_id IS NULL;

CREATE INDEX brain_hypothesis_intervention_hypothesis ON brain_hypothesis_intervention (hypothesis_id);

CREATE INDEX brain_hypothesis_intervention_period ON brain_hypothesis_intervention (intervention_period_id);

CREATE INDEX brain_hypothesis_intervention_target ON brain_hypothesis_intervention (intervention_id, intervention_period_id);

CREATE INDEX brain_hypothesis_metric_hypothesis ON brain_hypothesis_metric (hypothesis_id);

CREATE INDEX brain_hypothesis_metric_key_role ON brain_hypothesis_metric (metric_key, role);

CREATE UNIQUE INDEX brain_intervention_period_identity
    ON intervention_periods(id, intervention_id);

CREATE INDEX brain_memory_link_evaluation ON brain_memory_link (source_evaluation_uuid);

CREATE INDEX brain_memory_link_incoming ON brain_memory_link (to_node_id, is_active);

CREATE INDEX brain_memory_link_outgoing ON brain_memory_link (from_node_id, is_active);

CREATE UNIQUE INDEX brain_memory_link_symmetric ON brain_memory_link (min(from_node_id, to_node_id), max(from_node_id, to_node_id), relation_type) WHERE relation_type IN ('contradicts', 'relevantTo');

CREATE INDEX brain_memory_node_retrieval ON brain_memory_node (retrieval_tier, review_state, archived_at);

CREATE UNIQUE INDEX brain_memory_node_source ON brain_memory_node (source_entity_type, source_entity_uuid);

CREATE TRIGGER brain_assessment_validate_insert
      BEFORE INSERT ON brain_assessment
      BEGIN
            SELECT RAISE(ABORT, 'Assessment requires an active hypothesis')
    WHERE NOT EXISTS (
      SELECT 1 FROM brain_hypothesis
      WHERE id = NEW.hypothesis_id AND archived_at IS NULL
    );

    SELECT RAISE(ABORT, 'Assessment references incompatible evidence')
    WHERE NEW.latest_evaluation_uuid IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM brain_evaluation AS e
      WHERE e.uuid = NEW.latest_evaluation_uuid AND e.hypothesis_id = NEW.hypothesis_id
        AND e.executed_at <= NEW.assessed_at
        AND e.id = (SELECT latest.id FROM brain_evaluation AS latest
          WHERE latest.hypothesis_id = NEW.hypothesis_id
          ORDER BY latest.executed_at DESC, latest.id DESC LIMIT 1)
        AND (NEW.claim_strength <> 'causal'
          OR (e.result_claim_type = 'causal' AND e.evidence_decision = 'supported'))
    );

    SELECT RAISE(ABORT, 'Unresolved assessment context')
    WHERE EXISTS (
      SELECT 1 FROM json_each(NEW.validity_context_json, '$.payload.contextEventUuids') AS ref
      WHERE ref.type <> 'text' OR NOT EXISTS (
        SELECT 1 FROM brain_context_event WHERE uuid = ref.value AND is_deleted = 0
      )
    );
  
      END;

CREATE TRIGGER brain_assessment_validate_update
      BEFORE UPDATE ON brain_assessment
      BEGIN
            SELECT RAISE(ABORT, 'Assessment requires an active hypothesis')
    WHERE NOT EXISTS (
      SELECT 1 FROM brain_hypothesis
      WHERE id = NEW.hypothesis_id AND archived_at IS NULL
    );

    SELECT RAISE(ABORT, 'Assessment references incompatible evidence')
    WHERE NEW.latest_evaluation_uuid IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM brain_evaluation AS e
      WHERE e.uuid = NEW.latest_evaluation_uuid AND e.hypothesis_id = NEW.hypothesis_id
        AND e.executed_at <= NEW.assessed_at
        AND e.id = (SELECT latest.id FROM brain_evaluation AS latest
          WHERE latest.hypothesis_id = NEW.hypothesis_id
          ORDER BY latest.executed_at DESC, latest.id DESC LIMIT 1)
        AND (NEW.claim_strength <> 'causal'
          OR (e.result_claim_type = 'causal' AND e.evidence_decision = 'supported'))
    );

    SELECT RAISE(ABORT, 'Unresolved assessment context')
    WHERE EXISTS (
      SELECT 1 FROM json_each(NEW.validity_context_json, '$.payload.contextEventUuids') AS ref
      WHERE ref.type <> 'text' OR NOT EXISTS (
        SELECT 1 FROM brain_context_event WHERE uuid = ref.value AND is_deleted = 0
      )
    );
  
      END;

CREATE TRIGGER brain_context_event_identity_update BEFORE UPDATE ON brain_context_event
      WHEN OLD.id IS NOT NEW.id OR OLD.uuid IS NOT NEW.uuid
      BEGIN SELECT RAISE(ABORT, 'Brain identity is immutable'); END;

CREATE TRIGGER brain_context_event_reject_replacement BEFORE INSERT ON brain_context_event
      WHEN EXISTS (SELECT 1 FROM brain_context_event WHERE uuid = NEW.uuid OR id = NEW.id)
      BEGIN SELECT RAISE(ABORT, 'Brain UUID or row ID already exists'); END;

CREATE TRIGGER brain_context_event_source_delete AFTER DELETE ON brain_context_event
      BEGIN
              DELETE FROM brain_memory_node
      WHERE source_entity_type = 'contextEvent' AND source_entity_uuid = OLD.uuid;
    
                  DELETE FROM brain_assessment WHERE EXISTS (
            SELECT 1 FROM json_each(validity_context_json, '$.payload.contextEventUuids')
            WHERE value = OLD.uuid
          );
        
      END;

CREATE TRIGGER brain_context_event_source_update AFTER UPDATE ON brain_context_event
        BEGIN
          DELETE FROM brain_memory_node
          WHERE source_entity_type = 'contextEvent' AND source_entity_uuid = OLD.uuid
            AND NEW.is_deleted = 1;
                    DELETE FROM brain_assessment WHERE EXISTS (
            SELECT 1 FROM json_each(validity_context_json, '$.payload.contextEventUuids')
            WHERE value = OLD.uuid
          );
        
        END;

CREATE TRIGGER brain_evaluation_evidence_frozen_update
    BEFORE UPDATE ON brain_evaluation_evidence
    BEGIN SELECT RAISE(ABORT, 'Brain evidence is append-only'); END;

CREATE TRIGGER brain_evaluation_evidence_identity_update BEFORE UPDATE ON brain_evaluation_evidence
      WHEN OLD.id IS NOT NEW.id OR OLD.uuid IS NOT NEW.uuid
      BEGIN SELECT RAISE(ABORT, 'Brain identity is immutable'); END;

CREATE TRIGGER brain_evaluation_evidence_purge
    AFTER DELETE ON brain_evaluation_evidence
    BEGIN DELETE FROM brain_evaluation WHERE id = OLD.evaluation_id; END;

CREATE TRIGGER brain_evaluation_evidence_reject_replacement BEFORE INSERT ON brain_evaluation_evidence
      WHEN EXISTS (SELECT 1 FROM brain_evaluation_evidence WHERE uuid = NEW.uuid OR id = NEW.id)
      BEGIN SELECT RAISE(ABORT, 'Brain UUID or row ID already exists'); END;

CREATE TRIGGER brain_evaluation_evidence_validate_insert
      BEFORE INSERT ON brain_evaluation_evidence
      BEGIN
            SELECT RAISE(ABORT, 'Invalid canonical TYR metric unit')
    WHERE NEW.canonical_unit IS NOT CASE NEW.metric_key WHEN 'total_sleep_minutes' THEN 'minutes' WHEN 'sleep_debt_minutes_7_day' THEN 'minutes' WHEN 'bedtime_minute' THEN 'minute_of_day' WHEN 'wake_minute' THEN 'minute_of_day' WHEN 'sleep_midpoint_minute' THEN 'minute_of_day' WHEN 'workout_session_count' THEN 'count' WHEN 'workout_minutes' THEN 'minutes' WHEN 'cardio_minutes' THEN 'minutes' WHEN 'strength_volume_load' THEN 'kg_reps' WHEN 'strength_working_sets' THEN 'sets' WHEN 'strength_failure_sets' THEN 'sets' WHEN 'calories' THEN 'kcal' WHEN 'protein_grams' THEN 'grams' WHEN 'carbs_grams' THEN 'grams' WHEN 'fat_grams' THEN 'grams' WHEN 'total_steps' THEN 'steps' WHEN 'body_weight' THEN 'kg' WHEN 'resting_hr' THEN 'bpm' WHEN 'average_hr' THEN 'bpm' WHEN 'hrv_morning' THEN 'ms' END;

    SELECT RAISE(ABORT, 'Brain evaluation evidence is sealed')
    WHERE EXISTS (SELECT 1 FROM brain_evaluation WHERE id = NEW.evaluation_id);
  
      END;

CREATE TRIGGER brain_evaluation_frozen_update
    BEFORE UPDATE OF id, uuid, hypothesis_id, algorithm_id, algorithm_version, evaluation_mode, spec_registered_at, test_window_start, test_window_end, executed_at, spec_hash, specification_codec_version, specification_json, input_manifest_hash, reproducibility_level, primary_metric_key, effect_estimate, effect_unit, interval_lower, interval_upper, interval_method, interval_level, sample_count, coverage_ratio, evidence_decision, result_claim_type, failure_class, limitations_code, diagnostics_codec_version, diagnostics_json, analysis_family_id, validation_method ON brain_evaluation
    BEGIN SELECT RAISE(ABORT, 'Brain evaluations are append-only'); END;

CREATE TRIGGER brain_evaluation_identity_update BEFORE UPDATE ON brain_evaluation
      WHEN OLD.id IS NOT NEW.id OR OLD.uuid IS NOT NEW.uuid
      BEGIN SELECT RAISE(ABORT, 'Brain identity is immutable'); END;

CREATE TRIGGER brain_evaluation_invalidate_delete
        AFTER DELETE ON brain_evaluation
        BEGIN DELETE FROM brain_assessment WHERE hypothesis_id = OLD.hypothesis_id; END;

CREATE TRIGGER brain_evaluation_invalidate_insert
        AFTER INSERT ON brain_evaluation
        BEGIN DELETE FROM brain_assessment WHERE hypothesis_id = NEW.hypothesis_id; END;

CREATE TRIGGER brain_evaluation_reject_replacement BEFORE INSERT ON brain_evaluation
      WHEN EXISTS (SELECT 1 FROM brain_evaluation WHERE uuid = NEW.uuid OR id = NEW.id)
      BEGIN SELECT RAISE(ABORT, 'Brain UUID or row ID already exists'); END;

CREATE TRIGGER brain_evaluation_source_delete AFTER DELETE ON brain_evaluation
      BEGIN
              DELETE FROM brain_memory_node
      WHERE source_entity_type = 'evaluation' AND source_entity_uuid = OLD.uuid;
    
        
      END;

CREATE TRIGGER brain_evaluation_supersedes_insert
    BEFORE INSERT ON brain_evaluation
    WHEN NEW.supersedes_evaluation_uuid IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM brain_evaluation
      WHERE uuid = NEW.supersedes_evaluation_uuid AND hypothesis_id = NEW.hypothesis_id
        AND executed_at <= NEW.executed_at
    )
    BEGIN SELECT RAISE(ABORT, 'Invalid predecessor evaluation'); END;

CREATE TRIGGER brain_evaluation_supersedes_update
    BEFORE UPDATE OF supersedes_evaluation_uuid ON brain_evaluation
    WHEN NEW.supersedes_evaluation_uuid IS NOT NULL OR OLD.supersedes_evaluation_uuid IS NULL
      OR EXISTS (SELECT 1 FROM brain_evaluation WHERE uuid = OLD.supersedes_evaluation_uuid)
    BEGIN SELECT RAISE(ABORT, 'Brain evaluation provenance is append-only'); END;

CREATE TRIGGER brain_evaluation_validate_insert
      BEFORE INSERT ON brain_evaluation
      BEGIN
            SELECT RAISE(ABORT, 'Unsupported TYR metric')
    WHERE NEW.primary_metric_key NOT IN ('total_sleep_minutes', 'sleep_debt_minutes_7_day', 'bedtime_minute', 'wake_minute', 'sleep_midpoint_minute', 'workout_session_count', 'workout_minutes', 'cardio_minutes', 'strength_volume_load', 'strength_working_sets', 'strength_failure_sets', 'calories', 'protein_grams', 'carbs_grams', 'fat_grams', 'total_steps', 'body_weight', 'resting_hr', 'average_hr', 'hrv_morning');

    SELECT RAISE(ABORT, 'Invalid frozen Brain specification or digest')
    WHERE tyr_brain_specification_valid(NEW.specification_json, NEW.spec_hash) IS NOT 1;

    SELECT RAISE(ABORT, 'Frozen definition must match the current Brain hypothesis')
    WHERE NOT EXISTS (
      SELECT 1 FROM brain_hypothesis AS h
      WHERE h.id = NEW.hypothesis_id
        AND h.uuid IS json_extract(NEW.specification_json, '$.payload.hypothesis.uuid')
        AND h.definition_version IS json_extract(NEW.specification_json, '$.payload.hypothesis.definitionVersion')
        AND h.title IS json_extract(NEW.specification_json, '$.payload.hypothesis.title')
        AND h.statement IS json_extract(NEW.specification_json, '$.payload.hypothesis.statement')
        AND h.domain IS json_extract(NEW.specification_json, '$.payload.hypothesis.domain')
        AND h.hypothesis_type IS json_extract(NEW.specification_json, '$.payload.hypothesis.hypothesisType')
        AND h.claim_type IS json_extract(NEW.specification_json, '$.payload.hypothesis.claimType')
        AND h.origin_type IS json_extract(NEW.specification_json, '$.payload.hypothesis.originType')
        AND h.origin_ref IS json_extract(NEW.specification_json, '$.payload.hypothesis.originRef')
        AND h.registered_at IS json_extract(NEW.specification_json, '$.payload.hypothesis.registeredAt')
        AND h.registration_mode IS json_extract(NEW.specification_json, '$.payload.hypothesis.registrationMode')
    );

    SELECT RAISE(ABORT, 'Unresolved frozen intervention period')
    WHERE EXISTS (
      SELECT 1
      FROM json_each(NEW.specification_json, '$.payload.interventionBindings') AS binding
      WHERE json_extract(binding.value, '$.interventionPeriodUuid') IS NOT NULL
        AND NOT EXISTS (
          SELECT 1 FROM intervention_periods AS period
          WHERE period.uuid = json_extract(binding.value, '$.interventionPeriodUuid')
        )
    );

    SELECT RAISE(ABORT, 'Causal claim requires prospective registration')
    WHERE NEW.result_claim_type = 'causal' AND (
      json_extract(NEW.specification_json, '$.payload.hypothesis.registrationMode') IS NOT 'prospective'
      OR json_extract(NEW.specification_json, '$.payload.hypothesis.claimType') IS NOT 'causal'
      OR json_type(NEW.specification_json, '$.payload.hypothesis.registeredAt') IS NOT 'integer'
      OR json_extract(NEW.specification_json, '$.payload.hypothesis.registeredAt') > NEW.spec_registered_at
    );
  
      END;

CREATE TRIGGER brain_hypothesis_assessment_invalidate
    AFTER UPDATE ON brain_hypothesis
    WHEN OLD.archived_at IS NOT NEW.archived_at
      OR OLD.definition_version IS NOT NEW.definition_version
    BEGIN DELETE FROM brain_assessment WHERE hypothesis_id = OLD.id; END;

CREATE TRIGGER brain_hypothesis_definition_version_update
    BEFORE UPDATE ON brain_hypothesis
    WHEN NEW.definition_version < OLD.definition_version OR (
      NEW.definition_version = OLD.definition_version AND (
        OLD.title IS NOT NEW.title OR OLD.statement IS NOT NEW.statement
        OR OLD.domain IS NOT NEW.domain OR OLD.hypothesis_type IS NOT NEW.hypothesis_type
        OR OLD.claim_type IS NOT NEW.claim_type OR OLD.origin_type IS NOT NEW.origin_type
        OR OLD.origin_ref IS NOT NEW.origin_ref OR OLD.registered_at IS NOT NEW.registered_at
        OR OLD.registration_mode IS NOT NEW.registration_mode
      )
    )
    BEGIN SELECT RAISE(ABORT, 'Brain hypothesis definition requires a new version'); END;

CREATE TRIGGER brain_hypothesis_identity_update BEFORE UPDATE ON brain_hypothesis
      WHEN OLD.id IS NOT NEW.id OR OLD.uuid IS NOT NEW.uuid
      BEGIN SELECT RAISE(ABORT, 'Brain identity is immutable'); END;

CREATE TRIGGER brain_hypothesis_intervention_identity_update BEFORE UPDATE ON brain_hypothesis_intervention
      WHEN OLD.id IS NOT NEW.id OR OLD.uuid IS NOT NEW.uuid
      BEGIN SELECT RAISE(ABORT, 'Brain identity is immutable'); END;

CREATE TRIGGER brain_hypothesis_intervention_invalidate_delete
        AFTER DELETE ON brain_hypothesis_intervention
        BEGIN DELETE FROM brain_assessment WHERE hypothesis_id = OLD.hypothesis_id; END;

CREATE TRIGGER brain_hypothesis_intervention_invalidate_insert
        AFTER INSERT ON brain_hypothesis_intervention
        BEGIN DELETE FROM brain_assessment WHERE hypothesis_id = NEW.hypothesis_id; END;

CREATE TRIGGER brain_hypothesis_intervention_invalidate_update
        AFTER UPDATE ON brain_hypothesis_intervention
        BEGIN DELETE FROM brain_assessment WHERE hypothesis_id IN (OLD.hypothesis_id, NEW.hypothesis_id); END;

CREATE TRIGGER brain_hypothesis_intervention_reject_replacement BEFORE INSERT ON brain_hypothesis_intervention
      WHEN EXISTS (SELECT 1 FROM brain_hypothesis_intervention WHERE uuid = NEW.uuid OR id = NEW.id)
      BEGIN SELECT RAISE(ABORT, 'Brain UUID or row ID already exists'); END;

CREATE TRIGGER brain_hypothesis_metric_identity_update BEFORE UPDATE ON brain_hypothesis_metric
      WHEN OLD.id IS NOT NEW.id OR OLD.uuid IS NOT NEW.uuid
      BEGIN SELECT RAISE(ABORT, 'Brain identity is immutable'); END;

CREATE TRIGGER brain_hypothesis_metric_invalidate_delete
        AFTER DELETE ON brain_hypothesis_metric
        BEGIN DELETE FROM brain_assessment WHERE hypothesis_id = OLD.hypothesis_id; END;

CREATE TRIGGER brain_hypothesis_metric_invalidate_insert
        AFTER INSERT ON brain_hypothesis_metric
        BEGIN DELETE FROM brain_assessment WHERE hypothesis_id = NEW.hypothesis_id; END;

CREATE TRIGGER brain_hypothesis_metric_invalidate_update
        AFTER UPDATE ON brain_hypothesis_metric
        BEGIN DELETE FROM brain_assessment WHERE hypothesis_id IN (OLD.hypothesis_id, NEW.hypothesis_id); END;

CREATE TRIGGER brain_hypothesis_metric_reject_replacement BEFORE INSERT ON brain_hypothesis_metric
      WHEN EXISTS (SELECT 1 FROM brain_hypothesis_metric WHERE uuid = NEW.uuid OR id = NEW.id)
      BEGIN SELECT RAISE(ABORT, 'Brain UUID or row ID already exists'); END;

CREATE TRIGGER brain_hypothesis_metric_validate_insert
      BEFORE INSERT ON brain_hypothesis_metric
      BEGIN
            SELECT RAISE(ABORT, 'Unsupported TYR metric')
    WHERE NEW.metric_key NOT IN ('total_sleep_minutes', 'sleep_debt_minutes_7_day', 'bedtime_minute', 'wake_minute', 'sleep_midpoint_minute', 'workout_session_count', 'workout_minutes', 'cardio_minutes', 'strength_volume_load', 'strength_working_sets', 'strength_failure_sets', 'calories', 'protein_grams', 'carbs_grams', 'fat_grams', 'total_steps', 'body_weight', 'resting_hr', 'average_hr', 'hrv_morning');
  
      END;

CREATE TRIGGER brain_hypothesis_metric_validate_update
      BEFORE UPDATE ON brain_hypothesis_metric
      BEGIN
            SELECT RAISE(ABORT, 'Unsupported TYR metric')
    WHERE NEW.metric_key NOT IN ('total_sleep_minutes', 'sleep_debt_minutes_7_day', 'bedtime_minute', 'wake_minute', 'sleep_midpoint_minute', 'workout_session_count', 'workout_minutes', 'cardio_minutes', 'strength_volume_load', 'strength_working_sets', 'strength_failure_sets', 'calories', 'protein_grams', 'carbs_grams', 'fat_grams', 'total_steps', 'body_weight', 'resting_hr', 'average_hr', 'hrv_morning');
  
      END;

CREATE TRIGGER brain_hypothesis_prospective_revision_registration
    BEFORE UPDATE ON brain_hypothesis
    WHEN NEW.definition_version > OLD.definition_version
      AND NEW.registration_mode = 'prospective'
      AND (
        NEW.registered_at <= OLD.registered_at
        OR NEW.registered_at < CAST(strftime('%s','now') AS INTEGER)
        OR EXISTS (
          SELECT 1 FROM brain_evaluation
          WHERE hypothesis_id = OLD.id AND executed_at > NEW.registered_at
        )
      )
    BEGIN SELECT RAISE(ABORT, 'Prospective Brain revision requires a fresh registration'); END;

CREATE TRIGGER brain_hypothesis_reject_replacement BEFORE INSERT ON brain_hypothesis
      WHEN EXISTS (SELECT 1 FROM brain_hypothesis WHERE uuid = NEW.uuid OR id = NEW.id)
      BEGIN SELECT RAISE(ABORT, 'Brain UUID or row ID already exists'); END;

CREATE TRIGGER brain_hypothesis_source_delete AFTER DELETE ON brain_hypothesis
      BEGIN
              DELETE FROM brain_memory_node
      WHERE source_entity_type = 'hypothesis' AND source_entity_uuid = OLD.uuid;
    
        
      END;

CREATE TRIGGER brain_intervention_period_identity_update
    BEFORE UPDATE ON intervention_periods
    WHEN OLD.id IS NOT NEW.id OR OLD.uuid IS NOT NEW.uuid
    BEGIN
      SELECT RAISE(ABORT, 'Intervention period identity is referenced by Brain evidence')
      WHERE EXISTS (
        SELECT 1 FROM intervention_periods AS period
        WHERE (period.id IN (OLD.id, NEW.id) OR period.uuid = NEW.uuid)
          AND (    EXISTS (
      SELECT 1 FROM brain_evaluation WHERE period.uuid IN (    SELECT json_extract(binding.value, '$.interventionPeriodUuid')
    FROM json_each(brain_evaluation.specification_json, '$.payload.interventionBindings') AS binding
  )
    ) OR EXISTS (
      SELECT 1 FROM brain_evaluation_evidence
      WHERE source_type = 'interventionPeriod' AND source_uuid = period.uuid
    )
  )
      );
    END;

CREATE TRIGGER brain_intervention_period_purge
    AFTER DELETE ON intervention_periods
    BEGIN
      DELETE FROM brain_evaluation WHERE OLD.uuid IN (    SELECT json_extract(binding.value, '$.interventionPeriodUuid')
    FROM json_each(brain_evaluation.specification_json, '$.payload.interventionBindings') AS binding
  );
    END;

CREATE TRIGGER brain_intervention_period_reject_replacement
    BEFORE INSERT ON intervention_periods
    BEGIN
      SELECT RAISE(ABORT, 'Intervention period identity is referenced by Brain evidence')
      WHERE EXISTS (
        SELECT 1 FROM intervention_periods AS period
        WHERE (period.id = NEW.id OR period.uuid = NEW.uuid)
          AND (    EXISTS (
      SELECT 1 FROM brain_evaluation WHERE period.uuid IN (    SELECT json_extract(binding.value, '$.interventionPeriodUuid')
    FROM json_each(brain_evaluation.specification_json, '$.payload.interventionBindings') AS binding
  )
    ) OR EXISTS (
      SELECT 1 FROM brain_evaluation_evidence
      WHERE source_type = 'interventionPeriod' AND source_uuid = period.uuid
    )
  )
      );
    END;

CREATE TRIGGER brain_memory_link_identity_update BEFORE UPDATE ON brain_memory_link
      WHEN OLD.id IS NOT NEW.id OR OLD.uuid IS NOT NEW.uuid
      BEGIN SELECT RAISE(ABORT, 'Brain identity is immutable'); END;

CREATE TRIGGER brain_memory_link_reject_replacement BEFORE INSERT ON brain_memory_link
      WHEN EXISTS (SELECT 1 FROM brain_memory_link WHERE uuid = NEW.uuid OR id = NEW.id)
      BEGIN SELECT RAISE(ABORT, 'Brain UUID or row ID already exists'); END;

CREATE TRIGGER brain_memory_node_identity_update BEFORE UPDATE ON brain_memory_node
      WHEN OLD.id IS NOT NEW.id OR OLD.uuid IS NOT NEW.uuid
      BEGIN SELECT RAISE(ABORT, 'Brain identity is immutable'); END;

CREATE TRIGGER brain_memory_node_reject_replacement BEFORE INSERT ON brain_memory_node
      WHEN EXISTS (SELECT 1 FROM brain_memory_node WHERE uuid = NEW.uuid OR id = NEW.id)
      BEGIN SELECT RAISE(ABORT, 'Brain UUID or row ID already exists'); END;

CREATE TRIGGER brain_memory_node_source_immutable
    BEFORE UPDATE ON brain_memory_node
    WHEN OLD.node_type IS NOT NEW.node_type
      OR OLD.source_entity_type IS NOT NEW.source_entity_type
      OR OLD.source_entity_uuid IS NOT NEW.source_entity_uuid
    BEGIN SELECT RAISE(ABORT, 'Brain memory node provenance is immutable'); END;

CREATE TRIGGER brain_memory_node_validate_insert
      BEFORE INSERT ON brain_memory_node
      BEGIN
            SELECT RAISE(ABORT, 'Unresolved Brain memory source')
    WHERE CASE NEW.source_entity_type
      WHEN 'hypothesis' THEN NOT EXISTS (
        SELECT 1 FROM brain_hypothesis WHERE uuid = NEW.source_entity_uuid)
      WHEN 'evaluation' THEN NOT EXISTS (
        SELECT 1 FROM brain_evaluation WHERE uuid = NEW.source_entity_uuid)
      WHEN 'contextEvent' THEN NOT EXISTS (
        SELECT 1 FROM brain_context_event WHERE uuid = NEW.source_entity_uuid AND is_deleted = 0)
      ELSE NEW.source_entity_type IS NOT NULL
    END;
  
      END;

CREATE TRIGGER brain_memory_node_validate_update
      BEFORE UPDATE ON brain_memory_node
      BEGIN
            SELECT RAISE(ABORT, 'Unresolved Brain memory source')
    WHERE CASE NEW.source_entity_type
      WHEN 'hypothesis' THEN NOT EXISTS (
        SELECT 1 FROM brain_hypothesis WHERE uuid = NEW.source_entity_uuid)
      WHEN 'evaluation' THEN NOT EXISTS (
        SELECT 1 FROM brain_evaluation WHERE uuid = NEW.source_entity_uuid)
      WHEN 'contextEvent' THEN NOT EXISTS (
        SELECT 1 FROM brain_context_event WHERE uuid = NEW.source_entity_uuid AND is_deleted = 0)
      ELSE NEW.source_entity_type IS NOT NULL
    END;
  
      END;
