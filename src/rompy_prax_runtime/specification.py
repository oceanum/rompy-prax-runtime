"""Inactive ProjectSpec construction. Rendering does not deploy or submit it."""

import argparse
from pathlib import Path
import re
import shlex

SWAN_IMAGE = "ghcr.io/rom-py/swan@sha256:17dd749381bdf4bfd1f5c717b2f4a07b3d740a125ca12d4b64db23963a4d6dc2"


def resources(cores, memory):
    return {
        "requests": {"cpu": str(cores), "memory": memory},
        "limits": {"cpu": str(cores), "memory": memory},
    }


def candidate(owner, repository, commit, credential_secret, *, mode="serial"):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner):
        raise ValueError("Explicit GitHub source owner required.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", repository):
        raise ValueError("Explicit source repository required.")
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Pin an exact Git commit, not a moving branch.")
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,31}", credential_secret):
        raise ValueError("Explicit existing native secret binding required.")
    if mode not in ("serial", "mpi"):
        raise ValueError("Only serial or single-node MPI proposal supported.")
    launcher = (
        "/usr/local/bin/swan-serial"
        if mode == "serial"
        else "/usr/bin/mpirun -np 4 /usr/local/bin/swan.exe"
    )
    shell = (
        "set -eu; if [ \"${DATAMESH_TOKEN+x}\" = x ]; then echo 'Unexpected Datamesh credential in model task' >&2; exit 64; fi; cd /work/run; sha256sum -c native-inputs.sha256; cd examples/example_declarative/run1; exec "
        + launcher
    )
    tasks = [
        {
            "name": "generate",
            "image": {"buildRef": "rompy-runtime"},
            "command": "/opt/rompy/bin/python -m rompy_prax_runtime generate",
            "timeout": 120,
            "resources": resources(1, "1Gi"),
            "env": [
                {
                    "name": "DATAMESH_TOKEN",
                    "secretRef": {"name": credential_secret, "key": "token"},
                }
            ],
            "inputs": {
                "parameters": [{"name": "handoff-json", "env": "ROMPY_HANDOFF_JSON"}]
            },
            "outputs": {
                "artifacts": [
                    {"name": "workspace", "path": "/work/run", "optional": True}
                ]
            },
        },
        {
            "name": "swan",
            "image": SWAN_IMAGE,
            "command": "bash -c " + shlex.quote(shell),
            "timeout": 120,
            "resources": resources(1 if mode == "serial" else 4, "512Mi"),
            "inputs": {"artifacts": [{"name": "workspace", "path": "/work/run"}]},
            "outputs": {"artifacts": [{"name": "workspace", "path": "/work/run"}]},
        },
        {
            "name": "verify",
            "image": {"buildRef": "rompy-runtime"},
            "command": "/opt/rompy/bin/python -m rompy_prax_runtime verify",
            "timeout": 60,
            "resources": resources(1, "512Mi"),
            "inputs": {"artifacts": [{"name": "workspace", "path": "/work/run"}]},
            "outputs": {
                "artifacts": [{"name": "verification", "path": "/work/report"}]
            },
        },
    ]
    # PRAX supplies retries even when omitted. Bound recovery explicitly and
    # distinguish transient infrastructure retry from an unsafe submission retry.
    for task in tasks:
        task["onDemand"] = True
        task["retryStrategy"] = {
            "limit": 1,
            "retryPolicy": "OnTransientError",
            "backoff": {"duration": "5s", "factor": 2, "maxDuration": "10s"},
        }
    # No global credentials, triggers, PVCs, privileged flags or invented security fields.
    pipeline_name = "swan-serial" if mode == "serial" else "swan-mpi"
    return {
        "name": "rompy-staged-smoke",
        "description": "INACTIVE staged reference candidate; build/runtime/admission prerequisites require review",
        "active": False,
        "resources": {
            "sources": [
                {
                    "name": "runtime-source",
                    "github": {
                        "username": owner,
                        "repository": owner + "/" + repository,
                    },
                }
            ],
            "builds": [
                {
                    "name": "rompy-runtime",
                    "sourceRef": {"name": "runtime-source", "ref": commit},
                    "dockerfile": "runtime/Dockerfile",
                    "resources": resources(1, "4Gi"),
                }
            ],
            "tasks": tasks,
            "pipelines": [
                {
                    "name": pipeline_name,
                    "timeout": 360,
                    "arguments": {
                        "parameters": [
                            {"name": "handoff-json", "value": "", "overridable": True}
                        ]
                    },
                    "steps": [
                        [
                            {
                                "name": "generate",
                                "taskRef": "generate",
                                "arguments": {
                                    "parameters": [
                                        {
                                            "name": "handoff-json",
                                            "value": "{{ workflow.parameters.handoff-json }}",
                                        }
                                    ]
                                },
                            }
                        ],
                        [
                            {
                                "name": "swan",
                                "taskRef": "swan",
                                "arguments": {
                                    "artifacts": [
                                        {
                                            "name": "workspace",
                                            "path": "/work/run",
                                            "stepRef": {
                                                "name": "generate",
                                                "artifactRef": "workspace",
                                            },
                                        }
                                    ]
                                },
                            }
                        ],
                        [
                            {
                                "name": "verify",
                                "taskRef": "verify",
                                "arguments": {
                                    "artifacts": [
                                        {
                                            "name": "workspace",
                                            "path": "/work/run",
                                            "stepRef": {
                                                "name": "swan",
                                                "artifactRef": "workspace",
                                            },
                                        }
                                    ]
                                },
                            }
                        ],
                    ],
                }
            ],
            "stages": [
                {
                    "name": "dev",
                    "active": False,
                    "resources": {"pipelines": [pipeline_name]},
                }
            ],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("owner", "repository", "commit", "credential-secret", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--mode", choices=("serial", "mpi"), default="serial")
    args = parser.parse_args()
    spec = candidate(
        args.owner, args.repository, args.commit, args.credential_secret, mode=args.mode
    )
    from ruamel.yaml import YAML

    with Path(args.output).open("x") as output:
        YAML().dump(spec, output)
    print(
        "Inactive candidate written. No PRAX call, build, deployment or run occurred."
    )


if __name__ == "__main__":
    main()
