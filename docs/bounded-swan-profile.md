# Bounded SWAN profile and workspace evidence contract

**Authority:** this file is the runtime-owned specification for any future bounded edited-profile implementation. It is design, not an enabled capability. The code at the current public `main` head remains fixed-reference-only; this document does not authorize extraction, an image build, deployment or a model submission. Edited-profile admission stays disabled until the integrated contract is implemented and accepted under workbench issue #5.

This contract bounds only a reviewed subset of the existing `reference/example-swan.yml`. It does not define a general rompy/SWAN configuration service. The authored reference, source format and omissions remain authoritative; the public Pydantic model is an independent validator, not a source-normalization mechanism.

## 1. Editable profile

Only these authored values may vary:

| Field | Contract |
| --- | --- |
| `period.start` | UTC instant on an exact whole-hour boundary, from 2023-01-01T00:00:00Z through 2023-01-02T00:00:00Z inclusive. |
| `period.duration` | Positive integral number of hours. The resulting end must not exceed 2023-01-02T00:00:00Z. |
| `period.interval` | Positive integral number of hours; it must divide the duration exactly. |
| Regular computational grid `config.cgrid.grid.{xp,yp,xlen,ylen,mx,my}` | Finite origin and lengths; positive `xlen`/`ylen`; `mx` a strict non-boolean integer in 1..14 and `my` a strict non-boolean integer in 1..24. |
| Output points `config.output.points.{xp,yp}` | Matched coordinate lists containing 1..3 finite, non-boolean numbers. Every point must lie within the accepted actual computational polygon. |

Time intervals are inclusive at both ends: `(duration / interval) + 1` instants, with no more than 25. A start/end/interval combination that is not exactly coherent is refused; there is no rounding, clipping, resampling, or silent period rewrite. The supported window is UTC 2023-01-01 through 2023-01-02, not a promise of input availability at every instant.

### Time representation

Policy interprets an authored naive datetime as UTC, consistent with the reference convention. A detached working model must express the selected instants as UTC-naive datetimes, so the pinned library's comparisons operate in one representation. Authored `Z`, `+00:00`, and naive-as-UTC spellings have the same effective UTC value for selection, but the exact original source bytes and authored JSON are retained independently and never rewritten. Explicit zero-offset values are converted only in the detached working model after source/policy checks. Any nonzero UTC offset is refused before data access. Unsupported edits must not be made acceptable by normalization.

### Immutable reference values

Every other authored field must remain semantically equal to the checked-in reference before Pydantic coercion/default insertion. This includes model kind and mode; coordinate system and rotation; spectrum, physics, numerics, convergence and source terms; active and inactive input definitions; datasource IDs, service, variables, mappings, filters and buffers; output selections, names and basenames; run ID, output directory, working/staging layout, commands and execution/resource settings. No extra fields or newly populated defaults are a way to pass the allowlist. In particular, the profile does not permit path/command/resource changes or changes to extraction semantics. Datamesh IDs are mutable references, not immutable snapshots of data.

The policy compares authored parsed values against the reference before coercion, default insertion or transformation. Browser and legacy handoff paths use the same policy. The exact submitted YAML/JSON bytes, comments and omitted defaults remain separately available; the runtime validates a deep-copied detached model. A validator must not mutate, replace or reserialize the retained authored source.

## 2. Actual-selection fence

Ideal mathematical corners and a requested cell count are not enough to bound selection. The pinned rompy/rompy-swan implementation generates coordinates with floating-point array operations; rounding can add actual rows/columns and move the generated extent outside the intended footprint.

Under the pure-validation fence, before credentials are read/required, connectors or coordinate queries are created, extraction begins, or any workspace is created:

1. Check authored policy and construct the public pinned Pydantic model from a detached copy.
2. Use the same pinned library's real grid-generation behavior to derive the actual grid; do not replace it with an idealized calculation. Refuse unless both coordinate arrays have the profile-derived cardinalities, all coordinates are finite, and coordinates form a nonempty, nondegenerate valid grid. No duplicated, nonmonotonic, or extra/missing coordinate is accepted.
3. Check every actual generated coordinate/footprint against the actual pinned reference computational polygon, not merely its axis-aligned envelope or ideal corners. Each configured point must be contained by that polygon. Polygon containment is inclusive with a maximum `1e-9` degree boundary tolerance; this tolerance applies only to geometric boundary comparisons, not to counts, finiteness, or policy values.
4. Derive each actual buffered source-query box using the pinned adapter's actual fixed buffer behavior. Require every finite, valid actual source box to be fully contained in its corresponding actual reference source-query box, componentwise, with at most `1e-9` degrees comparison tolerance. Missing, malformed, degenerate or non-finite boxes fail closed. Do not use ideal corners to infer the box and do not enlarge or rewrite user extents to make them pass.
5. Refuse on any actual/reference mismatch before credentials, connector/data access, workspace creation or publication. Errors are controlled, value-free policy reasons; private config values, source content, tokens and exception dumps do not go to logs.

