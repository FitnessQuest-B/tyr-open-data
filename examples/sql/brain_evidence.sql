PRAGMA query_only = ON;

-- A hypothesis can lack an assessment or evaluation.
-- Historical evaluation decisions remain visible alongside the current assessment.
SELECT
    hypothesis.id AS hypothesis_id,
    hypothesis.definition_version AS current_definition_version,
    hypothesis.archived_at,
    assessment.evidence_decision AS current_decision,
    assessment.applicability,
    assessment.latest_evaluation_uuid,
    evaluation.uuid AS evaluation_uuid,
    evaluation.executed_at,
    evaluation.evidence_decision AS evaluation_decision,
    evaluation.result_claim_type,
    evidence.metric_key,
    evidence.cohort_role,
    evidence.sample_count,
    evidence.expected_count,
    evidence.coverage_ratio,
    evidence.canonical_unit
FROM brain_hypothesis AS hypothesis
LEFT JOIN brain_assessment AS assessment ON assessment.hypothesis_id = hypothesis.id
LEFT JOIN brain_evaluation AS evaluation ON evaluation.hypothesis_id = hypothesis.id
LEFT JOIN brain_evaluation_evidence AS evidence ON evidence.evaluation_id = evaluation.id
ORDER BY hypothesis.id, evaluation.executed_at, evaluation.id, evidence.id
LIMIT 100;
