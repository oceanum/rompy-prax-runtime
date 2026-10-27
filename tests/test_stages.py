from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest
from rompy_prax_runtime import stages


def raw(handoff):
    return json.dumps(handoff)


def test_detached_exact_handoff_and_reference(handoff):
    accepted, document = stages.admit(raw(handoff))
    assert accepted["configuration"]["content"] == handoff["configuration"]["content"]
    accepted["configuration"]["content"] = "changed"
    assert handoff["configuration"]["content"] != "changed"
    assert (
        document["config"]["inpgrid"]["bottom"]["source"]["kwargs"]["service"]
        == "https://datamesh.oceanum.tech"
    )


@pytest.mark.parametrize("field", ["content_sha256", "model_json_sha256"])
def test_hash_mismatch(handoff, field):
    handoff["configuration"][field] = "wrong"
    with pytest.raises(stages.StageError):
        stages.admit(raw(handoff))


def test_rejects_source_json_difference_unknown_reference_and_bad_evidence(handoff):
    import copy

    changed = copy.deepcopy(handoff)
    changed["configuration"]["content"] += "\nextra: true\n"
    changed["configuration"]["content_sha256"] = stages.digest(
        changed["configuration"]["content"].encode()
    )
    with pytest.raises(stages.StageError, match="source_json_mismatch"):
        stages.admit(raw(changed))
    changed = copy.deepcopy(handoff)
    source = changed["configuration"]["content"].replace(
        "https://datamesh.oceanum.tech", "https://datamesh.oceanum.io"
    )
    document = stages.yaml_document(source)
    model = json.dumps(document)
    changed["configuration"].update(
        content=source,
        content_sha256=stages.digest(source.encode()),
        model_json=model,
        model_json_sha256=stages.digest(model.encode()),
    )
    changed["validation"]["document_sha256"] = stages.digest(model.encode())
    with pytest.raises(stages.StageError, match="only_reviewed_reference"):
        stages.admit(raw(changed))
    changed = copy.deepcopy(handoff)
    changed["validation"]["document_sha256"] = "wrong"
    with pytest.raises(stages.StageError, match="validation_correlation"):
        stages.admit(raw(changed))


@pytest.mark.parametrize("field", ["period", "input_references", "submission"])
def test_review_metadata_cannot_disagree_with_the_admitted_document(handoff, field):
    handoff[field] = {"enabled": True} if field == "submission" else []
    with pytest.raises(stages.StageError):
        stages.admit(raw(handoff))


@pytest.mark.parametrize("content", ['{"version":1,"version":1}', "a" * 262145])
def test_size_and_duplicate_keys(content):
    with pytest.raises(stages.StageError):
        stages.admit(content)