The required rounding regression is the authored reference with `xlen=7.4, mx=2`: policy and Pydantic alone accept it, while the pinned generated grid is 25 by 4 rather than the requested 25 by 3. Its actual wind-query box is `[107.12804407819843, -37.2, 123.07296095788405, -19.956152513192407]`, exceeding the actual reference box `[107.12804407819843, -37.2, 119.48173037694868, -20.20727581867126]`. It must be refused before connector/workspace effects. Add other rounding-sensitive refusals and a valid interior non-reference grid regression. Do not patch upstream grid generation or silently alter the requested mesh/extent.

Coordinate metadata queries used by the fixed adapter remain adapter behavior and occur only after the pure guards pass. Bounded spatial/time selections and the existing 64 MiB generated-tree publication limit do **not** prove a pre-transfer byte bound or guarantee source availability. Do not claim otherwise or broaden extraction/resource policy here.

## 3. Validation order and compatibility

The authoritative sequence for an edited source is:

1. Bound and safely parse the existing browser-request or legacy handoff envelope; verify exact field sets, hashes, source-to-authored-JSON equality, and legacy metadata correlation.
2. Apply the versioned authored-value profile against the checked-in reference.
3. Build the detached, effective UTC-naive model and validate it with the public pinned Pydantic/rompy model under the existing I/O fence.
4. Validate actual pinned grid cardinality/coordinates, polygon containment and actual buffered source boxes as above.
5. Only then check credentials/adapter settings and permit connector/data access and workspace construction.
6. Generate native inputs without patching upstream templates or the generated SWAN control file; attest inputs/evidence and apply existing publication guards before publishing.

Every policy/Pydantic/actual-selection rejection precedes credentials/connectors/workspace. Keep controlled private-value-free failures. Do not weaken existing duplicate-key/YAML safety, envelope size/source correlation, secret exclusion, atomic publication, path/symlink, portability, output and credential guards.

The ordinary PRAX request envelope/API fields and existing CLI handoff remain unchanged. Browser worker-owned acceptance and legacy raw handoff bytes remain distinct and correlated. The browser's local checks remain advisory; authoritative acceptance is in the runtime worker. Do not add an API, required client field, browser Python/CLI requirement, separate service, retry, or client claim that an earlier readiness observation pins the subsequently admitted release. Existing native PRAX submission uncertainty behavior is outside this contract and must not be weakened.

## 4. Versioned workspace and provenance

A successful generation publishes one versioned evidence contract as part of the workspace. The producer is the runtime generation adapter; the existing SWAN task consumes only the published native workspace and checksum ledger; the runtime verifier is an independent consumer. The browser/CLI is not an evidence authority, and a user-supplied manifest or expected-output file is never trusted by itself.

The v1 workspace contract requires, at minimum:

- The untouched native staging tree, including `STAGING/INPUT` and every generated native source file needed by SWAN.
- `evidence/configuration-handoff.json`: accepted handoff/provenance with exact source hash and authored model-JSON hash. For the browser, retain the exact request separately at `evidence/configuration-request.json`; worker acceptance/provenance is created only after genuine worker Pydantic and policy acceptance. For legacy CLI, preserve the original handoff bytes and behavior; do not rewrite the submitted handoff.
- `evidence/generation-runtime.json`: actual installed runtime identity, selected profile identifier/version and policy/module identity needed to bind the acceptance.
- `evidence/native-inputs.json`: canonical manifest of the complete native-input set and its SHA-256 values, including mandatory `STAGING/INPUT` and required provenance/profile artifacts as defined by the v1 writer.
- Root `native-inputs.sha256`: the exact pre-run ledger consumed by the SWAN task, covering the same complete native set.
- A versioned generated profile/expectations record binding source identity, profile identity, derived hotfile/output names and expected dimensions. It is evidence, not an independent source of verifier authority.

The accepted provenance identity must correlate the exact request/source bytes and hash, authored JSON/hash, profile ID/version and policy identity, actual worker runtime facts, and generated input hashes. Where source IDs are mutable, record actual generated native-input hashes: provenance does not assert that a future fetch of the same datasource ID will return identical data. Do not put credentials or private values in evidence.

### Manifest and checksum rules

Both manifests are untrusted input at verification. Parse a strict versioned shape; reject unknown/duplicate keys, malformed/noncanonical relative paths, absolute paths, `..`, empty/dot components, symlinks, path escapes, duplicate entries, invalid SHA-256 syntax, missing mandatory files, and unlisted native files. Resolve paths under the fixed workspace root and verify the regular file actually exists. Do not accept an omitted row as proof of integrity.

