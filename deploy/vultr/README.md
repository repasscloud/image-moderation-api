# Independent Vultr processor installation and operations

Implementation for Swoovr tracking issue [#294](https://github.com/repasscloud/wanderconnect/issues/294).
This service is released independently of Swoovr web/API. The owner provisions two
VMs, VPC networking and an HTTPS load balancer; this repository does not provision
resources or claim provider acceptance. Install the SAME pinned image on each VM.
Each VM has its own warm CPU model process and its own local ClamAV sidecar.

## Files to prepare

- `compose.yaml`: per-VM stack, unmodified pinned ClamAV and reviewed processor image.
- `compose.env.example`: copy to operator-private `compose.env`; deployment data only.
- `processor.env.example`: copy to private `processor.env`, mode 0600; runtime secrets.
- `build.sh IMAGE:TAG`: explicit local image build, no publish/deploy.
- `stack.sh /absolute/compose.env validate|up|status|drain|resume|stop`: explicit local operator action.
- `validate.py`: rejects missing/dangerous deployment settings, bad digest and secret-file permissions.

Never shell-source an environment file. Compose reads `compose.env` as configuration;
`processor.env` uses Compose raw env-file handling so literal `$` in secrets is
not interpolated. Use a Docker Compose version supporting `env_file.format: raw`
and verify with `docker compose version` and `config --quiet`. Do not print the
resolved Compose config; it may expose environment values. Examples have no secrets.

## Use the published multi-platform image

The main branch now has the owner's GitHub Actions release workflow. It builds native
linux/amd64 and linux/arm64 images and publishes their combined index to Docker Hub
as `repasscloud/image-moderation-api`. A VM does not need to build the image itself.
Take the immutable index digest from the successful workflow's job summary and set:

```text
PROCESSOR_IMAGE=docker.io/repasscloud/image-moderation-api@sha256:<published-index-digest>
```

For a private repository, authenticate Docker on each VM using the operator's registry
pull identity (`docker login docker.io` interactively, or an approved secret-input
mechanism). Never put the registry PAT in source, container image layers or command
arguments. Then use the validated per-VM `stack.sh ... up` procedure below.

The PNG transparency correction uses transform recipe `webp-2048-320-v2`. Previously
published images do not acquire this fix automatically: merge its follow-up PR and
run the existing version-tag/manual release workflow for the corrected source, then
roll out the new digest one VM at a time. Branch pushes alone do not trigger this
workflow. The publishing workflow is preserved unchanged by this fix.

## Build and release (operator, explicit steps)

1. Review source, dependencies and model licences (existing NudeNet licence discrepancy
   remains a hosted-use gate). Run Python tests and contract checks.
2. Run `deploy/vultr/build.sh YOUR_REGISTRY/swoovr-image-processor:REVIEWED_RELEASE`.
   Dockerfile downloads Freepik revision pinned by `scripts/download_models.py`
   during build, records model checksums, then runs offline. Startup verifies/refreshes the model volume from the build snapshot so a stale volume cannot override a new model release. NudeNet packaged 320n weights are dependency-pinned.
   Build context excludes `.env` files; never pass secrets as build arguments.
3. Inspect the resulting image, generate/review SBOM and image vulnerabilities, then
   explicitly publish to your chosen private registry. Publication is an operator step;
   build scripts never push. Record the registry digest, platform, model revisions,
   package lock and code revision. Configure `PROCESSOR_IMAGE=...@sha256:...`.
4. Confirm the VM CPU architecture matches the built image. A local ARM64 test does
   not prove AMD64 runtime compatibility; build/test each intended platform.

## First installation on each VM

1. Provide Docker Engine/Compose, restricted operator SSH, trusted time synchronisation,
   a private/VPC address and LB firewall rules. Scanner TCP 3310 is NEVER published.
   Processor 8080 is bound to the specific private interface, accessible only by LB
   and authorised local probes. Terminate HTTPS at the LB with a valid certificate;
   verify the private backend network and decide TLS-to-backend protection.
2. Install this repo's deployment files in `/opt/swoovr-image/deploy` or another chosen
   read-only release directory. Create `/opt/swoovr-image/private` (0700) and
   `/opt/swoovr-image/control` (0755, containing only a nonsecret drain marker). The container bind mount of control is read-only. UID10001 must be able to traverse/read this directory; keep credentials in the separate 0700 private directory. Drain markers must be readable (0644).
3. Copy/fill `compose.env.example` as `/opt/swoovr-image/private/compose.env` and
   `processor.env.example` as `/opt/swoovr-image/private/processor.env` (0600).
   Set the real private VM address, registry digest, absolute file/control paths.
4. Supply a random `API_KEY` of at least 32 characters as the Worker-to-processor Bearer credential. Supply
   `ARACHNID_API_USERNAME` and `ARACHNID_API_PASSWORD` for Shield Basic authentication.
   A generic API key does not replace those two Shield values. Never send Shield
   credentials to Cloudflare Workers, Swoovr clients or PostgreSQL configuration.
5. Validate: `deploy/vultr/stack.sh /opt/swoovr-image/private/compose.env validate`.
6. Start: `deploy/vultr/stack.sh /opt/swoovr-image/private/compose.env up`.
   First signature database download/model volume seeding may take time. A 600-second
   wait limit is not proof of failed install; inspect sanitised local health/status.
7. Probe `/health` for liveness and `/ready` for model+scanner readiness. Point the LB
   to HTTP `/ready` on the private backend. Require READY before adding traffic.
8. Verify permitted harmless provider acceptance through the real account and both
   VM egress paths; configured Shield adapter readiness alone does not test credentials.
9. Give Cloudflare the HTTPS LB hostname and independent processor credential. Never
   expose this service as an unauthenticated public image API. API and Workers must
   be integrated and tested before any member upload cutover.

Default provisional per-host resources are processor 4 GiB/2 CPU plus ClamAV 4 GiB/2 CPU,
PLUS OS/headroom. These are bounds, not a measured sizing recommendation. Benchmark model
idle/peak, decoder pixel limits, definition reloads and one-VM maintenance capacity.
ClamAV reload avoids concurrent database copies. Freshclam needs outbound access;
processor needs outbound HTTPS to fixed Shield endpoint. Restrict host egress using
supported firewall controls; Docker network separation alone is not an egress firewall.
One model process and one admitted request are intentional to avoid duplicated weights.

## Processing protocol v1

`POST /v1/process`, `Authorization: Bearer <API_KEY>`, multipart/form-data exactly:

- `file`: original image bytes, max 10 MiB in deployment (compatibility image limits
  min200 on both sides, max8192 side, 40 million decoded pixels, JPEG/PNG/WebP, single frame).
- `job`: JSON string with **only** `protocolVersion:1`, `jobId` UUID, `imageId` UUID,
  lowercase hexadecimal `sourceSha256`, `purpose` (`profile`, `album`, `chat`).

The source SHA-256 must match the uploaded bytes. A mismatch returns 409. The service
has no database or R2 credentials, fetch URLs, client callbacks or policy settings.
The Worker owns replay/job authority and lifecycle claims. Auth applies before body
read and bounded concurrency admission; missing/malformed/disabled requirements fail
closed. Timeouts return 504 while work retains its slot until native execution ends.
A supervisor/operator may recycle a hung drained process; no forced native interruption
or unsafe release of its admission slot is claimed.

The 200 response is multipart/form-data with a text `manifest` JSON field and zero or
two binary file parts named `display` and `thumbnail`. Do not use base64 image fields.
Manifest includes job/image/input identity, `protocolVersion:1`, `recipeVersion`,
independent `results` for `malware`, `nudenet`, `nsfw`, `arachnid`, and `variants` entries
with `name`, `contentType`, `width`, `height`, `bytes`, `sha256`. Variants are WebP
quality85, display max2048 and thumbnail max320, no upscaling, metadata stripped,
orientation respected, transparent pixels flattened to white. Combined variant bytes
are limited to 20 MiB. Manifest/multipart framing adds small bounded overhead.

ClamAV scans ORIGINAL bytes before image decoding. Completed malware result classification
is `clean` or `infected`, with engine/signature/timestamp data. Failed/unsupported scanner
results do not become Clean. Required engine failures and any Shield classification
other than `no-known-match` produce no variants. `csam`/`harmful-abusive-material` are
specialist results; no thumbnails. `test`/unknown are also non-deliverable findings.
Valid ordinary nudity/NSFW review candidates CAN have private variants, letting a later
ordinary reviewer approve without another image transfer. The Worker decides whether
pass/review is appropriate; storing variants never grants delivery. Successful rejected-photo
appeal/reconsideration must still perform a fresh scan as Swoovr requires.

Shield receives a locally computed PDQ fingerprint, not the image. Raw Shield JSON
is stripped from this response. NSFW scores and nudity detections are predictions;
no model here establishes age, consent, ownership or legality. No known match cannot
prove absence of newly created abuse material.

## Readiness, drain and rolling update

Readiness checks all enabled local engines, local ClamAV VERSION/PING, signature age
and drain marker. The provisional `CLAMAV_MAX_SIGNATURE_AGE_HOURS=72` is an engineering
starting point pending Q173, not owner-approved. Missing required processing secrets
fails configuration rather than silently disabling Shield. A remote Shield outage
is reported by each attempt; readiness does not repeatedly call the provider.

1. On VM1, run `stack.sh ... drain`; `/ready` returns 503 and new process requests 503.
2. Wait for LB health routing to remove VM1 AND all admitted requests to finish or
   their bounded deadline/retry. A changed health state alone does not drain active work.
3. Stop VM1 stack with graceful timeout; patch/reboot and replace processor digest as
   explicitly planned. Do not upgrade both hosts simultaneously.
4. Remove drain marker using `resume` before `up`/health wait. Start and warm the new
   stack, test `/ready` and a safe permitted job; restore LB rotation.
5. Confirm one healthy host can carry traffic before repeating on VM2.

Rollback: drain the affected host, stop, restore the last compatible digest, remove marker,
start and verify. Do not revert Worker/protocol contracts to incompatible versions or
restore held/deleted images. Queue retries must use job fencing and durable API outcomes.
Signature updates happen independently inside each scanner; processor image upgrades are
not required for every definition refresh.

## Required external inputs and evidence

Owner supplies VM/VPC/LB address and region, architecture/resources, TLS/network rules,
registry/digest access, private credentials and operational monitoring contacts.
Cloudflare setup needs private R2 areas, Queues/DLQ, Worker bindings/secrets, API service
authority and accepted policy/protocol versions. Worker and API docs own exact setup.
No direct PostgreSQL credential or shared R2 admin credential belongs on these VMs.

Measure queue age, request capacity, model/scanner/Shield/encode timings, result/callback
failures, RAM/CPU/scratch, signature freshness and one-host recovery. No raw images,
private URLs, provider fingerprints or secrets in routine logs. Retention for original
uploads and appeals/holds belongs to Swoovr; local containers never retain uploaded files
on persistent model/signature volumes.

## Local verification commands

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check app tests scripts deploy/vultr/validate.py
docker build --tag swoovr-image-processor:local .
.venv/bin/python scripts/verify_processing_readiness.py --image swoovr-image-processor:local
.venv/bin/python scripts/verify_processing_stack.py --image swoovr-image-processor:local
```

To reproduce the cross-repository transport fixture without live providers:

```sh
.venv/bin/python scripts/export_processing_fixture.py --output /tmp/swoovr-processor-response
# In the companion Swoovr checkout's workers/images directory:
# PROCESSOR_RESPONSE_FIXTURE=/tmp/swoovr-processor-response npm test
```

The exporter refuses existing output files and uses explicit synthetic engines/image.
It exercises the actual FastAPI multipart response, not provider accuracy.

The readiness check uses synthetic engine readiness to test actual nonroot filesystem
access/drain behaviour. The stack check starts owned disposable Docker resources, uses
real clamd INSTREAM with a tiny synthetic EICAR definition database and real local model
inference on a green generated image. It injects synthetic signature provenance only in
the test because this tiny database has no production freshness metadata. This does not
prove production signature freshness, real Shield account acceptance, deployed networking,
model accuracy or AMD64 compatibility. The tests do not stop managed application services.