def fake_generator(monkeypatch, handoff, behavior="good"):
    counter = {"generated": 0}

    class Model:
        staging_dir = stages.Path("example_declarative/run1")

        def generate(self):
            counter["generated"] += 1
            self.staging_dir.mkdir(parents=True)
            content = b"INPUT relative-file\n"
            if behavior == "secret":
                content = b"synthetic-datamesh-secret"
            if behavior == "absolute":
                content = str(Path.cwd().parent).encode()
            (self.staging_dir / "INPUT").write_bytes(content)
            (self.staging_dir / "bottom.bot").write_bytes(b"native data")
            if behavior == "private_metadata":
                metadata_file = self.staging_dir / "generate_result.json"
                metadata_file.write_bytes(b'{"success":true}')
                metadata_file.chmod(0o600)
                private_directory = self.staging_dir / "private"
                private_directory.mkdir(mode=0o700)
                executable = private_directory / "helper.sh"
                executable.write_bytes(b"#!/bin/sh\nexit 0\n")
                executable.chmod(0o700)
            if behavior == "stale":
                (self.staging_dir / "swangrid.nc").write_bytes(b"stale")
            return SimpleNamespace(success=behavior != "failed")

    class Run:
        @classmethod
        def model_validate(cls, _):
            return Model()

    for name in ("rompy", "rompy.model", "rompy_swan", "rompy_swan.config"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    sys.modules["rompy.model"].ModelRun = Run
    sys.modules["rompy_swan.config"].SwanConfig = type("SwanConfig", (), {})
    monkeypatch.setitem(
        sys.modules,
        "dask",
        SimpleNamespace(config=SimpleNamespace(set=lambda **_: nullcontext())),
    )
    monkeypatch.setattr(stages, "runtime", lambda: handoff["validation"]["runtime"])
    monkeypatch.setenv("DATAMESH_TOKEN", "synthetic-datamesh-secret")
    monkeypatch.delenv("DATAMESH_GATEWAY", raising=False)
    monkeypatch.delenv("DATAMESH_SERVICE", raising=False)
    return counter


def test_generation_publishes_complete_workspace_only_after_checks(
    monkeypatch, handoff, tmp_path
):
    counter = fake_generator(monkeypatch, handoff)
    output = tmp_path / "run"
    result = stages.generate(raw(handoff), output)
    assert result["phase"] == "generated" and result["model_executed"] is False
    assert counter["generated"] == 1
    assert (output / stages.STAGING / "INPUT").exists()
    native = json.loads((output / "evidence/native-inputs.json").read_bytes())
    for name, sha in native.items():
        assert stages.digest((output / name).read_bytes()) == sha
    assert not list(tmp_path.glob("rompy-preparing-*"))


def test_publication_normalizes_checked_private_metadata_without_changing_bytes(
    monkeypatch, handoff, tmp_path
):
    fake_generator(monkeypatch, handoff, "private_metadata")
    output = tmp_path / "run"
    stages.generate(raw(handoff), output)
    metadata = output / stages.STAGING / "generate_result.json"
    executable = output / stages.STAGING / "private/helper.sh"
    assert metadata.read_bytes() == b'{"success":true}'
    assert metadata.stat().st_mode & 0o777 == 0o644
    assert executable.stat().st_mode & 0o777 == 0o755
    assert executable.parent.stat().st_mode & 0o777 == 0o755
    native = json.loads((output / "evidence/native-inputs.json").read_bytes())
    for name, expected in native.items():
        assert stages.digest((output / name).read_bytes()) == expected


def test_sensitive_workspace_never_reaches_permission_normalization(
    monkeypatch, handoff, tmp_path
):
    fake_generator(monkeypatch, handoff, "secret")
    called = []
    monkeypatch.setattr(
        stages, "_portable_artifact_modes", lambda _: called.append(True)
    )
    with pytest.raises(stages.StageError, match="credential_in_workspace"):
        stages.generate(raw(handoff), tmp_path / "run")
    assert not called
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize(
    "behavior,reason",
    [
        ("secret", "credential_in_workspace"),
        ("absolute", "nonportable"),
        ("failed", "generation_or_workspace_failed"),
        ("stale", "model_outputs_present_before_run"),
    ],
)
def test_failed_generation_never_exposes_artifact_path(
    monkeypatch, handoff, tmp_path, behavior, reason
):
    fake_generator(monkeypatch, handoff, behavior)
    output = tmp_path / "run"
    with pytest.raises(stages.StageError, match=reason):
        stages.generate(raw(handoff), output)
    assert not output.exists()
    assert not list(tmp_path.glob("rompy-preparing-*"))


def test_no_credential_or_wrong_runtime_prevents_generation(
    monkeypatch, handoff, tmp_path
):
    counter = fake_generator(monkeypatch, handoff)
    monkeypatch.delenv("DATAMESH_TOKEN")
    with pytest.raises(stages.StageError, match="credential_required"):
        stages.generate(raw(handoff), tmp_path / "run")
    monkeypatch.setenv("DATAMESH_TOKEN", "synthetic-datamesh-secret")
    monkeypatch.setattr(
        stages,
        "runtime",
        lambda: {**handoff["validation"]["runtime"], "python": "wrong"},
    )
    with pytest.raises(stages.StageError, match="runtime_mismatch"):
        stages.generate(raw(handoff), tmp_path / "run")
    assert counter["generated"] == 0


def test_symlink_size_and_pure_validation_fence(tmp_path, monkeypatch):
    with (
        stages.pure_validation(),
        pytest.raises(stages.StageError, match="validation_io_blocked"),
    ):
        (tmp_path / "no").write_text("not allowed")
    assert not (tmp_path / "no").exists()
    (tmp_path / "link").symlink_to("/tmp")
    with pytest.raises(stages.StageError, match="symlink"):
        stages.tree(tmp_path)
    (tmp_path / "link").unlink()
    (tmp_path / "large").write_bytes(b"xx")
    monkeypatch.setattr(stages, "MAX_TREE_BYTES", 1)
    with pytest.raises(stages.StageError, match="workspace_size"):
        stages.tree(tmp_path)


def test_verification_reads_all_outputs_and_rejects_missing_or_changed(
    monkeypatch, handoff, tmp_path
):
    fake_generator(monkeypatch, handoff)
    root = tmp_path / "run"
    stages.generate(raw(handoff), root)
    with pytest.raises(stages.StageError, match="missing_model_outputs"):
        stages.verify(root, tmp_path / "report")
    profile = json.loads(stages.MANIFEST.read_bytes())["expected_outputs"]
    for name in ["PRINT", *profile["files"], *profile["netcdf"]]:
        (root / stages.STAGING / name).write_bytes(b"test output")
    reads = []

    class Dataset:
        data_vars = {"hs": True}
        sizes = {"time": 25, "x": 3}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def load(self):
            reads.append(True)

    monkeypatch.setitem(
        sys.modules, "xarray", SimpleNamespace(open_dataset=lambda *_a, **_k: Dataset())
    )
    result = stages.verify(root, tmp_path / "report")
    assert result["phase"] == "verified" and len(reads) == 2
    (root / stages.STAGING / "INPUT").write_bytes(b"modified")
    with pytest.raises(stages.StageError, match="native_inputs_changed"):
        stages.verify(root, tmp_path / "another")
