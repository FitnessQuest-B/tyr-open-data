import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "schema/versions/0.1.0/"
APPROVED_FILES = {
    ".gitignore", "README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md",
    "LICENSE", "AGENTS.md", "docs/architecture/compatibility.md", "brain-lab/README.md",
    "databases/synthetic/README.md", "scenarios/README.md", "scenarios/starter.json",
    "tools/generate_synthetic.py", "tools/synthetic_model.py", "tools/synthetic_storage.py",
    "tests/test_synthetic.py",
    "brain-lab/lab.py", "brain-lab/lab_metadata.sql", "brain-lab/tyr_brain_lab/analysis.py",
    "brain-lab/tyr_brain_lab/codec.py", "brain-lab/tyr_brain_lab/source.py",
    "brain-lab/tyr_brain_lab/store.py", "tests/test_lab.py", "tests/fixtures/brain-v1-lab-vectors.json",
    "benchmark/README.md", "benchmark/task.md", "benchmark/providers.md",
    "benchmark/bench.py", "benchmark/prepare.py", "benchmark/protocol.py",
    "benchmark/worker.py", "benchmark/providers.py", "benchmark/scoring.py", "benchmark/weight_break.py",
    "tests/test_benchmark.py",
    "benchmark/pilot.py", "benchmark/pilot_design.py", "benchmark/isolated/README.md", "tests/test_pilot.py",
    "benchmark/isolated/runner.py", "benchmark/isolated/guest.py", "benchmark/isolated/wire.py",
    "benchmark/isolated/canary.py", "benchmark/isolated/provision_guest.py",
    "schema/current.json", "tools/schema_support.py", "tools/create_empty.py", "tools/read_export.py",
    "tests/test_contract.py", "tests/test_package.py", "tests/test_documentation.py",
    "docs/data-dictionary/README.md", "docs/data-dictionary/body-and-training.md",
    "docs/data-dictionary/health.md", "docs/data-dictionary/nutrition.md",
    "docs/data-dictionary/interventions-and-summaries.md",
    "docs/measurements/README.md", "docs/measurements/derived.md", "docs/measurements/metric-registry.md",
    "docs/brain/README.md", "docs/brain/tables.md",
    "examples/README.md", "examples/sql/daily_coverage.sql", "examples/sql/brain_evidence.sql",
    "examples/python/inspect_health_coverage.py", "examples/agent-prompts/read-only-review.md",
    "databases/empty/manifest.json", "databases/empty/tyr-open-data-0.1.0.sqlite",
    "databases/empty/tyr-brain-lab-0.1.0.sqlite",
} | {SCHEMA + name for name in ("records.sql", "brain-lab.sql", "foreign-keys.md", "inventory.json", "manifest.json")}


class PackageTests(unittest.TestCase):
    def test_candidate_tree_matches_review_scope(self):
        found = set()
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT)
            if rel.parts[0] == ".git":
                continue
            self.assertFalse(path.is_symlink(), str(rel))
            if path.parent.name == "__pycache__" and path.suffix == ".pyc":
                continue
            if path.is_file():
                found.add(rel.as_posix())
        self.assertEqual(found, APPROVED_FILES)

    def test_artifacts_exclude_credential_markers(self):
        key_markers = [
            rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
            rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
            rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}",
            rb"\bgh[pousr]_[a-zA-Z0-9]{30,}",
            rb'"type"\s*:\s*"service_account"',
        ]
        for name in sorted(APPROVED_FILES):
            content = (ROOT / name).read_bytes()
            for pattern in key_markers:
                self.assertIsNone(re.search(pattern, content), name)
            if not name.startswith("tests/"):
                self.assertNotIn(b"fixture@example.invalid", content, name)


if __name__ == "__main__":
    unittest.main()
