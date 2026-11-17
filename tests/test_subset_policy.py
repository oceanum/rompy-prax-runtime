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


def test_public_admission_activates_bounded_browser_profile():
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
    accepted, actual = stages.admit(json.dumps(payload))
    assert accepted["purpose"] == "rompy-configuration-request"
    assert actual == document


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


def test_preparer_anchors_immutable_source_physics_and_path_fields():
    for mutate in (
        lambda d: d["config"]["inpgrid"]["bottom"]["source"].update(
            datasource="caller-controlled"
        ),
        lambda d: d["config"]["inpgrid"]["bottom"]["source"]["kwargs"].update(
            service="https://caller-controlled.invalid"
        ),
        lambda d: d["config"]["physics"]["quadrupl"].update(iquad=99),
        lambda d: d.update(output_dir="caller-controlled"),
    ):
        document = reference()
        mutate(document)
        # The preparer has no caller-supplied baseline parameter; policy is
        # evaluated against the checked-in bytes, not the candidate itself.
        with pytest.raises(PolicyError):
            stages.prepare_bounded_model(document)


def test_preparer_fails_closed_on_tampered_reference_bytes(monkeypatch, tmp_path):
    reference_path = tmp_path / "reference.yml"
    reference_path.write_bytes(stages.REFERENCE.read_bytes() + b"# tampered\n")
    monkeypatch.setattr(stages, "REFERENCE", reference_path)
    with pytest.raises(stages.StageError, match="reference_integrity"):
        stages.checked_reference_document()


def test_actual_pinned_mesh_and_buffers_reject_rounding_and_accept_interior():
    from rompy_prax_runtime.subset import validate_actual_model

    base = reference()
    reference_model = _pinned_model(base)
    valid = edited()
    model = stages.prepare_bounded_model(valid)
    validate_actual_model(model, reference_model, valid, base)

    rounded = deepcopy(base)
    rounded["config"]["cgrid"]["grid"].update(xlen=7.4, mx=2)
    validate(rounded, base)  # Policy/Pydantic alone are intentionally insufficient.
    rounded_model = _pinned_model(rounded)
    assert rounded_model.config.grid.x.shape == (25, 4)
    with pytest.raises(stages.StageError, match="configuration_policy_failed"):
        stages.prepare_bounded_model(rounded)

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


@pytest.mark.parametrize(
    "edit",
    ["last_hour_boundary", "minimum_mesh_extent", "maximum_mesh", "maximum_points"],
)
def test_edit_family_boundaries_use_actual_pinned_selection(edit):
    document = reference()
    grid = document["config"]["cgrid"]["grid"]
    points = document["config"]["output"]["points"]
    if edit == "last_hour_boundary":
        document["period"].update(
            start="2023-01-01T23:00:00Z", duration="1h", interval="1h"
        )
    elif edit == "minimum_mesh_extent":
        grid.update(xp=112.0, yp=-34.5, xlen=3.0, ylen=3.0, mx=1, my=1)
        points.update(xp=[114.0], yp=[-34.0])
    elif edit == "maximum_mesh":
        grid.update(xp=112.0, yp=-34.5, xlen=4.0, ylen=4.0, mx=14, my=24)
        points.update(xp=[114.0], yp=[-34.0])
    else:
        points.update(xp=[114.0, 114.1, 114.2], yp=[-34.0, -34.0, -34.0])
    base = reference()
    model = stages.prepare_bounded_model(document)
    model_json = json.dumps(document, separators=(",", ":"))
    from rompy_prax_runtime.subset import expected_outputs

    outputs = expected_outputs(document, base, stages.digest(model_json.encode()))
    assert model.config.grid.x.shape == (
        grid["my"] + 1,
        grid["mx"] + 1,
    )
    assert outputs["dimensions"]["swangrid.nc"]["yc"] == model.config.grid.x.shape[0]
    assert outputs["dimensions"]["swangrid.nc"]["xc"] == model.config.grid.x.shape[1]
    assert outputs["dimensions"]["swanspec.nc"]["points"] == len(points["xp"])


def test_actual_selection_rejects_outside_points_and_invalid_edits():
    cases = []
    outside = edited()
    outside["config"]["output"]["points"].update(xp=[130.0], yp=[0.0])
    cases.append(outside)
    bad_time = edited()
    bad_time["period"].update(start="2023-01-02T01:00:00", duration="1h")
    cases.append(bad_time)
    for document in cases:
        with pytest.raises(
            (stages.StageError, PolicyError), match="^configuration_policy_failed$"
        ):
            stages.prepare_bounded_model(document)
