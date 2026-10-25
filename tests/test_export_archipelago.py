import json

import pytest

from tools.export_archipelago import main


def test_export_shape(tmp_path):
    assert main(["--out", str(tmp_path), "bf_001", "pr_016"]) == 0
    data = json.loads((tmp_path / "bf_001_tax_half_even.json").read_text())
    assert data["experimental"] is True and "untested" in data["note"]
    verifiers = data["verifiers"]
    assert verifiers[0]["is_primary_objective"] is True and verifiers[0]["weight"] == 0.7
    assert len(verifiers[0]["negative_criteria"]) == 5
    assert all(set(v) >= {"criteria", "weight", "is_primary_objective", "negative_criteria"} for v in verifiers)
    assert sum(v["weight"] for v in verifiers) == pytest.approx(1.0, abs=1e-3)
