"""Generate/verify only. The model task uses the unchanged upstream SWAN image.

Initial admission is the known Datamesh .tech reference, not generic YAML execution.
"""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import sys
import shutil
import tempfile
import base64
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "reference/example-swan.yml"
MANIFEST = ROOT / "reference/manifest.json"
EXPECTED = {"rompy": "2.0.0a0", "rompy-swan": "0.11.1", "pydantic": "2.13.5"}
GUARDED = False
STAGING = Path("examples/example_declarative/run1")
MAX_TREE_BYTES = 64 * 1024 * 1024


class StageError(ValueError):
    pass


def audit(event, _args):
    if GUARDED and (
        event == "open"
        or event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn"))
        or event
        in {
            "os.system",
            "os.mkdir",
            "os.remove",
            "os.rmdir",
            "os.rename",
            "os.link",
            "os.symlink",
            "os.chdir",
            "os.listdir",
            "os.scandir",
            "shutil.copyfile",
            "shutil.rmtree",
        }
    ):
        raise StageError("validation_io_blocked")


sys.addaudithook(audit)


@contextmanager
def pure_validation():
    global GUARDED
    previous = GUARDED
    GUARDED = True
    try:
        yield
    finally:
        GUARDED = previous


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def pairs(items):
    value = {}
    for key, child in items:
        if not isinstance(key, str) or key in value:
            raise StageError("duplicate_keys")
        value[key] = child
    return value


