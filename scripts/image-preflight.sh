#!/bin/sh
# Pure model construction only: never call generate/run or pass Datamesh credentials.
set -eu
if [ "$#" -ne 1 ]; then printf 'Usage: %s PRIVATE_CONFIGURATION_HANDOFF_JSON\n' "$0" >&2; exit 2; fi
docker run --rm -i --network none --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 1g --cpus 1 --pids-limit 64 \
  --entrypoint /opt/rompy/bin/python rompy-prax-runtime:staged-candidate -c '
import json,sys
from pydantic import Field
from rompy.model import ModelRun
from rompy_swan.config import SwanConfig
from rompy_prax_runtime.stages import admit,runtime,pure_validation
class SwanRun(ModelRun):
    config:SwanConfig=Field(...,discriminator="model_type")
handoff,document=admit(sys.stdin.read())
facts=runtime()
assert all(handoff["validation"]["runtime"][key]==facts[key] for key in ("python","packages","sources_sha256"))
with pure_validation():model=SwanRun.model_validate(document)
print(json.dumps({"accepted":True,"scope":"Offline source/library/Pydantic preflight only","python":facts["python"],"packages":facts["packages"],"adapter_sha256":facts["adapter_sha256"],"model_executed":False,"data_fetched":False}))
' < "$1"
