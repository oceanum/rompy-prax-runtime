"""Exercise the shipped preflight's embedded Python, without Docker or a model."""

from copy import deepcopy
import io
import json
import sys

import pytest
from pydantic import ValidationError

from rompy_prax_runtime import stages
from test_stages import fake_generator


def execute_preflight(monkeypatch, payload):
    script = (stages.ROOT / "scripts/image-preflight.sh").read_text()
    body = script.split("-c '\n", 1)[1].rsplit("' < ", 1)[0]
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    exec(compile(body, "image-preflight.sh:embedded-python", "exec"), {})


@pytest.mark.parametrize("browser", [False, True])
def test_shipped_preflight_accepts_both_formats_only_after_python_check(
    monkeypatch, handoff, capsys, browser
):
    handoff["validation"]["runtime"]["adapter_sha256"] = "d" * 64
    counter = fake_generator(monkeypatch, handoff)
    payload = (
        {
            "version": 1,
            "purpose": "rompy-configuration-request",
            "configuration": deepcopy(handoff["configuration"]),
        }
        if browser
        else handoff
    )
    execute_preflight(monkeypatch, payload)
    result = json.loads(capsys.readouterr().out)
    assert result["accepted"] is True
    assert result["adapter_sha256"] == "d" * 64
    assert result["model_executed"] is False and result["data_fetched"] is False
    assert counter["generated"] == 0


def test_shipped_preflight_keeps_legacy_runtime_identity_check(
    monkeypatch, handoff, capsys
):
    fake_generator(monkeypatch, handoff)
    facts = {
        **handoff["validation"]["runtime"],
        "python": "wrong",
        "adapter_sha256": "d" * 64,
    }
    monkeypatch.setattr(stages, "runtime", lambda: facts)
    with pytest.raises(stages.StageError, match="reviewed_runtime_mismatch"):
        execute_preflight(monkeypatch, handoff)
    assert not capsys.readouterr().out


def test_shipped_preflight_does_not_accept_or_echo_failed_python_validation(
    monkeypatch, handoff, capsys
):
    handoff["validation"]["runtime"]["adapter_sha256"] = "d" * 64
    counter = fake_generator(monkeypatch, handoff)

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
                        "ctx": {"error": ValueError("private-config-marker")},
                    }
                ],
            )

    sys.modules["rompy.model"].ModelRun = BadRun
    payload = {
        "version": 1,
        "purpose": "rompy-configuration-request",
        "configuration": handoff["configuration"],
    }
    with pytest.raises(
        stages.StageError, match="^configuration_validation_failed$"
    ) as error:
        execute_preflight(monkeypatch, payload)
    assert "private-config-marker" not in str(error.value)
    assert error.value.__suppress_context__
    assert not capsys.readouterr().out
    assert counter["generated"] == 0
