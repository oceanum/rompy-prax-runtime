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


@pytest.mark.parametrize(
    "invalid_case",
    [
        "arange_mesh_overflow",
        "expanded_buffered_footprint",
        "outside_time_window",
        "nonzero_utc_offset",
        "invalid_interval",
        "invalid_point_shape",
        "forbidden_source",
        "forbidden_physics_path",
    ],
)
def test_public_generate_rejects_invalid_profiles_before_effects(
    invalid_case, handoff, monkeypatch, tmp_path
):
    import json

    from rompy.core.source import SourceDatamesh
    from rompy_prax_runtime import stages

    document = stages.yaml_document(handoff["configuration"]["content"])
    grid = document["config"]["cgrid"]["grid"]
    period = document["period"]
    if invalid_case == "arange_mesh_overflow":
        grid.update(xlen=7.4, mx=2)
    elif invalid_case == "expanded_buffered_footprint":
        grid.update(xp=113.0)
    elif invalid_case == "outside_time_window":
        period.update(start="2023-01-02T01:00:00", duration="1h")
    elif invalid_case == "nonzero_utc_offset":
        period.update(start="2023-01-01T01:00:00+01:00")
    elif invalid_case == "invalid_interval":
        period.update(interval="5h")
    elif invalid_case == "invalid_point_shape":
        document["config"]["output"]["points"]["yp"] = [-34.0]
    elif invalid_case == "forbidden_source":
        document["config"]["inpgrid"]["bottom"]["source"].update(
            datasource="caller-controlled"
        )
    else:
        document["config"]["physics"]["quadrupl"].update(iquad=99)

    source = json.dumps(document, separators=(",", ":"))
    configuration = {
        "format": "json",
        "content": source,
        "content_sha256": stages.digest(source.encode()),
        "model_json": source,
        "model_json_sha256": stages.digest(source.encode()),
    }
    raw = json.dumps(
        {
            "version": 1,
            "purpose": "rompy-configuration-request",
            "configuration": configuration,
        }
    )
    monkeypatch.delenv("DATAMESH_TOKEN", raising=False)
    monkeypatch.setattr(
        SourceDatamesh, "_open", lambda *_a, **_k: pytest.fail("data accessed")
    )
    monkeypatch.setattr(
        SourceDatamesh,
        "connector",
        property(lambda _: pytest.fail("connector accessed")),
    )
    destination = tmp_path / "workspace"
    with pytest.raises(stages.StageError, match="^configuration_policy_failed$"):
        stages.generate(raw, destination)
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


PIPELINE_CASES = [
    pytest.param(
        {},
        "hotfile_20230102T000000.txt",
        "20230101.000000",
        "20230102.000000",
        "1.0 HR",
        "CGRID REGULAR xpc=110.0 ypc=-35.2 alpc=4.0 xlenc=7.5 ylenc=12.5 mxc=14 myc=24",
        "xp=114.0 yp=-34.0",
        {
            "swangrid.nc": {"time": 25, "yc": 25, "xc": 15},
            "swanspec.nc": {"points": 3, "time": 25, "frequency": 35, "direction": 36},
        },
        id="reference",
    ),
    pytest.param(
        {
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
        },
        "hotfile_20230101T180000.txt",
        "20230101.060000",
        "20230101.180000",
        "1.0 HR",
        "CGRID REGULAR xpc=112.0 ypc=-34.5 alpc=4.0 xlenc=3.0 ylenc=3.0 mxc=7 myc=12",
        "xp=114.0 yp=-34.0",
        {
            "swangrid.nc": {"time": 13, "yc": 13, "xc": 8},
            "swanspec.nc": {"points": 1, "time": 13, "frequency": 35, "direction": 36},
        },
        id="combined-interior-edit",
    ),
    pytest.param(
        {
            "start: 20230101T000000": "start: 20230101T230000Z",
            "duration: 1d": "duration: 1h",
            "interval: 1h": "interval: 1h",
            "xp: 110.0": "xp: 112.0",
            "yp: -35.2": "yp: -34.5",
            "xlen: 7.5": "xlen: 3.0",
            "ylen: 12.5": "ylen: 3.0",
            "mx: 14": "mx: 1",
            "my: 24": "my: 1",
            "xp: [114.0, 112.5, 115.0]": "xp: [112.0]",
            "yp: [-34.0, -26.0, -30.0]": "yp: [-34.5]",
        },
        "hotfile_20230102T000000.txt",
        "20230101.230000",
        "20230102.000000",
        "1.0 HR",
        "CGRID REGULAR xpc=112.0 ypc=-34.5 alpc=4.0 xlenc=3.0 ylenc=3.0 mxc=1 myc=1",
        "xp=112.0 yp=-34.5",
        {
            "swangrid.nc": {"time": 2, "yc": 2, "xc": 2},
            "swanspec.nc": {"points": 1, "time": 2, "frequency": 35, "direction": 36},
        },
        id="late-end-boundary-minimum-mesh",
    ),
    pytest.param(
        {"interval: 1h": "interval: 2h"},
        "hotfile_20230102T000000.txt",
        "20230101.000000",
        "20230102.000000",
        "2.0 HR",
        "CGRID REGULAR xpc=110.0 ypc=-35.2 alpc=4.0 xlenc=7.5 ylenc=12.5 mxc=14 myc=24",
        "xp=114.0 yp=-34.0",
        {
            "swangrid.nc": {"time": 13, "yc": 25, "xc": 15},
            "swanspec.nc": {"points": 3, "time": 13, "frequency": 35, "direction": 36},
        },
        id="coarser-divisible-interval",
    ),
    pytest.param(
        {
            "xp: [114.0, 112.5, 115.0]": "xp: [114.0, 112.5]",
            "yp: [-34.0, -26.0, -30.0]": "yp: [-34.0, -26.0]",
        },
        "hotfile_20230102T000000.txt",
        "20230101.000000",
        "20230102.000000",
        "1.0 HR",
        "CGRID REGULAR xpc=110.0 ypc=-35.2 alpc=4.0 xlenc=7.5 ylenc=12.5 mxc=14 myc=24",
        "xp=114.0 yp=-34.0 &\n    xp=112.5 yp=-26.0",
        {
            "swangrid.nc": {"time": 25, "yc": 25, "xc": 15},
            "swanspec.nc": {"points": 2, "time": 25, "frequency": 35, "direction": 36},
        },
        id="reference-footprint-two-points",
    ),
]


