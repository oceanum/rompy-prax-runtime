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


def admit(raw):
    """Pure detached source/hash/reference admission; no datasets or model work."""
    try:
        if not isinstance(raw, str) or len(raw.encode()) > 262144:
            raise StageError("handoff_size")
        handoff = json.loads(raw, object_pairs_hook=pairs)
        if set(handoff) != {
            "version",
            "purpose",
            "configuration",
            "validation",
            "input_references",
            "period",
            "submission",
        }:
            raise StageError("handoff_shape")
        if (
            type(handoff["version"]) is not int
            or handoff["version"] != 1
            or handoff["purpose"] != "rompy-configuration-handoff-only"
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
        references = [
            {
                "role": "bottom",
                "kind": "datamesh",
                "datasource": "gebco_2008",
                "service": "https://datamesh.oceanum.tech",
            },
            {
                "role": "input[0]",
                "kind": "datamesh",
                "datasource": "era5_wind10m",
                "service": "https://datamesh.oceanum.tech",
            },
        ]
        if not same(handoff["period"], document["period"]) or not same(
            handoff["input_references"], references
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


def generate(raw, destination):
    """Only explicit generate entrypoint can access Datamesh; tests must mock it."""
    handoff, document = admit(raw)
    token = os.environ.get("DATAMESH_TOKEN")
    if not token:
        raise StageError("datamesh_credential_required")
    if token.encode() in encoded(handoff):
        raise StageError("credential_in_handoff")
    if os.environ.get(
        "DATAMESH_SERVICE", "https://datamesh.oceanum.tech"
    ) != "https://datamesh.oceanum.tech" or os.environ.get("DATAMESH_GATEWAY"):
        raise StageError("datamesh_endpoint_override")
    facts = runtime()
    reviewed = handoff["validation"].get("runtime", {})
    if any(
        reviewed.get(key) != facts[key]
        for key in ("python", "packages", "sources_sha256")
    ):
        raise StageError("reviewed_runtime_mismatch")
    from pydantic import Field
    from rompy.model import ModelRun
    from rompy_swan.config import SwanConfig

    class SwanRun(ModelRun):
        config: SwanConfig = Field(..., discriminator="model_type")

    with pure_validation():
        model = SwanRun.model_validate(document)
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
        outputs = json.loads(MANIFEST.read_bytes())["expected_outputs"]
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
        (evidence / "configuration-handoff.json").write_bytes(raw.encode())
        (evidence / "generation-runtime.json").write_bytes(encoded(facts))
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


def verify(source, report):
    """Read expected outputs after SWAN, never fetch data or rerun a model."""
    root = Path(source).absolute()
    tree(root)
    native = json.loads((root / "evidence/native-inputs.json").read_bytes())
    for name, expected in native.items():
        path = (root / name).resolve()
        if (
            not path.is_relative_to(root)
            or path.is_symlink()
            or not path.is_file()
            or digest(path.read_bytes()) != expected
        ):
            raise StageError("native_inputs_changed")
    profile = json.loads(MANIFEST.read_bytes())["expected_outputs"]
    staging = root / STAGING
    if (staging / "Errfile").is_file() and (staging / "Errfile").stat().st_size:
        raise StageError("swan_error_file")
    for name in ["PRINT", *profile["files"], *profile["netcdf"]]:
        path = staging / name
        if not path.is_file() or not path.stat().st_size:
            raise StageError("missing_model_outputs")
    import xarray as xr

    dimensions = {}
    for name in profile["netcdf"]:
        with xr.open_dataset(staging / name, engine="netcdf4") as dataset:
            if (
                not dataset.data_vars
                or not dataset.sizes
                or any(size == 0 for size in dataset.sizes.values())
            ):
                raise StageError("empty_model_outputs")
            dataset.load()
            dimensions[name] = dict(dataset.sizes)
    output = Path(report)
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "phase": "verified",
        "netcdf_dimensions": dimensions,
        "scope": "Output completeness/readability and unchanged native inputs, not scientific validity.",
    }
    result["files"] = {
        str(path.relative_to(root)): digest(path.read_bytes()) for path in tree(root)
    }
    (output / "verification.json").write_bytes(encoded(result))
    return result
