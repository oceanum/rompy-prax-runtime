# ROMPY → SWAN staged PRAX reference (serial acceptance verified)

This repository separates runtime execution from the frontend workbench and configuration-only `oceanum rompy` plugin. It is not a modelling API, run database or operations CLI. PRAX owns builds, releases, submission, status/logs, retries and artifacts.

## Pipeline contract

| Phase | Image | Resources | Datamesh credential |
|---|---|---|---|
| Generate | This Python/rompy image, selected through PRAX `buildRef` | 1 requested/limited CPU, 1Gi memory | Approved scoped development native `secretRef` binding, generation only |
| SWAN | Unchanged `ghcr.io/rom-py/swan@sha256:17dd749381bdf4bfd1f5c717b2f4a07b3d740a125ca12d4b64db23963a4d6dc2` | Serial: 1 CPU; proposed single-node MPI: 4 CPUs; 512Mi | None; task refuses an unexpected Datamesh token |
| Verify | Pinned Python/rompy image; an earlier reviewed digest can be retained | 1 CPU, 512Mi | None |

The third phase is output verification, not invented scientific postprocessing. Optional derived-product processing can be added separately after this baseline works. CPU requests/limits are not exclusive physical-core guarantees. MPI across multiple nodes is not configured.

Workspaces pass through explicit PRAX `stepRef.artifactRef` bindings. There is no PVC, host mount, sudo/tmpfs setup or Docker-in-Docker requirement. Generation builds a private temporary workspace and publishes the declared artifact directory **only after** input manifest, portability and credential checks. Failed generation leaves no declared output path to archive. The model task verifies native-input checksums before running the upstream binary, and verification checks those files again after execution.

Task environment bindings use the current canonical `secretRef: {name, key}` contract; the retired `userSecretRef` selector is rejected by the server. User scope belongs to managed-secret creation/access, not a different task environment field. The executed proof used an explicitly approved organisation-scoped binding in its selected development tenant, without altering the existing personal binding or embedding any value.

PRAX applies infrastructure retries even when `retryStrategy` is omitted. The candidate explicitly requests on-demand scheduling and one retry restricted to `OnTransientError`, bounded backoff. This is not exactly-once execution, nor permission to retry an unknown submission outcome. Deterministic model/code failures and OOM are not intended to be retried by that policy. The successful staged proof used one attempt per phase; fault injection and retry behavior were not exercised.

## Initial configuration admission

The initial adapter accepts only the logical values of the preserved `.tech` Datamesh reference in `reference/example-swan.yml`, whose exact source SHA256 is `998436b3164ccc8f7e971faea57ff8365d58435653db299a7cb8a90e67980a42`. Comments/formatting may differ but are retained in the exact handoff. This is **not** a general user-YAML/template execution service. No local catalog/input assets are packaged.

Input is the configuration-only plugin's `rompy-configuration-handoff-only` JSON record. The adapter rechecks exact source/model hashes, source↔JSON semantics, supported reference values and validation-document correlation. Generation independently checks Python/package/source identities against the recorded runtime and constructs the real narrowed public `ModelRun`/`SwanConfig` before calling public `generate()` with synchronous scheduling. No upstream templates or generated `INPUT` are patched.

The handoff is not an authorization signature or PRAX receipt. PRAX must authorize the submitting actor and bind the reviewed release; source/runtime checks do not fix the unresolved reviewed-release admission race. Datasource IDs remain mutable; native file hashes record what was actually generated in each successful attempt.

The model phase is a native SWAN invocation: `/usr/local/bin/swan-serial` for the baseline, or the proposed `/usr/bin/mpirun -np 4 /usr/local/bin/swan.exe`. The public image already supplies both binaries and selects MPI under `mpirun`; this repository does not rebuild or modify SWAN. Serial and MPI are separate acceptance gates.

Verification requires `PRINT`, the configured table/restart files and both NetCDF outputs; it reopens and actually loads the datasets. Exit zero alone is insufficient. Output completeness/readability is not calibration, scientific suitability or proof of arbitrary configurations.