The post-run `evidence/native-inputs.json` must cover exactly the same native-input path set and digest values as the original pre-run `native-inputs.sha256`; parse and compare the two ledgers independently. Every mandatory control/provenance/profile file must have a row in both. Rehash every listed file after SWAN and refuse missing, extra, changed, disagreeing, malformed or omitted entries. In particular, deleting the `INPUT` row from JSON must not conceal an `INPUT` mutation while the pre-run ledger retains its original digest. The SWAN task checks the pre-run ledger before invocation; the verifier independently checks that ledger against post-run manifest and bytes.

These checks detect accidental or unauthorized artifact mutation only within the integrity/trust assumptions of the trusted workflow. A checksum bundle whose producer and files can be jointly changed is **not** a cryptographic authorization signature and does not prove who authorized a run. PRAX remains responsible for actor authorization and actual admitted release; runtime evidence reports what the worker accepted and produced.

The 64 MiB workspace/publication cap is checked after generation and is not a pre-transfer or source-query limit. Preserve existing credential scans, fixed path/staging rules, symlink rejection, atomic publication, safe modes and output publication protections.

## 5. Output expectation derivation and verification

The verifier independently re-admits the accepted source under the same versioned profile/policy and derives expectations; it does not take expected values solely from a downloaded mutable expectations record or the old reference manifest.

- The final timestamped hotfile basename is derived from the accepted effective UTC period using the pinned runtime's actual naming semantics. It remains required; no arbitrary user basename and no optional-hotfile fallback.
- Grid/time/point dimension expectations are independently derived from the accepted source and profile's explicit sampling rules, checked against pinned confirmed behavior, and compared to loaded NetCDF dimensions. Do not infer a dimension from an authored label alone.
- `frequency=35` and `direction=36` remain protected accepted-reference counts because spectrum is immutable. They are not generic guessed SWAN counts; verify the actual relevant dataset dimensions against those protected counts.
- `PRINT`, required table, derived hotfile and both required NetCDF files remain mandatory, nonempty/readable outputs. A nonempty `Errfile` remains a refusal. Load datasets and report dimensions; completeness/readability is not calibration, scientific validity, or proof for untested configurations.
- Verify native-input stability before and after execution and independently hash published verification outputs. Keep fixed basenames, output selection, staging paths and existing resource/execution limits.

The workspace contract is versioned. A workspace created before this evidence contract is not silently migrated or accepted through a compatibility shim: use its original immutable verifier/contract. No current verifier behavior is changed by this documentation-only issue.

## 6. Ownership, sequencing and proof boundary

The runtime repository owns this profile, actual-selection adapter and output/evidence policy; policy and its implementation must be reviewed/released together. The workbench owns presentation and submits existing envelopes; it is not a parallel policy authority. The runtime accepts no external admission override. Main remains fixed-reference-only until issue #5 closes integrated contract acceptance. Issue #3 owns actual grid/UTC enforcement; issue #4 owns fail-closed evidence verification. This spec defines those prerequisites; it does not claim they are implemented here.

Applicable current compatibility/regression suites are `tests/test_browser_input.py`, `tests/test_stages.py`, `tests/test_image_preflight.py`, and `tests/test_specification.py`, run with the repository's existing pytest convention (`.venv/bin/python -m pytest -q`) and focused tests in those files. The future gates include both browser and legacy inputs, pure ordering/no connector effects, exact source preservation, UTC naive/Z/+00:00 and nonzero-offset refusal, actual-grid rounding, complete dual-ledger omission/mutation/disagreement, independent output expectation derivation, path/symlink and credential guards, and unchanged API/CLI envelopes. Do not add a toolchain or CI platform contract for this design issue.

No `.github`/other CI workflow or main branch-protection rule was detected in this repository at the time of this contract review. Required hosted checks/branch protection must not be claimed or treated as waived; reviewers must honor whatever checks are actually configured at PR/merge time. Offline source/library fixtures are not a newly built-image or live acceptance, and do not attest the full transitive binary stack. No real Datamesh extraction, SWAN process, workflow submission, build or deployment is part of this contract or this PR.

## 7. Later authority gates

- Issues #3 and #4 prepare the actual-selection and evidence consumers.
- Issue #5 gates activation only after integrated offline verification.
- Issue #7 is the separate rollout/deployment gate; issue #8 is the separate fresh live-case gate. This contract grants neither.
- Keep external admission fixed-reference-only until the issue #5 integration gate is met. No broader geography/time, source/physics, resource, API, execution or deployment change is included.
