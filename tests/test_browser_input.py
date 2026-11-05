"""Browser source requests need no client Python acceptance; PRAX validates first."""

from copy import deepcopy
import json
import sys

import pytest
from pydantic import ValidationError

from rompy_prax_runtime import stages
from test_stages import fake_generator


def request(handoff):
    return {
        "version": 1,
        "purpose": "rompy-configuration-request",
        "configuration": deepcopy(handoff["configuration"]),
    }


def test_source_only_browser_request_is_detached_without_claiming_acceptance(handoff):
    payload = request(handoff)
    admitted, document = stages.admit(json.dumps(payload))
    assert set(admitted) == {"version", "purpose", "configuration"}
    assert document == json.loads(handoff["configuration"]["model_json"])
    admitted["configuration"]["content"] = "changed"
    assert payload["configuration"]["content"] != "changed"


@pytest.mark.parametrize(
    "field",
    [
        "validation",
        "input_references",
        "period",
        "submission",
        "runtime",
        "client_invocation_id",
    ],
)
def test_browser_request_rejects_extra_client_claims(handoff, field):
    payload = request(handoff)
    payload[field] = {"status": "accepted"}
    with pytest.raises(stages.StageError, match="handoff_shape"):
        stages.admit(json.dumps(payload))


@pytest.mark.parametrize("version", [True, 2, "1"])
def test_browser_request_version_is_strict(handoff, version):
    payload = request(handoff)
    payload["version"] = version
    with pytest.raises(stages.StageError):
        stages.admit(json.dumps(payload))


@pytest.mark.parametrize(
    "kind", ["hash", "mismatch", "reference", "duplicate", "oversized"]
)
def test_invalid_browser_request_stops_before_runtime_or_generation(
    monkeypatch, handoff, tmp_path, kind
):
    payload = request(handoff)
    config = payload["configuration"]
    if kind == "hash":
        config["content_sha256"] = "wrong"
    if kind in {"mismatch", "reference"}:
        config["content"] += "\nextra: true\n"
        config["content_sha256"] = stages.digest(config["content"].encode())
        if kind == "reference":
            config["model_json"] = json.dumps(stages.yaml_document(config["content"]))
            config["model_json_sha256"] = stages.digest(config["model_json"].encode())
    raw = json.dumps(payload)
    if kind == "duplicate":
        raw = '{"version":1,' + raw[1:]
    if kind == "oversized":
        raw = "a" * 262145
    monkeypatch.setattr(
        stages,
        "runtime",
        lambda: pytest.fail("invalid request reached runtime/generation"),
    )
    with pytest.raises(stages.StageError):
        stages.generate(raw, tmp_path / "run")
    assert not list(tmp_path.iterdir())


def test_worker_records_actual_acceptance_and_preserves_raw_browser_request(
    monkeypatch, handoff, tmp_path
):
    counter = fake_generator(monkeypatch, handoff)
    handoff["validation"]["runtime"]["adapter_sha256"] = "d" * 64
    raw = json.dumps(request(handoff), ensure_ascii=False, indent=2)
    root = tmp_path / "run"
    result = stages.generate(raw, root)
    assert result["phase"] == "generated" and result["model_executed"] is False
    assert counter["generated"] == 1
    assert (root / "evidence/configuration-request.json").read_bytes() == raw.encode()
    accepted_raw = (root / "evidence/configuration-handoff.json").read_text()
    accepted, document = stages.admit(accepted_raw)
    assert accepted["purpose"] == "rompy-configuration-handoff-only"
    assert accepted["configuration"] == handoff["configuration"]
    assert accepted["validation"]["status"] == "accepted"
    assert accepted["validation"]["adapter"] == "prax-runtime-v1"
    facts = handoff["validation"]["runtime"]
    assert accepted["validation"]["runtime"] == facts
    assert accepted["validation"]["runtime_id"] == stages.digest(stages.encoded(facts))
    assert (
        accepted["validation"]["document_sha256"]
        == handoff["configuration"]["model_json_sha256"]
    )
    assert accepted["period"] == document["period"]
    assert accepted["input_references"] == handoff["input_references"]
    assert b"synthetic-datamesh-secret" not in accepted_raw.encode()
    assert (
        root / "evidence/configuration-request.json"
    ).stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize(
    "behavior,reason",
    [
        ("secret", "credential_in_workspace"),
        ("failed", "generation_or_workspace_failed"),
        ("stale", "model_outputs_present_before_run"),
    ],
)
def test_browser_request_keeps_existing_publication_guards(
    monkeypatch, handoff, tmp_path, behavior, reason
):
    fake_generator(monkeypatch, handoff, behavior)
    with pytest.raises(stages.StageError, match=reason):
        stages.generate(json.dumps(request(handoff)), tmp_path / "run")
    assert not list(tmp_path.iterdir())


def test_browser_comments_cannot_publish_the_runtime_credential(
    monkeypatch, handoff, tmp_path
):
    counter = fake_generator(monkeypatch, handoff)
    payload = request(handoff)
    config = payload["configuration"]
    config["content"] += "\n# synthetic-datamesh-secret\n"
    config["content_sha256"] = stages.digest(config["content"].encode())
    with pytest.raises(stages.StageError, match="credential_in_handoff"):
        stages.generate(json.dumps(payload), tmp_path / "run")
    assert counter["generated"] == 0
    assert not list(tmp_path.iterdir())