## Build and rendering

The Python image uses pinned public Python3.12.13 and uv image digests, hash-locked dependencies and exact public rompy/rompy-swan Git commits. Its filesystem is owned by UID10001 for normal generation/report work. That is not proof of PRAX artifact extraction ownership or a pod-level security context; those must be verified in the target environment. The unchanged SWAN image has its own upstream user/runtime defaults. No privileged pod settings are added. Checked artifact modes are explicitly normalized as described below.

`.dockerignore` is an allowlist for source, locks and reference metadata. Credentials, `.runtime`, local data and tests are not build inputs. A local build does not fetch model data or run a model:

```sh
docker build --platform linux/amd64 -f runtime/Dockerfile \
  -t rompy-prax-runtime:staged-candidate .
```

PRAX performed the staged builds from the approved reachable repository and exact commits—no separate manual registry-push workflow was required. The approved public source destination is `oceanum/rompy-prax-runtime`, under Apache 2.0. Upstream notices are retained in `third-party/`; this does not relicense the unchanged SWAN image or other dependencies. Reachability and the exact source commit must be verified before a PRAX build.

Render a new inactive candidate after supplying real reviewed bindings (do not invent a source repository or secret):

```sh
PYTHONPATH=src python -m rompy_prax_runtime.specification \
  --owner YOUR_GITHUB_OWNER --repository YOUR_RUNTIME_REPOSITORY \
  --commit EXACT_40_CHARACTER_COMMIT --credential-secret EXISTING_USER_SECRET \
  --mode serial --output inactive-prax.yml
```

Both project and stage are inactive. No triggers are created. This command does not call PRAX, build an image, deploy or submit a run. `--mode mpi` describes a separate four-process, single-node proposal, not a proven execution mode. For a new target, source access, credential binding, artifact retention and workspace permissions remain prerequisites; the serial acceptance below covers only the explicitly approved development target.

The pipeline's `handoff-json` parameter must be a **serialized JSON string**, not a nested object that the current PRAX API would stringify as a Python representation. The published pipeline CLI accepts a JSON `--parameters` object; do not invent `@file` expansion support. Configuration content transferred as parameters/artifacts is subject to PRAX visibility/retention. Credentials never belong in the handoff or workflow parameters.

Use the CRD-compatible parameter name `handoff-json` throughout task inputs, pipeline declarations and argument bindings; underscores are rejected by the live Kubernetes CRD even if server validation accepts them. The generation container still receives `ROMPY_HANDOFF_JSON`. Pin the concrete target with canonical `orgRef`; do not rely on the CLI login's active organisation for inventory or deployment targeting.

The image-build budget is 1 CPU / 4Gi memory, separately from task runtime limits. A real PRAX/Kaniko build installed the locked packages successfully but was OOM-killed during full-filesystem snapshotting at 2Gi; the 4Gi build succeeded. This is build evidence, not a staged model-run claim.

The model wrapper's credential guard emits only a fixed diagnostic to stdout and exits 64; it never prints a credential value. Avoiding a nonessential `>&2` redirection keeps this definition in the JSON-encoding subset shared by the currently deployed PRAX controllers. A live check found differing HTML escaping in their fingerprint calculations. No stored fingerprint, readiness flag or integrity check is overridden; a general canonicalization repair belongs in PRAX, separately from this proof.

The sequential artifact graph uses `dag` with explicit `generate → swan → verify` dependencies. The deployed PRAX translator renders `stepRef.artifactRef` using Argo's `tasks.*` context, which belongs to DAGs; a steps-form workflow was rejected by Argo before any pod ran. Do not confuse successful PRAX admission with native Argo spec acceptance.

