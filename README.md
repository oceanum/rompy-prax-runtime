# ROMPY → SWAN staged PRAX reference (local candidate)

This repository separates runtime execution from the frontend workbench and configuration-only `oceanum rompy` plugin. It is not a modelling API, run database or operations CLI. PRAX owns builds, releases, submission, status/logs, retries and artifacts.

## Pipeline contract

| Phase | Image | Resources | Datamesh credential |
|---|---|---|---|
| Generate | This Python/rompy image, selected through PRAX `buildRef` | 1 requested/limited CPU, 1Gi memory | Approved scoped development native `secretRef` binding, generation only |
| SWAN | Unchanged `ghcr.io/rom-py/swan@sha256:17dd749381bdf4bfd1f5c717b2f4a07b3d740a125ca12d4b64db23963a4d6dc2` | Serial: 1 CPU; proposed single-node MPI: 4 CPUs; 512Mi | None; task refuses an unexpected Datamesh token |
| Verify | Same Python image as generation | 1 CPU, 512Mi | None |

The third phase is output verification, not invented scientific postprocessing. Optional derived-product processing can be added separately after this baseline works. CPU requests/limits are not exclusive physical-core guarantees. MPI across multiple nodes is not configured.

Workspaces pass through explicit PRAX `stepRef.artifactRef` bindings. There is no PVC, host mount, sudo/tmpfs setup or Docker-in-Docker requirement. Generation builds a private temporary workspace and publishes the declared artifact directory **only after** input manifest, portability and credential checks. Failed generation leaves no declared output path to archive. The model task verifies native-input checksums before running the upstream binary, and verification checks those files again after execution.

Task environment bindings use the current canonical `secretRef: {name, key}` contract; the retired `userSecretRef` selector is rejected by the server. User scope belongs to managed-secret creation/access, not a different task environment field. The candidate's reference names the approved user-scoped secret without embedding its value.

PRAX applies infrastructure retries even when `retryStrategy` is omitted. The candidate explicitly requests on-demand scheduling and one retry restricted to `OnTransientError`, bounded backoff. This is not exactly-once execution, nor permission to retry an unknown submission outcome. Deterministic model/code failures and OOM are not intended to be retried by that policy. Actual deployed behavior still needs verification.

## Initial configuration admission

The initial adapter accepts only the logical values of the preserved `.tech` Datamesh reference in `reference/example-swan.yml`, whose exact source SHA256 is `998436b3164ccc8f7e971faea57ff8365d58435653db299a7cb8a90e67980a42`. Comments/formatting may differ but are retained in the exact handoff. This is **not** a general user-YAML/template execution service. No local catalog/input assets are packaged.

Input is the configuration-only plugin's `rompy-configuration-handoff-only` JSON record. The adapter rechecks exact source/model hashes, source↔JSON semantics, supported reference values and validation-document correlation. Generation independently checks Python/package/source identities against the recorded runtime and constructs the real narrowed public `ModelRun`/`SwanConfig` before calling public `generate()` with synchronous scheduling. No upstream templates or generated `INPUT` are patched.

The handoff is not an authorization signature or PRAX receipt. PRAX must authorize the submitting actor and bind the reviewed release; source/runtime checks do not fix the unresolved reviewed-release admission race. Datasource IDs remain mutable; native file hashes record what was actually generated in each successful attempt.

The model phase is a native SWAN invocation: `/usr/local/bin/swan-serial` for the baseline, or the proposed `/usr/bin/mpirun -np 4 /usr/local/bin/swan.exe`. The public image already supplies both binaries and selects MPI under `mpirun`; this repository does not rebuild or modify SWAN. Serial and MPI are separate acceptance gates.

Verification requires `PRINT`, the configured table/restart files and both NetCDF outputs; it reopens and actually loads the datasets. Exit zero alone is insufficient. Output completeness/readability is not calibration, scientific suitability or proof of arbitrary configurations.

## Build and rendering

The Python image uses pinned public Python3.12.13 and uv image digests, hash-locked dependencies and exact public rompy/rompy-swan Git commits. Its filesystem is owned by UID10001 for normal generation/report work. That is not proof of PRAX artifact extraction ownership or a pod-level security context; those must be verified in the target environment. The unchanged SWAN image has its own upstream user/runtime defaults. No privileged settings or permission broadening are added.

`.dockerignore` is an allowlist for source, locks and reference metadata. Credentials, `.runtime`, local data and tests are not build inputs. A local build does not fetch model data or run a model:

```sh
docker build --platform linux/amd64 -f runtime/Dockerfile \
  -t rompy-prax-runtime:staged-candidate .
```

PRAX should ultimately perform this build from an approved reachable repository and exact commit—no separate manual registry-push workflow is required. The approved public source destination is `oceanum/rompy-prax-runtime`, under Apache 2.0. Upstream notices are retained in `third-party/`; this does not relicense the unchanged SWAN image or other dependencies. Reachability and the exact source commit must be verified before a PRAX build.

Render a new inactive candidate after supplying real reviewed bindings (do not invent a source repository or secret):

