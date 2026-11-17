"""Offline tests for policy helpers; no external admission path is enabled."""

from copy import deepcopy
import json
import math

import pytest

from rompy_prax_runtime import stages
from rompy_prax_runtime.subset import PolicyError, effective_document, validate


def reference():
    return stages.yaml_document(stages.REFERENCE.read_text())


def edited():
    document = reference()
    document["period"].update(start="20230101T060000", duration="12h")
    document["config"]["cgrid"]["grid"].update(
        xp=112.0, yp=-34.5, xlen=3.0, ylen=3.0, mx=7, my=12
    )
    document["config"]["output"]["points"].update(xp=[114.0], yp=[-34.0])
    return document


def test_reference_and_policy_time_representation():
    base = reference()
    validate(base, base)
    for authored in (
        "2023-01-01T06:00:00",
        "2023-01-01T06:00:00Z",
        "2023-01-01T06:00:00+00:00",
    ):
        doc = edited()
        doc["period"]["start"] = authored
        original = deepcopy(doc)
        result = effective_document(doc, base)
        assert result["period"]["start"] == "2023-01-01T06:00:00"
        assert doc == original
        assert validate(doc, base)["instants"] == 13
    doc = edited()
    doc["period"]["start"] = "2023-01-01T06:00:00+01:00"
    with pytest.raises(PolicyError):
        validate(doc, base)


def test_public_admission_stays_fixed_reference_only():
    document = edited()
    source = json.dumps(document, separators=(",", ":"))
    payload = {
        "version": 1,
        "purpose": "rompy-configuration-request",
        "configuration": {
            "format": "json",
            "content": source,
            "content_sha256": stages.digest(source.encode()),
            "model_json": source,
            "model_json_sha256": stages.digest(source.encode()),
        },
    }
    with pytest.raises(stages.StageError, match="only_reviewed_reference_supported"):
        stages.admit(json.dumps(payload))


def test_unsupported_changes_and_invalid_numbers_fail_closed():
    for mutate in (
        lambda d: d.update(run_id="different"),
        lambda d: d["config"]["physics"].update(unknown=True),
        lambda d: d["config"]["cgrid"]["grid"].update(mx=True),
        lambda d: d["config"]["cgrid"]["grid"].update(xp=math.nan),
    ):
        doc = edited()
        mutate(doc)
        with pytest.raises(PolicyError):
            validate(doc, reference())


def _pinned_model(document):
    from pydantic import Field
    from rompy.model import ModelRun
    from rompy_swan.config import SwanConfig

    class SwanRun(ModelRun):
        config: SwanConfig = Field(..., discriminator="model_type")

    return SwanRun.model_validate(deepcopy(document))


def test_actual_pinned_mesh_and_buffers_reject_rounding_and_accept_interior():
    from rompy_prax_runtime.subset import validate_actual_model

    base = reference()
    reference_model = _pinned_model(base)
    valid = edited()
    model = stages.prepare_bounded_model(valid, base)
    validate_actual_model(model, reference_model, valid, base)

    rounded = deepcopy(base)
    rounded["config"]["cgrid"]["grid"].update(xlen=7.4, mx=2)
    validate(rounded, base)  # Policy/Pydantic alone are intentionally insufficient.
    rounded_model = _pinned_model(rounded)
    assert rounded_model.config.grid.x.shape == (25, 4)
    with pytest.raises(stages.StageError, match="configuration_policy_failed"):
        stages.prepare_bounded_model(rounded, base)

    for xlen, mx in ((7.4, 2), (6.4, 2)):
        candidate = deepcopy(base)
        candidate["config"]["cgrid"]["grid"].update(xlen=xlen, mx=mx)
        try:
            validate(candidate, base)
            actual = _pinned_model(candidate)
        except Exception:
            continue
        if actual.config.grid.x.shape != (25, mx + 1):
            with pytest.raises(PolicyError):
                validate_actual_model(actual, reference_model, candidate, base)