def test_existing_cli_handoff_bytes_and_metadata_are_not_rewritten(
    monkeypatch, handoff, tmp_path
):
    fake_generator(monkeypatch, handoff)
    raw = json.dumps(handoff, ensure_ascii=False, indent=3)
    root = tmp_path / "run"
    stages.generate(raw, root)
    assert (root / "evidence/configuration-handoff.json").read_bytes() == raw.encode()
    assert not (root / "evidence/configuration-request.json").exists()


def test_python_validation_rejects_before_credentials_or_workspace_and_redacts_error(
    monkeypatch, handoff, tmp_path
):
    counter = fake_generator(monkeypatch, handoff)
    monkeypatch.delenv("DATAMESH_TOKEN")

    class BadRun:
        @classmethod
        def model_validate(cls, document):
            raise ValidationError.from_exception_data(
                "SwanRun",
                [
                    {
                        "type": "value_error",
                        "loc": ("config",),
                        "input": document,
                        "ctx": {"error": ValueError("private-source-do-not-log")},
                    }
                ],
            )

    sys.modules["rompy.model"].ModelRun = BadRun
    with pytest.raises(
        stages.StageError, match="^configuration_validation_failed$"
    ) as error:
        stages.generate(json.dumps(request(handoff)), tmp_path / "run")
    assert "private-source" not in str(error.value)
    assert error.value.__suppress_context__
    assert counter["generated"] == 0
    assert not list(tmp_path.iterdir())


def test_browser_entrypoint_reports_validation_failure_without_private_values(
    monkeypatch, handoff, tmp_path, capsys
):
    from rompy_prax_runtime import __main__ as entrypoint

    counter = fake_generator(monkeypatch, handoff)
    monkeypatch.delenv("DATAMESH_TOKEN")

    class BadRun:
        @classmethod
        def model_validate(cls, document):
            raise ValidationError.from_exception_data(
                "SwanRun",
                [
                    {
                        "type": "value_error",
                        "loc": ("config",),
                        "input": document,
                        "ctx": {"error": ValueError("private-input-marker")},
                    }
                ],
            )

    sys.modules["rompy.model"].ModelRun = BadRun
    monkeypatch.setenv("ROMPY_HANDOFF_JSON", json.dumps(request(handoff)))
    monkeypatch.setattr(
        sys, "argv", ["runtime", "generate", "--destination", str(tmp_path / "run")]
    )
    assert entrypoint.main() == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "phase": "failed",
        "reason": "configuration_validation_failed",
    }
    assert not output.err
    assert "private-input-marker" not in output.out
    assert counter["generated"] == 0
    assert not list(tmp_path.iterdir())


def test_python_validator_cannot_rewrite_the_authored_provenance(
    monkeypatch, handoff, tmp_path
):
    fake_generator(monkeypatch, handoff)
    original_run = sys.modules["rompy.model"].ModelRun

    class MutatingRun(original_run):
        @classmethod
        def model_validate(cls, document):
            document["period"] = {"changed": "by validator"}
            return original_run.model_validate(document)

    sys.modules["rompy.model"].ModelRun = MutatingRun
    root = tmp_path / "run"
    stages.generate(json.dumps(request(handoff)), root)
    accepted, _ = stages.admit(
        (root / "evidence/configuration-handoff.json").read_text()
    )
    assert accepted["period"] == handoff["period"]
    assert accepted["configuration"] == handoff["configuration"]


def test_browser_python_validation_keeps_io_fence(monkeypatch, handoff, tmp_path):
    counter = fake_generator(monkeypatch, handoff)

    class ReadingRun:
        @classmethod
        def model_validate(cls, document):
            (tmp_path / "unexpected").write_text("not allowed")

    sys.modules["rompy.model"].ModelRun = ReadingRun
    with pytest.raises(stages.StageError, match="validation_io_blocked"):
        stages.generate(json.dumps(request(handoff)), tmp_path / "run")
    assert counter["generated"] == 0
    assert not list(tmp_path.iterdir())


def test_browser_workspace_remains_compatible_with_unchanged_verifier(
    monkeypatch, handoff, tmp_path
):
    from types import SimpleNamespace

    fake_generator(monkeypatch, handoff)
    root = tmp_path / "run"
    stages.generate(json.dumps(request(handoff)), root)
    profile = json.loads(stages.MANIFEST.read_bytes())["expected_outputs"]
    for name in ["PRINT", *profile["files"], *profile["netcdf"]]:
        (root / stages.STAGING / name).write_bytes(b"mock output, no SWAN execution")

    class Dataset:
        data_vars = {"hs": True}
        sizes = {"time": 25, "x": 3}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def load(self):
            pass

    monkeypatch.setitem(
        sys.modules, "xarray", SimpleNamespace(open_dataset=lambda *_a, **_k: Dataset())
    )
    result = stages.verify(root, tmp_path / "report")
    assert result["phase"] == "verified"
    assert "evidence/configuration-request.json" in result["files"]
    assert "evidence/configuration-handoff.json" in result["files"]
