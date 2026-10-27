from pathlib import Path
import shlex

import pytest
from prax.spec import ProjectSpec
from prax.spec.pipeline import PipelineSpec
from prax.spec.secret_refs import (
    environment_secret_references,
    SecretReferenceShapeError,
)
from rompy_prax_runtime.specification import candidate, SWAN_IMAGE

ROOT = Path(__file__).parents[1]


def spec(mode="serial"):
    # Synthetic names are offline fixtures, not a claim about existing remote resources.
    return candidate("example", "runtime", "a" * 40, "datamesh-tech", mode=mode)


def test_separate_images_cores_credential_and_artifact_handoffs():
    document = spec()
    resources = document["resources"]
    generate, model, verify = resources["tasks"]
    assert document["active"] is False and resources["stages"][0]["active"] is False
    assert generate["image"] == verify["image"] == {"buildRef": "rompy-runtime"}
    assert model["image"] == SWAN_IMAGE and "@sha256:" in model["image"]
    assert [
        task["resources"]["limits"]["cpu"] for task in (generate, model, verify)
    ] == ["1", "1", "1"]
    assert generate["env"][0]["name"] == "DATAMESH_TOKEN"
    assert all(not task.get("env") for task in (model, verify))
    assert all(task["onDemand"] is True for task in resources["tasks"])
    assert all(
        task["retryStrategy"]["limit"] == 1
        and task["retryStrategy"]["retryPolicy"] == "OnTransientError"
        and task["retryStrategy"]["backoff"]["factor"] == 2
        for task in resources["tasks"]
    )
    assert (
        generate["outputs"]["artifacts"][0]["optional"] is True
    )  # Failed generation publishes nothing.
    pipeline = resources["pipelines"][0]
    assert "triggers" not in pipeline and "volumes" not in pipeline
    for current, previous in zip(pipeline["steps"][1:], ("generate", "swan")):
        artifact = current[0]["arguments"]["artifacts"][0]
        assert artifact["stepRef"] == {"name": previous, "artifactRef": "workspace"}
        assert artifact["path"] == "/work/run"
    assert resources["builds"][0]["sourceRef"]["ref"] == "a" * 40


def test_canonical_secret_reference_contract_rejects_legacy_user_secret_alias():
    env = spec()["resources"]["tasks"][0]["env"]
    refs = environment_secret_references(env, "generate.env")
    assert len(refs) == 1
    assert (refs[0].name, refs[0].key, refs[0].environment_variable) == (
        "datamesh-tech",
        "token",
        "DATAMESH_TOKEN",
    )
    with pytest.raises(SecretReferenceShapeError):
        environment_secret_references(
            [
                {
                    "name": "DATAMESH_TOKEN",
                    "userSecretRef": {"name": "datamesh-tech", "key": "token"},
                }
            ],
            "generate.env",
        )


def test_native_serial_and_explicit_single_node_mpi_not_custom_model_runner():
    serial = spec()["resources"]["tasks"][1]
    assert shlex.split(serial["command"])[0:2] == ["bash", "-c"]
    command = shlex.split(serial["command"])[2]
    assert (
        "${DATAMESH_TOKEN+x}" in command
        and "sha256sum -c native-inputs.sha256" in command
    )
    assert command.endswith("exec /usr/local/bin/swan-serial")
    mpi = spec("mpi")["resources"]["tasks"][1]
    assert mpi["resources"]["limits"]["cpu"] == "4"
    assert shlex.split(mpi["command"])[2].endswith(
        "exec /usr/bin/mpirun -np 4 /usr/local/bin/swan.exe"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"owner": "https://bad"},
        {"repository": "../bad"},
        {"commit": "main"},
        {"credential_secret": ""},
        {"mode": "multinode"},
    ],
)
def test_no_invented_moving_or_arbitrary_bindings(kwargs):
    values = {
        "owner": "example",
        "repository": "runtime",
        "commit": "a" * 40,
        "credential_secret": "datamesh-tech",
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        candidate(**values)


def test_published_sdk_subset_checks_not_full_server_admission():
    # These published models deliberately accept extra workload fields. Never label
    # this as the authenticated PRAX API's full structural/prerequisite validation.
    document = spec()
    assert ProjectSpec.model_validate(document).resources
    for pipeline in document["resources"]["pipelines"]:
        assert PipelineSpec.model_validate(pipeline).name == "swan-serial"


def test_pinned_generation_dockerfile_no_swan_binary_or_private_context():
    dockerfile = (ROOT / "runtime/Dockerfile").read_text()
    assert "python:3.12.13-slim@sha256:" in dockerfile
    assert "--require-hashes" in dockerfile
    assert "cf80d0d03dddf032bc27282a1f8a1607d69b4184" in dockerfile
    assert "f5ed326f6287a9f0f884efd2498d20ee7948c47d" in dockerfile
    assert "FROM ghcr.io/rom-py/swan" not in dockerfile
    assert "USER 10001:10001" in dockerfile
    ignored = (ROOT / ".dockerignore").read_text().splitlines()
    assert ignored[0] == "**"
    assert all(".runtime" not in line and ".env" not in line for line in ignored[1:])