```sh
PYTHONPATH=src python -m rompy_prax_runtime.specification \
  --owner YOUR_GITHUB_OWNER --repository YOUR_RUNTIME_REPOSITORY \
  --commit EXACT_40_CHARACTER_COMMIT --credential-secret EXISTING_USER_SECRET \
  --mode serial --output inactive-prax.yml
```

Both project and stage are inactive. No triggers are created. This command does not call PRAX, build an image, deploy or submit a run. `--mode mpi` describes a separate four-process, single-node proposal, not a proven execution mode. Source publication/access, credential binding, artifact repository retention and actual task workspace permissions remain prerequisites.

The pipeline's `handoff-json` parameter must be a **serialized JSON string**, not a nested object that the current PRAX API would stringify as a Python representation. The published pipeline CLI accepts a JSON `--parameters` object; do not invent `@file` expansion support. Configuration content transferred as parameters/artifacts is subject to PRAX visibility/retention. Credentials never belong in the handoff or workflow parameters.

Use the CRD-compatible parameter name `handoff-json` throughout task inputs, pipeline declarations and argument bindings; underscores are rejected by the live Kubernetes CRD even if server validation accepts them. The generation container still receives `ROMPY_HANDOFF_JSON`. Pin the concrete target with canonical `orgRef`; do not rely on the CLI login's active organisation for inventory or deployment targeting.

The image-build budget is 1 CPU / 4Gi memory, separately from task runtime limits. A real PRAX/Kaniko build installed the locked packages successfully but was OOM-killed during full-filesystem snapshotting at 2Gi; the 4Gi build succeeded. This is build evidence, not a staged model-run claim.

The model wrapper's credential guard emits only a fixed diagnostic to stdout and exits 64; it never prints a credential value. Avoiding a nonessential `>&2` redirection keeps this definition in the JSON-encoding subset shared by the currently deployed PRAX controllers. A live check found differing HTML escaping in their fingerprint calculations. No stored fingerprint, readiness flag or integrity check is overridden; a general canonicalization repair belongs in PRAX, separately from this proof.

The sequential artifact graph uses `dag` with explicit `generate → swan → verify` dependencies. The deployed PRAX translator renders `stepRef.artifactRef` using Argo's `tasks.*` context, which belongs to DAGs; a steps-form workflow was rejected by Argo before any pod ran. Do not confuse successful PRAX admission with native Argo spec acceptance.

## Local verification

The local gate passes **26 tests** and Ruff. Tests use mocked generation/model outputs; no actual generation or model execution occurs. `examples/inactive-serial.fixture.yml` and `examples/inactive-mpi.fixture.yml` are offline review fixtures with explicitly synthetic source/commit/secret names, not deployable targets.

The Python image built locally and accepted the actual configuration-only CLI handoff in a network-disabled container using real pinned public Pydantic models. Its reviewed Python/package/source identities matched. The sandbox retained a read-only root, UID10001, bounded CPU/memory/PIDs and a 64MiB container-only `/tmp`. An initial fully read-only attempt failed because Cartopy needs temporary storage during import; no model code or validation guard was weakened. Reproduce the pure check with `sh scripts/image-preflight.sh /path/to/private-handoff.json` after building locally.

The unchanged pinned SWAN image was pulled and its serial/MPI binaries, selector and launcher were checked for presence/executability, without launching the model. `verification.json` records nonsecret local image/preflight facts; the local image ID is **not** a published/pullable runner release. The fresh public PRAX schema still advertises only `stage_ref`/`parameters` for `PipelineRunRequest`, not a reviewed-release/idempotency field.

Read-only discovery found no visible user-scoped runtime credential references in the active development tenant. No secret values were requested. Source publication/access and an explicit scoped credential binding are therefore still outstanding, alongside full server validation and actual serial/MPI workflow evidence.

## Validation and acceptance boundaries

For a separate local test environment:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m pytest -q
ruff check src tests
```

Local tests exercise handoff parsing/correlation, reference/runtime fences, mocked generation, atomic artifact publication, failure/secret cleanup, native file integrity, output checks and task/credential/artifact/resource wiring. They do **not** fetch data, generate actual model inputs or run SWAN.

The installed `oceanum-prax-sdk 0.3.2` exposes explicitly partial ProjectSpec/PipelineSpec models. Passing those local checks is **not full server structural/prerequisite admission**. The published `oceanum prax validate` command performs an authenticated POST to the PRAX API, not an offline schema check. A later validation call needs a concrete reviewed target/source/secret and must remain distinct from deployment/run.

Use the published `oceanum-prax-cli` for actual PRAX operations; don't add lifecycle wrappers to the ROMPY plugin. Real server validation, image/release readiness, artifact permissions/retention, atomic reviewed-release enforcement/unknown-outcome reconciliation and authoritative console identity remain unproven here.

The 64MiB generation-tree threshold is a post-generation publication check, **not** a hard download/filesystem quota. Pod CPU/memory/timeout and ephemeral-storage behavior must be reviewed at deployment. The generation adapter is a trusted fixed-case tool, not a hostile-code sandbox.

No registry publication, remote PRAX build/deployment/submission, data extraction or new SWAN/MPI execution is authorized or claimed by preparing this candidate. Existing historical combined-image serial smoke remains separate evidence.