After all generation and credential checks pass, the private preparing workspace normalizes artifact files to `0644` (`0755` for executable files) and directories to `0755` before atomic publication. This permits the non-root verifier to read archives restored under another UID. The first real staged serial run produced reference-matching outputs, but its remote verification failed on root-owned `0600` `generate_result.json`; host verification passed. The permission repair does not change file bytes, source hashes or scientific inputs, does not modify the retained cloud artifact, and does not retroactively make that failed workflow successful.

## Staged serial acceptance

A real development workflow completed **generate → SWAN → verify**, with all three phases `Succeeded`. The corrected generation image was built from `2111d3e8fdb4ba6815ef5e781b7ac532caaa4e90`; the existing verifier image and unchanged upstream SWAN digest were retained.

Independent downloads confirmed that every file hash in the remote verification report matched the retained workspace. Both NetCDF datasets fully loaded and matched the historical reference byte-for-byte. Required PRINT/table/restart outputs were present, native inputs were unchanged during execution, the exact reviewed handoff matched, and known credential patterns were absent. Generated `INPUT` headers differ between runs by timestamp/hostname; they were not patched. No artifact file remained unreadable to UID10001.

Attempt accounting: three workflow submissions—one rejected by native Argo before any pod, one actual SWAN run followed by the permission failure, and one explicitly approved final run with remote verification successful. **Two actual SWAN runs total.** Failed workflows and original retained artifacts were preserved. The final successful workflow's pods were garbage-collected; final image/environment wiring evidence is the frozen accepted template and immutable build resolution, not retained live pod image IDs. Actual pod credential isolation was inspected on the earlier failed workflow, whose environment wiring was unchanged.

This is fixed-reference serial execution/output acceptance, not scientific calibration, arbitrary-configuration support, MPI acceptance or permission for further runs. Detailed per-run receipts remain private. `reference/manifest.json` and `verification.json` retain their historical preparatory provenance rather than being rewritten as execution receipts.

## Local verification

The local gate passes **35 tests** and Ruff. Tests use mocked generation/model outputs; no actual generation or model execution occurs. `examples/inactive-serial.fixture.yml` and `examples/inactive-mpi.fixture.yml` are offline review fixtures with explicitly synthetic source/commit/secret names, not deployable targets.

The Python image built locally and accepted the actual configuration-only CLI handoff in a network-disabled container using real pinned public Pydantic models. Its reviewed Python/package/source identities matched. The sandbox retained a read-only root, UID10001, bounded CPU/memory/PIDs and a 64MiB container-only `/tmp`. An initial fully read-only attempt failed because Cartopy needs temporary storage during import; no model code or validation guard was weakened. Reproduce the pure check with `sh scripts/image-preflight.sh /path/to/private-handoff.json` after building locally.

The unchanged pinned SWAN image was pulled and its serial/MPI binaries, selector and launcher were checked for presence/executability, without launching the model. `verification.json` records nonsecret local image/preflight facts; the local image ID is **not** a published/pullable runner release. The fresh public PRAX schema still advertises only `stage_ref`/`parameters` for `PipelineRunRequest`, not a reviewed-release/idempotency field.

Initial read-only credential discovery preceded the explicitly approved binding and staged serial acceptance above. Those later operations do not establish MPI acceptance or authorize new credentials, tenants or runs.

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

Use the published `oceanum-prax-cli` for actual PRAX operations; don't add lifecycle wrappers to the ROMPY plugin. The serial proof passed concrete server validation, immutable build/release readiness, native workflow lint, artifact publication and remote output verification. Atomic client-reviewed-release enforcement, unknown-submission reconciliation and authoritative console identity remain unresolved frontend handoff gates; frontend submission stays disabled.

The 64MiB generation-tree threshold is a post-generation publication check, **not** a hard download/filesystem quota. Pod CPU/memory/timeout and ephemeral-storage behavior must be reviewed at deployment. The generation adapter is a trusted fixed-case tool, not a hostile-code sandbox.

Preparing or rendering another candidate does not authorize registry publication, PRAX writes, data extraction or model execution. The staged serial acceptance above and historical combined-image smoke are separate evidence. No MPI execution or further serial attempt is approved.