def same(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            same(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    return left == right


def yaml_document(content):
    from ruamel.yaml import YAML
    from ruamel.yaml.constructor import SafeConstructor
    from ruamel.yaml.tokens import AnchorToken, AliasToken, TagToken, DirectiveToken

    class JsonConstructor(SafeConstructor):
        yaml_constructors = {
            **SafeConstructor.yaml_constructors,
            "tag:yaml.org,2002:timestamp": SafeConstructor.construct_scalar,
        }

    parser = YAML(typ="safe", pure=True)
    parser.version = (1, 2)
    parser.allow_duplicate_keys = False
    parser.Constructor = JsonConstructor
    for token in parser.scan(content):
        if isinstance(token, (AnchorToken, AliasToken, TagToken)):
            raise StageError("unsupported_yaml_alias_or_tag")
        if isinstance(token, DirectiveToken) and (
            token.name != "YAML" or token.value != (1, 2)
        ):
            raise StageError("unsupported_yaml_version")
    return parser.load(content)


def _input_references(document):
    grids = document["config"]["inpgrid"]
    return [
        {
            "role": "bottom" if index == 0 else f"input[{index - 1}]",
            "kind": "datamesh",
            "datasource": grid["source"]["datasource"],
            "service": grid["source"]["kwargs"]["service"],
        }
        for index, grid in enumerate([grids["bottom"], *grids.get("input", [])])
    ]


def admit(raw):
    """Pure detached source/hash/reference admission; no datasets or model work."""
    try:
        if not isinstance(raw, str) or len(raw.encode()) > 262144:
            raise StageError("handoff_size")
        handoff = json.loads(raw, object_pairs_hook=pairs)
        browser = (
            isinstance(handoff, dict)
            and handoff.get("purpose") == "rompy-configuration-request"
        )
        fields = {"version", "purpose", "configuration"}
        if not browser:
            fields |= {"validation", "input_references", "period", "submission"}
        if not isinstance(handoff, dict) or set(handoff) != fields:
            raise StageError("handoff_shape")
        if (
            type(handoff["version"]) is not int
            or handoff["version"] != 1
            or handoff["purpose"]
            not in {"rompy-configuration-handoff-only", "rompy-configuration-request"}
        ):
            raise StageError("handoff_version")
        config = handoff["configuration"]
        if set(config) != {
            "format",
            "content",
            "content_sha256",
            "model_json",
            "model_json_sha256",
        }:
            raise StageError("configuration_shape")
        for field in ("content", "model_json"):
            if (
                not isinstance(config[field], str)
                or len(config[field].encode()) > 65536
                or digest(config[field].encode()) != config[field + "_sha256"]
            ):
                raise StageError("configuration_hash")
        if config["format"] == "yaml":
            authored = yaml_document(config["content"])
        elif config["format"] == "json":
            authored = json.loads(config["content"], object_pairs_hook=pairs)
        else:
            raise StageError("configuration_format")
        document = json.loads(config["model_json"], object_pairs_hook=pairs)
        if not same(authored, document):
            raise StageError("source_json_mismatch")
        profile = json.loads(MANIFEST.read_bytes())
        reference = REFERENCE.read_bytes()
        if digest(reference) != profile["configuration"]["sha256"]:
            raise StageError("reference_integrity")
        if not same(document, yaml_document(reference.decode())):
            raise StageError("only_reviewed_reference_supported")
        # Source-only requests carry no prior Python acceptance claim. Both
        # formats still pass the same reference/source checks above.
        if browser:
            return deepcopy(handoff), deepcopy(document)
        if not same(handoff["period"], document["period"]) or not same(
            handoff["input_references"], _input_references(document)
        ):
            raise StageError("handoff_metadata_correlation")
        if (
            handoff["submission"].get("enabled") is not False
            or handoff["submission"].get("owner") != "PRAX"
        ):
            raise StageError("handoff_is_not_submission")
        validation = handoff["validation"]
        if (
            validation.get("status") != "accepted"
            or validation.get("document_sha256") != config["model_json_sha256"]
        ):
            raise StageError("validation_correlation")
        return deepcopy(handoff), deepcopy(document)
    except StageError:
        raise
    except Exception:
        raise StageError("malformed_handoff") from None


def checked_reference_document():
    """Load the immutable policy baseline and fail closed on byte tampering."""
    try:
        reference_bytes = REFERENCE.read_bytes()
        profile = json.loads(MANIFEST.read_bytes())
        expected_sha256 = profile["configuration"]["sha256"]
        if digest(reference_bytes) != expected_sha256:
            raise StageError("reference_integrity")
        return yaml_document(reference_bytes.decode("utf-8"))
    except StageError:
        raise
    except Exception:
        raise StageError("reference_integrity") from None


def prepare_bounded_model(document):
    """Internal, not admission: build and fence against the checked-in baseline.

    Public ``admit`` and ``generate`` remain fixed-reference-only until the
    integrated issue #5 evidence gate is accepted.
    """
    from pydantic import Field
    from rompy.model import ModelRun
    from rompy_swan.config import SwanConfig
    from .subset import effective_document, validate_actual_model

    class SwanRun(ModelRun):
        config: SwanConfig = Field(..., discriminator="model_type")

    reference_document = checked_reference_document()
    effective = effective_document(document, reference_document)
    try:
        with pure_validation():
            model = SwanRun.model_validate(deepcopy(effective))
            reference_model = SwanRun.model_validate(deepcopy(reference_document))
            validate_actual_model(model, reference_model, document, reference_document)
    except StageError:
        raise
    except Exception:
        raise StageError("configuration_policy_failed") from None
    return model


def runtime():
    versions = {name: metadata.version(name) for name in EXPECTED}
    if versions != EXPECTED or platform.python_version() != "3.12.13":
        raise StageError("runtime_versions")
    sources = {}
    for name in ("rompy", "rompy-swan"):
        distribution = metadata.distribution(name)
        files = sorted(
            item for item in distribution.files or [] if str(item).endswith(".py")
        )
        if not files:
            raise StageError("runtime_source_identity")
        sha = hashlib.sha256()
        for item in files:
            sha.update(str(item).encode())
            sha.update(distribution.locate_file(item).read_bytes())
        sources[name] = sha.hexdigest()
    return {
        "python": platform.python_version(),
        "packages": versions,
        "sources_sha256": sources,
        "adapter_sha256": digest(Path(__file__).read_bytes()),
        "profile_module_sha256": digest(
            Path(__file__).with_name("subset.py").read_bytes()
        ),
        "profile_id": "reference-fixed-v1",
        "profile_version": 1,
    }


def tree(root):
    files = []
    size = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise StageError("workspace_symlink")
        if path.is_file():
            size += path.stat().st_size
            if size > MAX_TREE_BYTES:
                raise StageError("workspace_size")
            files.append(path)
    return files


def native_hashes(root):
    return {
        str(path.relative_to(root)): digest(path.read_bytes())
        for path in tree(root / STAGING)
    }


def _portable_artifact_modes(root):
    """Make a credential-checked workspace readable after archive UID changes."""
    for path in tree(root):
        executable = bool(path.stat().st_mode & 0o111)
        path.chmod(0o755 if executable else 0o644)
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)


def _worker_handoff(request, document, facts):
    """Create truthful provenance only after the worker's Python check passed."""
    return {
        "version": 1,
        "purpose": "rompy-configuration-handoff-only",
        "configuration": deepcopy(request["configuration"]),
        "validation": {
            "status": "accepted",
            "document_sha256": request["configuration"]["model_json_sha256"],
            "runtime_id": digest(encoded(facts)),
            "adapter": "prax-runtime-v1",
            "runtime": deepcopy(facts),
            "scope": "Worker public Pydantic acceptance before extraction; not data readiness or scientific validation.",
        },
        "input_references": _input_references(document),
        "period": deepcopy(document["period"]),
        "submission": {"enabled": False, "owner": "PRAX"},
    }


def generate(raw, destination):
    """Only explicit generate entrypoint can access Datamesh; tests must mock it."""
    handoff, document = admit(raw)
    browser = handoff["purpose"] == "rompy-configuration-request"
    facts = runtime()
    if not browser:
        reviewed = handoff["validation"].get("runtime", {})
        if any(
            reviewed.get(key) != facts[key]
            for key in ("python", "packages", "sources_sha256")
        ):
            raise StageError("reviewed_runtime_mismatch")
    from pydantic import Field, ValidationError
    from rompy.model import ModelRun
    from rompy_swan.config import SwanConfig

    class SwanRun(ModelRun):
        config: SwanConfig = Field(..., discriminator="model_type")

    try:
        with pure_validation():
            model = SwanRun.model_validate(deepcopy(document))
    except ValidationError:
        # Pydantic errors may contain the private input. Keep task logs value-free.
        raise StageError("configuration_validation_failed") from None
    if browser:
        handoff = _worker_handoff(handoff, document, facts)
    token = os.environ.get("DATAMESH_TOKEN")
    if not token:
        raise StageError("datamesh_credential_required")
    if token.encode() in encoded(handoff):
        raise StageError("credential_in_handoff")
    if os.environ.get(
        "DATAMESH_SERVICE", "https://datamesh.oceanum.tech"
    ) != "https://datamesh.oceanum.tech" or os.environ.get("DATAMESH_GATEWAY"):
        raise StageError("datamesh_endpoint_override")
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise StageError("destination_exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Argo can collect artifacts even after container failure. Never expose an
    # incomplete or credential-bearing workspace at the declared output path.
    root = Path(tempfile.mkdtemp(prefix="rompy-preparing-", dir=destination.parent))
    previous = Path.cwd()
    try:
        working = root / "examples"
        working.mkdir()
        try:
            os.chdir(working)
            import dask

            with (
                open(os.devnull, "w") as quiet,
                redirect_stdout(quiet),
                redirect_stderr(quiet),
                dask.config.set(scheduler="synchronous"),
            ):
                generated = model.generate()
            if (
                not generated.success
                or Path(model.staging_dir).resolve() != root / STAGING
            ):
                raise StageError("generation_or_workspace_failed")
        finally:
            os.chdir(previous)
        outputs = _expected_from_source(handoff)
        if any(
            (root / STAGING / name).exists()
            for name in ["PRINT", "Errfile", *outputs["netcdf"], *outputs["files"]]
        ):
            raise StageError("model_outputs_present_before_run")
        files = native_hashes(root)
        if str(STAGING / "INPUT") not in files:
            raise StageError("missing_control_file")
        if str(root).encode() in (root / STAGING / "INPUT").read_bytes():
            raise StageError("nonportable_generated_control")
        evidence = root / "evidence"
        evidence.mkdir()
        if browser:
            (evidence / "configuration-request.json").write_bytes(raw.encode())
            handoff_bytes = encoded(handoff)
        else:
            handoff_bytes = raw.encode()
        (evidence / "configuration-handoff.json").write_bytes(handoff_bytes)
        (evidence / "generation-runtime.json").write_bytes(encoded(facts))
        profile_record = {
            "contract": "rompy-prax-generation-profile",
            "version": 2,
            "profile_id": "reference-fixed-v1",
            "profile_version": 1,
            "source_sha256": handoff["configuration"]["content_sha256"],
            "model_json_sha256": handoff["configuration"]["model_json_sha256"],
            "runtime_sha256": digest(encoded(facts)),
            "expected_outputs": outputs,
        }
        (evidence / "generation-profile.json").write_bytes(encoded(profile_record))
        for path in (
            evidence / "configuration-handoff.json",
            evidence / "generation-runtime.json",
            evidence / "generation-profile.json",
        ):
            files[str(path.relative_to(root))] = digest(path.read_bytes())
        if browser:
            path = evidence / "configuration-request.json"
            files[str(path.relative_to(root))] = digest(path.read_bytes())
        files = dict(sorted(files.items()))
        (evidence / "native-inputs.json").write_bytes(encoded(files))
        (root / "native-inputs.sha256").write_text(
            "".join(f"{value}  {name}\n" for name, value in files.items())
        )
        patterns = {
            token.encode(),
            quote(token, safe="").encode(),
            base64.b64encode(token.encode()),
            json.dumps(token).encode(),
        }
        for path in tree(root):
            raw_file = path.read_bytes()
            if any(pattern in raw_file for pattern in patterns):
                raise StageError("credential_in_workspace")
        _portable_artifact_modes(root)
        root.chmod(0o755)
        root.rename(destination)
        return {
            "phase": "generated",
            "native_files": len(files),
            "model_executed": False,
        }
    finally:
        if root.exists():
            shutil.rmtree(root)


def _safe_native_path(name):
    if (
        not isinstance(name, str)
        or not name
        or any(ord(c) < 32 or ord(c) == 127 for c in name)
    ):
        return False
    if "\\" in name or name.startswith("/") or "//" in name:
        return False
    parts = name.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _read_json(path):
    try:
        return json.loads(path.read_bytes(), object_pairs_hook=pairs)
    except Exception:
        raise StageError("malformed_workspace_evidence") from None


def _expected_from_source(handoff):
    _, document = admit(encoded(handoff).decode())
    period = document["period"]
    start_text = str(period["start"])
    from datetime import datetime, timezone

    start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = start + _duration(period["duration"])
    hot = "hotfile_" + end.strftime("%Y%m%dT%H%M%S") + ".txt"
    grid = document["config"]["cgrid"]["grid"]
    duration = _duration(period["duration"]).total_seconds() / 3600
    interval = _duration(period["interval"]).total_seconds() / 3600
    if interval <= 0 or duration % interval:
        raise StageError("unsupported_workspace_profile")
    time_count = int(duration / interval) + 1
    return {
        "netcdf": ["swangrid.nc", "swanspec.nc"],
        "files": ["swantable.txt", hot],
        "dimensions": {
            "swangrid.nc": {
                "time": time_count,
                "yc": int(grid["my"]) + 1,
                "xc": int(grid["mx"]) + 1,
            },
            "swanspec.nc": {
                "points": len(document["config"]["output"]["points"]["xp"]),
                "time": time_count,
                "frequency": 35,
                "direction": 36,
            },
        },
    }


def _duration(value):
    match = re.fullmatch(r"(\d+)([dhms])", str(value))
    if not match:
        raise StageError("unsupported_workspace_profile")
    from datetime import timedelta

    number, unit = int(match.group(1)), match.group(2)
    return timedelta(
        **{
            "d": {"days": number},
            "h": {"hours": number},
            "m": {"minutes": number},
            "s": {"seconds": number},
        }[unit]
    )


def _validate_native(root):
    manifest_path = root / "evidence/native-inputs.json"
    ledger_path = root / "native-inputs.sha256"
    if (
        manifest_path.is_symlink()
        or ledger_path.is_symlink()
        or not manifest_path.is_file()
        or not ledger_path.is_file()
    ):
        raise StageError("missing_native_ledger")
    native = _read_json(manifest_path)
    if manifest_path.read_bytes() != encoded(native):
        raise StageError("noncanonical_native_manifest")
    if not isinstance(native, dict) or any(
        not _safe_native_path(k)
        or not isinstance(v, str)
        or not re.fullmatch(r"[0-9a-f]{64}", v)
        for k, v in native.items()
    ):
        raise StageError("malformed_native_manifest")
    rows = {}
    try:
        for line in ledger_path.read_text(encoding="ascii").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if (
                not match
                or not _safe_native_path(match.group(2))
                or match.group(2) in rows
            ):
                raise ValueError
            rows[match.group(2)] = match.group(1)
    except Exception:
        raise StageError("malformed_native_ledger") from None
    expected_ledger = "".join(
        f"{sha}  {name}\n" for name, sha in sorted(native.items())
    )
    if rows != native or ledger_path.read_text(encoding="ascii") != expected_ledger:
        raise StageError("native_ledgers_disagree")
    required = {
        str(STAGING / "INPUT"),
        "evidence/configuration-handoff.json",
        "evidence/generation-runtime.json",
        "evidence/generation-profile.json",
    }
    if (root / "evidence/configuration-request.json").exists():
        required.add("evidence/configuration-request.json")
    if not required.issubset(native):
        raise StageError("missing_mandatory_native_input")
    actual = set()
    for path in tree(root / STAGING):
        actual.add(str(path.relative_to(root)))
    output_names = {"PRINT", "Errfile", "swangrid.nc", "swanspec.nc", "swantable.txt"}
    expected_outputs = json.loads(MANIFEST.read_bytes())["expected_outputs"]
    output_names.update(expected_outputs["files"])
    output_names.update(expected_outputs["netcdf"])
    actual = {name for name in actual if Path(name).name not in output_names}
    expected = actual | required
    if set(native) != expected:
        raise StageError("native_input_coverage")
    for name, sha in native.items():
        path = root / name
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != sha:
            raise StageError("native_inputs_changed")
    return native


def verify(source, report):
    """Independently verify versioned provenance, native inputs and outputs."""
    root = Path(source).absolute()
    tree(root)
    native = _validate_native(root)
    profile = _read_json(root / "evidence/generation-profile.json")
    keys = {
        "contract",
        "version",
        "profile_id",
        "profile_version",
        "source_sha256",
        "model_json_sha256",
        "runtime_sha256",
        "expected_outputs",
    }
    if (
        not isinstance(profile, dict)
        or set(profile) != keys
        or profile["contract"] != "rompy-prax-generation-profile"
        or type(profile["version"]) is not int
        or profile["version"] != 2
        or profile["profile_id"] != "reference-fixed-v1"
        or profile["profile_version"] != 1
    ):
        raise StageError("unsupported_workspace_version")
    handoff_bytes = (root / "evidence/configuration-handoff.json").read_bytes()
    handoff, document = admit(handoff_bytes.decode())
    if "evidence/configuration-request.json" in native:
        request_bytes = (root / "evidence/configuration-request.json").read_bytes()
        request, _ = admit(request_bytes.decode())
        if (
            request["configuration"] != handoff["configuration"]
            or handoff["validation"].get("status") != "accepted"
        ):
            raise StageError("provenance_mismatch")
    facts = _read_json(root / "evidence/generation-runtime.json")
    validation = handoff.get("validation", {})
    fact_keys = {
        "python",
        "packages",
        "sources_sha256",
        "adapter_sha256",
        "profile_module_sha256",
        "profile_id",
        "profile_version",
    }
    if (
        not isinstance(facts, dict)
        or set(facts) != fact_keys
        or not all(
            isinstance(facts.get(key), str)
            and re.fullmatch(r"[0-9a-f]{64}", facts[key])
            for key in ("adapter_sha256", "profile_module_sha256")
        )
        or profile["source_sha256"] != handoff["configuration"]["content_sha256"]
        or profile["model_json_sha256"] != handoff["configuration"]["model_json_sha256"]
        or profile["runtime_sha256"] != digest(encoded(facts))
        or facts.get("profile_id") != profile["profile_id"]
        or facts.get("profile_version") != profile["profile_version"]
        or validation.get("runtime") != facts
    ):
        raise StageError("provenance_mismatch")
    expected = _expected_from_source(handoff)
    if not same(profile["expected_outputs"], expected):
        raise StageError("output_expectations_mismatch")
    staging = root / STAGING
    if (staging / "Errfile").is_file() and (staging / "Errfile").stat().st_size:
        raise StageError("swan_error_file")
    for name in ["PRINT", *expected["files"], *expected["netcdf"]]:
        path = staging / name
        if not path.is_file() or not path.stat().st_size:
            raise StageError("missing_model_outputs")
    import xarray as xr

    dimensions = {}
    for name in expected["netcdf"]:
        try:
            with xr.open_dataset(staging / name, engine="netcdf4") as dataset:
                dataset.load()
                actual_dims = dict(dataset.sizes)
                if not dataset.data_vars or actual_dims != expected["dimensions"][name]:
                    raise StageError("output_dimensions_mismatch")
                dimensions[name] = actual_dims
        except StageError:
            raise
        except Exception:
            raise StageError("unreadable_model_outputs") from None
    output = Path(report)
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "phase": "verified",
        "netcdf_dimensions": dimensions,
        "profile_id": profile["profile_id"],
        "source_sha256": profile["source_sha256"],
        "model_json_sha256": profile["model_json_sha256"],
        "runtime_sha256": profile["runtime_sha256"],
        "scope": "Output completeness/readability and unchanged native inputs, not scientific validity.",
    }
    result["files"] = {
        str(path.relative_to(root)): digest(path.read_bytes()) for path in tree(root)
    }
    (output / "verification.json").write_bytes(encoded(result))
    return result
