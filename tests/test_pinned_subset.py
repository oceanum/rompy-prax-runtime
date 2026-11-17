"""Real pinned rompy generation against synthetic arrays; no connector or subprocess."""

import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize(
    ("use_edit", "authored_start"),
    [
        (False, None),
        (True, "2023-01-01T06:00:00"),
        (True, "2023-01-01T06:00:00Z"),
        (True, "2023-01-01T06:00:00+00:00"),
    ],
    ids=["reference", "naive", "z", "explicit-zero-offset"],
)
def test_real_pinned_generation_of_reference_and_valid_edit(
    monkeypatch, tmp_path, use_edit, authored_start
):
    import numpy as np
    import pandas as pd
    import xarray as xr
    from rompy.core.source import SourceDatamesh
    from rompy_prax_runtime import stages
    from rompy_prax_runtime.subset import effective_document

    facts = stages.runtime()
    assert facts["python"] == "3.12.13"
    assert facts["packages"] == stages.EXPECTED
    reference = stages.yaml_document(stages.REFERENCE.read_text())
    document = stages.yaml_document(stages.REFERENCE.read_text())
    if use_edit:
        document["period"].update(start=authored_start, duration="12h")
        document["config"]["cgrid"]["grid"].update(
            xp=112.0, yp=-34.5, xlen=3.0, ylen=3.0, mx=7, my=12
        )
        document["config"]["output"]["points"].update(xp=[114.0], yp=[-34.0])
    calls = []

    def fixture(self, variables, geofilter, timefilter):
        calls.append((self.datasource, variables, geofilter, timefilter))
        lon = np.arange(100.0, 131.0)
        lat = np.arange(-45.0, -9.0)
        if self.datasource == "gebco_2008":
            return xr.Dataset(
                {"elevation": (("lat", "lon"), np.full((len(lat), len(lon)), -20.0))},
                coords={"lon": lon, "lat": lat},
            )
        assert self.datasource == "era5_wind10m"
        times = pd.date_range("2023-01-01", periods=25, freq="h")
        values = np.full((len(times), len(lat), len(lon)), 5.0)
        return xr.Dataset(
            {
                "u10": (("time", "latitude", "longitude"), values),
                "v10": (("time", "latitude", "longitude"), values),
            },
            coords={"longitude": lon, "latitude": lat, "time": times},
        )

    monkeypatch.setattr(SourceDatamesh, "_open", fixture)
    monkeypatch.setattr(
        SourceDatamesh,
        "connector",
        property(lambda _: pytest.fail("connector accessed")),
    )
    monkeypatch.setattr(
        subprocess, "Popen", lambda *_a, **_k: pytest.fail("model subprocess attempted")
    )
    monkeypatch.setattr(os, "system", lambda *_a, **_k: pytest.fail("shell attempted"))
    model = stages.prepare_bounded_model(document)
    cwd = Path.cwd()
    work = tmp_path / "work"
    (work / "examples").mkdir(parents=True)
    try:
        os.chdir(work / "examples")
        result = model.generate()
    finally:
        os.chdir(cwd)
    assert result.success
    generated = work / "examples/example_declarative/run1/INPUT"
    text = generated.read_text()
    if use_edit:
        assert "hotfile_20230101T180000.txt" in text
        assert "20230101.060000" in text and "20230101.180000" in text
    else:
        assert "hotfile_20230102T000000.txt" in text
        assert "20230101.000000" in text and "20230102.000000" in text
    assert calls and {item[0] for item in calls} == {"gebco_2008", "era5_wind10m"}
    assert all(item[2] is not None for item in calls if item[1])
    assert not any(
        (generated.parent / name).exists()
        for name in ("PRINT", "swangrid.nc", "swanspec.nc")
    )
    if use_edit:
        assert document["period"]["start"] == authored_start
        assert (
            effective_document(document, reference)["period"]["start"]
            == "2023-01-01T06:00:00"
        )
    else:
        assert document["period"]["start"] == reference["period"]["start"]