@pytest.mark.parametrize("envelope", ["browser", "legacy"])
@pytest.mark.parametrize(
    "edits, hotfile, expected_start, expected_end, expected_interval, expected_grid, expected_points, expected_dimensions",
    PIPELINE_CASES,
)
def test_integrated_edited_profile_local_pipeline(
    envelope,
    edits,
    hotfile,
    expected_start,
    expected_end,
    expected_interval,
    expected_grid,
    expected_points,
    expected_dimensions,
    handoff,
    monkeypatch,
    tmp_path,
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
    for original, replacement in edits.items():
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
        raw = json.dumps(
            {
                "version": 1,
                "purpose": "rompy-configuration-request",
                "configuration": configuration,
            },
            separators=(",", ":"),
        )
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
    assert profile["expected_outputs"]["files"] == ["swantable.txt", hotfile]
    assert profile["expected_outputs"]["dimensions"] == expected_dimensions
    staging = root / stages.STAGING
    control = (staging / "INPUT").read_text()
    assert hotfile in control
    assert f"tbegc={expected_start}" in control
    import re

    compute = re.search(
        r"(?m)^COMPUTE NONSTATIONARY tbegc=(\S+) deltc=(\S+\s+\S+) tendc=(\S+)\s*$",
        control,
    )
    assert compute is not None, control
    assert compute.groups() == (expected_start, expected_interval, expected_end)
    assert f"OUTPUT tbegblk={expected_start} deltblk={expected_interval}" in control
    assert f"OUTPUT tbegspc={expected_start} deltspc={expected_interval}" in control
    assert expected_grid in control
    assert expected_points in control
    (staging / "PRINT").write_text("synthetic output fixture")
    (staging / "swantable.txt").write_text("synthetic output fixture")
    (staging / hotfile).write_text("synthetic output fixture")
    for name, dimensions in expected_dimensions.items():
        dims = tuple(dimensions)
        shape = tuple(dimensions[key] for key in dims)
        xr.Dataset({"fixture": (dims, np.ones(shape))}).to_netcdf(
            staging / name, engine="scipy"
        )
    report = stages.verify(root, tmp_path / "verification")
    assert report["phase"] == "verified"
    assert report["profile_id"] == "reference-subsets-v1"
    retained = stages._read_json(root / "evidence/configuration-handoff.json")
    assert retained["configuration"]["content"] == content
    if envelope == "browser":
        assert (root / "evidence/configuration-request.json").read_text() == raw
    else:
        assert (root / "evidence/configuration-handoff.json").read_text() == raw
