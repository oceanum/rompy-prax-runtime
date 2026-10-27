import json
import pytest
from rompy_prax_runtime import stages


@pytest.fixture
def handoff():
    content = stages.REFERENCE.read_bytes().decode()
    document = stages.yaml_document(content)
    model_json = json.dumps(
        document, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    facts = {
        "python": "3.12.13",
        "packages": stages.EXPECTED,
        "sources_sha256": {"rompy": "a" * 64, "rompy-swan": "b" * 64},
    }
    return {
        "version": 1,
        "purpose": "rompy-configuration-handoff-only",
        "configuration": {
            "format": "yaml",
            "content": content,
            "content_sha256": stages.digest(content.encode()),
            "model_json": model_json,
            "model_json_sha256": stages.digest(model_json.encode()),
        },
        "validation": {
            "status": "accepted",
            "document_sha256": stages.digest(model_json.encode()),
            "runtime_id": "c" * 64,
            "runtime": facts,
        },
        "input_references": [
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
        ],
        "period": document["period"],
        "submission": {"enabled": False, "owner": "PRAX"},
    }