@pytest.mark.parametrize("envelope", ["browser", "legacy"])
def test_integrated_edited_profile_local_pipeline(
    envelope, handoff, monkeypatch, tmp_path
):
    import copy
    import json

    import numpy as np
    import pandas as pd
    import xarray as xr
    from rompy.core.source import SourceDatamesh
    from rompy_prax_runtime import stages

    facts = stages.runtime()
    content = handoff["configuration"]["content"]
    substitutions = {
        "start: 20230101T000000": "start: 20230101T060000",
        "duration: 1d": "duration: 12h",
        "xp: 110.0": "xp: 112.0",
        "yp: -35.2": "yp: -34.5",
        "xlen: 7.5": "xlen: 3.0",
        "ylen: 12.5": "ylen: 3.0",
        "mx: 14": "mx: 7",
        "my: 24": "my: 12",
        "xp: [114.0, 112.5, 115.0]": "xp: [114.0]",
        "yp: [-34.0, -26.0, -30.0]": "yp: [-34.0]",
    }
    for original, replacement in substitutions.items():
        assert original in content
        content = content.replace(original, replacement, 1)
    document = stages.yaml_document(content)
    model_json = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    configuration = {
        "format": "yaml",
        "content": content,
        "content_sha256": stages.digest(content.encode()),
        "model_json": model_json,
        "model_json_sha256": stages.digest(model_json.encode()),
    }
    if envelope == "browser":
        request = {
            "version": 1,
            "purpose": "rompy-configuration-request",
            "configuration": configuration,
        }
        raw = json.dumps(request, separators=(",", ":"))
    else:
        legacy = copy.deepcopy(handoff)
        legacy["configuration"] = configuration
        legacy["period"] = document["period"]
        legacy["validation"]["document_sha256"] = configuration["model_json_sha256"]
        legacy["validation"]["runtime"] = facts
        legacy["validation"]["runtime_id"] = stages.digest(stages.encoded(facts))
        raw = json.dumps(legacy, separators=(",", ":"))

    def fixture(self, variables, geofilter, timefilter):
        lon = np.arange(100.0, 131.0)
        lat = np.arange(-45.0, -9.0)
        if self.datasource == "gebco_2008":
            return xr.Dataset(
                {"elevation": (("lat", "lon"), np.full((len(lat), len(lon)), -20.0))},
                coords={"lon": lon, "lat": lat},
            )
        times = pd.date_range("2023-01-01", periods=25, freq="h")
        values = np.full((len(times), len(lat), len(lon)), 5.0)
        return xr.Dataset(
            {
                "u10": (("time", "latitude", "longitude"), values),
                "v10": (("time", "latitude", "longitude"), values),
            },
            coords={"longitude": lon, "latitude": lat, "time": times},
        )

    monkeypatch.setattr(SourceDatamesh, "_open", fixture)
    monkeypatch.setattr(
        SourceDatamesh,
        "connector",
        property(lambda _: pytest.fail("connector accessed")),
    )
    monkeypatch.setenv("DATAMESH_TOKEN", "synthetic-token")
    monkeypatch.delenv("DATAMESH_GATEWAY", raising=False)
    monkeypatch.delenv("DATAMESH_SERVICE", raising=False)
    root = tmp_path / "workspace"
    result = stages.generate(raw, root)
    assert result["phase"] == "generated"
    profile = stages._read_json(root / "evidence/generation-profile.json")
    expected = profile["expected_outputs"]
    staging = root / stages.STAGING
    (staging / "PRINT").write_text("synthetic output fixture")
    for name in expected["files"]:
        (staging / name).write_text("synthetic output fixture")
    for name, dimensions in expected["dimensions"].items():
        dims = tuple(dimensions)
        shape = tuple(dimensions[key] for key in dims)
        dataset = xr.Dataset({"fixture": (dims, np.ones(shape))})
        dataset.to_netcdf(staging / name, engine="scipy")
    report = stages.verify(root, tmp_path / "verification")
    assert report["phase"] == "verified"
    assert report["profile_id"] == "reference-subsets-v1"
    retained = stages._read_json(root / "evidence/configuration-handoff.json")
    assert retained["configuration"]["content"] == content
    if envelope == "browser":
        assert (root / "evidence/configuration-request.json").read_text() == raw
    else:
        assert (root / "evidence/configuration-handoff.json").read_text() == raw
