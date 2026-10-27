# Image Moderation API

Standalone Python 3.12 / FastAPI service returning image analysis from NudeNet,
Freepik NSFW Image Detector, and optional Project Arachnid Shield. CPU only; no
application-specific policies, database, or filesystem scan endpoint. URL scanning
accepts public HTTPS images with optional exact hostname restrictions.
Results are predictions and known-content matches, not permission or legality decisions.

## Run with Docker

```sh
cp .env.example .env
# Set API_KEY if authentication is wanted; leave Shield credentials blank to disable it.
docker compose build
docker compose up -d
curl http://localhost:8080/health
curl http://localhost:8080/ready
```

Compose publishes **127.0.0.1:8080 only**, uses one worker, a non-root UID 10001,
a read-only root filesystem, dropped capabilities, a 4 GiB memory limit and two CPUs.
The initial build downloads approximately hundreds of MB of model/dependency data;
allow several GB of disk space and an internet connection. Model initialization may
take a minute on a cold CPU. Docker's health check measures liveness; use `/ready`
for a load balancer's readiness check. `docker compose down` stops the service and
preserves the named model-cache volume. No GPU or host Python installation is required.

For a private production network, remove `ports` from compose.yaml and attach this
service and its caller to the same private Docker network. Call
`http://moderation-api:8080` inside that network. Set API_KEY as another layer of
protection, terminate TLS at a trusted proxy, enforce request deadlines and rate
limits there, and restrict outbound access to Shield only if enabled. Do not expose
an unauthenticated instance publicly. Do not log multipart bodies, Authorization,
returned hashes, or filenames at the proxy. Disable docs with ENABLE_DOCS=false if needed.

## Configuration

Pydantic Settings reads environment variables and optional `.env`. Invalid typed
configuration fails startup with a sanitized message. Empty/whitespace-only secrets
are unset; otherwise secret values are used exactly, including any surrounding spaces.
No diagnostic endpoint returns configured values.

| Variable | Default | Meaning |
| --- | --- | --- |
| API_KEY | unset | Optional Bearer key on **all five POST scanning endpoints** |
| ARACHNID_API_USERNAME | unset | Shield Basic-auth username |
| ARACHNID_API_PASSWORD | unset | Shield Basic-auth password |
| HOST | 0.0.0.0 | Container listening address; use 127.0.0.1 for native local use |
| PORT | 8080 | Native listening port / Compose host port (container stays 8080) |
| LOG_LEVEL | INFO | DEBUG, INFO, WARNING, ERROR, CRITICAL; controlled JSON application events |
| ENABLE_NUDENET | true | Load packaged 320n detector |
| ENABLE_NSFW | true | Load Freepik detector |
| MAX_IMAGE_SIZE_MB | 20 | MiB of image bytes, 1–100 |
| MAX_IMAGE_PIXELS | 40000000 | Maximum decoded width × height |
| MAX_IMAGE_DIMENSION | 8192 | Maximum side length; also bounds NudeNet square-padding memory |
| MAX_CONCURRENT_SCANS | 1 | Maximum admitted uploads/scans, 1–4; busy requests receive 503 |
| UPLOAD_TIMEOUT_SECONDS | 30 | Total body-read deadline |
| SCAN_TIMEOUT_SECONDS | 120 | Response deadline for validation and scanning |
| ARACHNID_TIMEOUT_SECONDS | 15 | Shield HTTP timeout, with 5 second connect timeout |
| NUDENET_CONFIDENCE_THRESHOLD | 0 | Additional output filter 0–1; 0 preserves all library detections |
| NSFW_DTYPE | float32 | Portable CPU precision; bfloat16 is an opt-in matching the reference dtype |
| MODEL_CACHE | model-cache | Native cache path; container uses /app/model-cache |
| ENABLE_DOCS | true | Expose /docs and /openapi.json |
| ALLOWED_IMAGE_HOSTS | unset | Comma-separated exact image hostnames; blank permits any public HTTPS host |
| URL_DOWNLOAD_TIMEOUT_SECONDS | 30 | Absolute download deadline, 0–120 seconds; 5 second connect/read-idle limit |

Without API_KEY startup logs warn that authentication is disabled and the service
must stay private. With it, missing/invalid Bearer credentials get 401 using a
constant-time comparison. Query-string keys are never accepted. Health, readiness,
engine availability and documentation remain unauthenticated.

Shield is enabled only when **both** credentials are nonblank. Neither credential
means disabled. A single credential logs a warning and disables Shield while local
engines continue. Disabled Shield creates no HTTP client and makes no network calls.
No credentials are bundled; `.env` is ignored by Git and excluded from Docker builds.

## API contract

The application's typed schemas and route metadata generate `/openapi.json`.
`docs/openapi.json` is a checked-in snapshot; regenerate after interface changes:

```sh
.venv/bin/python -c 'import json; from app.main import create_app; print(json.dumps(create_app().openapi(), indent=2))' > docs/openapi.json
```

| Method / endpoint | Behaviour |
| --- | --- |
| GET /health | `{"status":"ok"}`; process liveness |
| GET /ready | Engine readiness; 503 if an enabled engine failed initialization |
| GET /v1/engines | Each engine's enabled and ready booleans |
| POST /v1/scan | All enabled engines, or comma-separated multipart `engines` selection |
| POST /v1/scan/url | Download and scan a public HTTPS image; JSON `url` and optional `engines` list |
| POST /v1/scan/nudenet | NudeNet only |
| POST /v1/scan/nsfw | Freepik only |
| POST /v1/scan/arachnid | Shield only; 422 if disabled |

On upload routes, send one multipart field named `file`. JPEG, PNG and WebP are decoded and verified
regardless of filename/MIME claims. Animated/multi-frame images are rejected.
The optional multipart `engines` string is supported only by `/v1/scan`; empty, unknown or disabled
explicit selections return 422. All-disabled configuration is ready (nothing is
loading), but scanning returns 503 because no engines are available.

```sh
# No API_KEY configured:
curl -sS http://localhost:8080/v1/scan -F 'file=@/absolute/path/image.jpg'
# API_KEY configured (avoid placing a real key in shell history):
curl -sS http://localhost:8080/v1/scan \
  -H "Authorization: Bearer $API_KEY" \
  -F 'file=@/absolute/path/image.jpg' -F 'engines=nudenet,nsfw'
curl -sS http://localhost:8080/v1/scan/nudenet \
  -H "Authorization: Bearer $API_KEY" -F 'file=@/absolute/path/image.webp'
```

Responses include a UUID `scan_id`, basename `filename` (never logged), overall
`status`, total `processing_time_ms`, and all three engine result entries. Executed
engines include `inference_time_ms`. NudeNet returns unchanged labels, scores and
`[x,y,width,height]` boxes. Its default built-in confidence/NMS thresholds remain
unchanged; the optional output filter cannot recover detections the library removed.

**Freepik output requires care.** The actual 0.1.2 package exposes a boolean
`is_nsfw` and a **list** of score dictionaries, not a categorical prediction.
`classification` and `is_nsfw` both contain that library boolean (default medium
threshold 0.5); this is a model output, not a moderation decision. `probabilities`
preserves the package's list structure and original labels/scores. `high` is its
class probability; `medium` sums medium+high; `low` sums low+medium+high; `neutral`
is separate. These values do **not** sum to one. The API does not invent a most
likely label by taking the maximum of cumulative scores. EXIF transpose and RGB
conversion follow the reference script. CPU defaults to float32 because bfloat16 inference was impractically slow on the
validated ARM64 host. Opt-in bfloat16 uses CPU autocast. Precision can change scores;
the library model, transforms and scoring algorithm remain unchanged.

Shield returns the original `classification`, optional `match_type`, `pdq_quality`
and `raw` JSON response. It computes the PDQ hash locally using OpenCV BGR→RGB,
`pdqhash.compute`, NumPy `packbits` (big-endian bit order), 32-byte Base64, and sends
`{"hashes":["..."]}` to the fixed HTTPS `/v1/pdq` endpoint with Basic authentication.
It never sends the uploaded image. `no-known-match` means no known database match,
**not proof of safety**. `csam`, `harmful-abusive-material`, `test`, and unknown future
strings are returned verbatim without a legal/policy conclusion. There are no automatic retries.

### Signed image URLs

```sh
curl -sS http://localhost:8080/v1/scan/url \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $API_KEY" \
  --data '{"url":"https://images.example.com/photo.png?token=SHORT_LIVED_TOKEN"}'
```

Omit the Authorization header if API_KEY is unset. Omit `engines` to run every
configured engine. To select engines, use a JSON list, for example
`{"url":"https://images.example.com/photo.png?token=TOKEN","engines":["nudenet","nsfw"]}`.
On the existing upload endpoint, `engines` remains an optional comma-separated
multipart string. Omit it entirely rather than sending an empty value. Selection
avoids unwanted computation; it does not balance requests across servers.

For S3-compatible storage behind your image Worker, allowlist the Worker's exact
hostname, rather than a provider's shared domain:

```env
ALLOWED_IMAGE_HOSTS=images.example.com,media.example.com
URL_DOWNLOAD_TIMEOUT_SECONDS=30
```

The list is case-insensitive, comma-separated and exact: no wildcards, scheme,
port, path, implicit subdomains or IP literals in configuration. Internationalized
DNS names are normalized to ASCII IDNA. Blank/unset means **any public HTTPS host**;
it never permits private-network access. Restart/recreate the service after changing
configuration. Compose passes both settings through to the container.

Only HTTPS on port 443 is accepted. URL credentials, fragments, whitespace/control
characters, backslashes and redirects are rejected. Every resolved IPv4/IPv6
address must be public; loopback, private, link-local, metadata/CGNAT, multicast,
site-local and transition-address destinations are blocked. The TCP connector pins
a checked numeric IP and keeps the original hostname for certificate verification
and TLS SNI, preventing a second DNS lookup from rebinding the request. Connections
are not pooled between downloads. Proxy environment variables are ignored; no API
Bearer key or cookies are forwarded, and received cookies are discarded.

The signed query string is preserved. Neither the URL nor its token is logged,
echoed in an error, or returned as a filename (`filename` is null for URL scans).
The response format is otherwise the same as uploads; total processing time
includes download time. Downloads remain in memory and are released after work
finishes; source objects in storage are never deleted. Keep tokens valid long
enough to download the image; local inference can continue after token expiry.

JSON requests are capped at 16 KiB and URLs at 8192 characters. Streamed download
size uses MAX_IMAGE_SIZE_MB even when Content-Length is missing or false. All
existing format, decoded-pixel and dimension checks also apply. HTTP-level
Content-Encoding compression is rejected to bound decompression risk (normal PNG,
JPEG and WebP image compression remains supported). Download deadlines apply at
each TCP/TLS/header/body operation and include a 5 second idle-read limit. DNS resolution uses dnspython with a bounded lifetime within the combined
5 second DNS/connect budget. Every A/AAAA answer is checked before connection,
and unreachable public addresses fall back within that same budget. Overall scan
timeout still bounds the response and retains capacity until native work returns.

Errors are sanitized: 422 invalid/disallowed/non-public URL; 413 body/image limit;
415 unsupported image/HTTP content encoding; 502 remote error, token expiry, redirect,
DNS/connect/TLS failure; 504 download or overall scan timeout. No automatic retries
or signed-URL refresh are performed. Restrict outbound traffic at the network layer
as another deployment boundary. Use an allowlist for your commercial deployment.

Implementation uses the documented [HTTPX custom transport](https://www.python-httpx.org/advanced/transports/)
and [HTTPCore network backend](https://www.encode.io/httpcore/network-backends/)
interfaces, with pinned HTTPX/HTTPCore versions and dnspython 2.9.0. DNS settings
come from the container resolver configuration; OS hosts-file overrides and DNS
search suffixes are not used for image downloads.

### Status and errors

| Status | Meaning |
| --- | --- |
| completed | Every requested engine returned a result; engine-level: inference completed |
| partial | At least one requested engine succeeded and at least one failed |
| failed | Every requested engine failed; engine-level: no usable result |
| disabled | Engine configuration disabled it; never executed |
| not_requested | Enabled engine was excluded by explicit selection |

Completed and partial scans return 200. All-engine failure returns 502 with a scan
response and per-engine errors. URL download failures also return 502, using the
standard error envelope. Other errors use
`{"error":{"code":"...","message":"..."}}`:
400 malformed multipart/image; 401 bad/missing token; 408 upload timeout; 413 byte,
pixel or dimension limit; 415 unsupported/animated image; 422 invalid selection or
missing file; 503 busy/no enabled engines; 504 scan deadline. Busy responses include
`Retry-After: 1`. Shield 429/timeout appears as a sanitized per-engine failure, so
other engines can succeed. No upstream error body, private path or exception trace
is returned to the caller. Readiness does not make billable/external Shield calls;
Shield `ready` means its client is configured, not that credentials were verified.

## Models, memory and shutdown

Models initialize once in FastAPI lifespan and are reused by a dedicated, serial
CPU executor. Enabling more admitted scans permits a bounded waiting queue; it
does not parallelize model access. Admission and authentication happen before
body parsing. Multipart payloads are capped at the file limit plus 64 KiB overhead,
kept in memory, and closed promptly. Images are never written to persistent storage.
Only the model cache persists. URL downloads share this same admission limit and
executor; a slow download cannot bypass upload capacity limits. Logs contain controlled events, not images,
filenames, hashes, credentials or exception bodies.

A native inference thread cannot safely be killed. A response timeout keeps its
admission slot occupied until real work finishes; disconnects do the same. Shutdown
waits for in-flight work before releasing models/HTTP clients. A stuck native library
may require an orchestrator restart after the 10 minute grace period. Proxy rate
limits and container resource limits are still required for hostile traffic.

NudeNet's 320n ONNX weights ship inside its package. Freepik's weights download
**during build**, pinned to revision `15b85477e4fd2000db76ae9aae0f89a72f95e2e3`.
The image seeds a fresh named volume offline from `/opt/models/freepik`; runtime
loads `/app/model-cache/freepik` directly, with Hugging Face offline mode. Restarts
reuse this cache. Remove/recreate the model-cache volume after changing the model
revision; preserve caches only while they match the deployed image. Build still
includes both models even when an engine is disabled at runtime.

Start with 4 GiB container memory and two CPUs; this is a configured budget, not a
claim about a measured peak. Decode/padding limits bound image growth. Benchmark
representative images on target hardware before setting throughput expectations.
Docker is tested on linux/arm64 in this workspace; AMD64 must be built/tested on its
own target. PDQ is compiled from source, so the build stage includes a C++ toolchain.
The lock selects CPU-only Linux torch wheels; native macOS has different torch
wheel names and must use `requirements.in` rather than the Linux runtime lock.

## Native setup and tests

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.in -r requirements-dev.txt
MODEL_CACHE=model-cache .venv/bin/python scripts/download_models.py
HOST=127.0.0.1 .venv/bin/python -m app
# In another terminal:
.venv/bin/python -m pytest -q
```

Unit tests inject model doubles and mock Shield HTTP transport; they do not require
weights, real credentials or external image transmission. Install the lightweight
API/settings/Pillow/dnspython dependencies plus requirements-dev.txt to run just those tests.
Real adapters are exercised separately in Docker with a generated harmless image.
Optional integration tests:

```sh
RUN_MODEL_INTEGRATION=1 .venv/bin/python -m pytest tests/test_integration.py -q
# Explicitly opt into sending the hash of your chosen local image to Shield:
RUN_ARACHNID_INTEGRATION=1 ARACHNID_TEST_IMAGE=/absolute/path/owned-image.png \
  .venv/bin/python -m pytest tests/test_integration.py::test_real_shield -q
```

The Shield integration test requires both real credentials and the explicit path;
it never selects bundled images. Keep local-only tests independent of credentials.
All runtime transitive versions are pinned in requirements.txt, generated from
requirements.in with uv for Python 3.12 Linux ARM64. Re-resolve/retest when upgrading,
and verify AMD64 compatibility before shipping that platform.

## Troubleshooting

- `/ready` returns 503: inspect the sanitized initialization event. Check cache
  completeness/permissions, available memory, model revision and CPU dependencies.
  A failed local model does not remove `/health` or results from other engines.
- NSFW disabled/failed: verify model-cache/freepik/config.json and model.safetensors,
  run setup for native use, or recreate a stale Docker cache volume. Keep the default
  NSFW_DTYPE=float32 on CPUs without fast bfloat16 support; retest scores after changing precision.
- 503 busy / 504: reduce image dimensions, increase a justified deadline, or scale
  independent containers. Do not increase Uvicorn workers casually: each loads models.
- 401: use Bearer in Authorization; `.env` changes require container recreation.
- Shield disabled: both credentials must be nonblank. 429: obey caller backoff and
  the Shield account's quota. Shield errors intentionally omit the upstream body.
- Build cannot fetch weights: check Hugging Face access/CA trust during build;
  runtime is deliberately offline for model loading.

## Reference behaviour and licences

The three original test scripts are primary references and are retained unchanged.
Sources: [NudeNet](https://github.com/notAI-tech/NudeNet),
[nsfw-image-detector](https://pypi.org/project/nsfw-image-detector/),
[Freepik model card](https://huggingface.co/Freepik/nsfw_image_detector), and
[Shield documentation](https://shield.projectarachnid.com/docs/), whose schema is
available at [openapi.json](https://shield.projectarachnid.com/openapi.json).
Orbit discovery returned no relevant Shield contract; the working script and
provider's own schema supply the integration contract.

Selected versions: NudeNet 3.4.2, nsfw-image-detector 0.1.2, PDQ 0.2.8,
FastAPI 0.162.0, Uvicorn 0.54.0, Pydantic 2.14.1 / Settings 2.16.1,
HTTPX 0.28.1, Pillow 13.0.0, ONNX Runtime 1.31.1, OpenCV 5.0.0.93,
NumPy 2.5.4, torch 2.14.1+cpu, torchvision 0.29.1+cpu, timm 1.0.30,
Transformers 4.57.6. Transformers stays on its compatible 4.x line because the
reference package calls that API; latest major is not assumed compatible.

**NudeNet licensing discrepancy:** its wheel metadata says MIT, but both bundled
LICENSE files contain AGPL-3.0 text. The exact wheel's text is retained in
`docs/licenses/NudeNet-3.4.2-LICENSE.txt`. Do not assume unrestricted commercial
licensing from metadata; resolve applicable code/weight terms with the upstream
maintainer before commercial distribution/deployment. No commercial-use clearance
is asserted here. The Freepik Python package declares Apache-2.0 and its model card
MIT; retain their notices and the model/base-model terms. PDQ is MIT; FastAPI,
Pydantic, HTTPX, ONNX Runtime and timm use permissive licences; torch/torchvision,
NumPy and Uvicorn have BSD-family terms; Pillow uses HPND and OpenCV Apache-2.0.
Redistributors must retain applicable notices and verify all transitive/native
licences in their final image. Shield access is subject to its account/service
terms and quota. This project does not grant rights to third-party software/models
or choose a licence for your newly authored application code on your behalf.

## Recorded validation

See [validation report](docs/validation.md) for measured results and remaining limits,
and [actual JSON response](docs/example-response.json) for a generated geometric image.
To repeat local model parity with the running, unauthenticated Compose service:

```sh
docker compose exec -T moderation-api python - < scripts/verify_local_models.py
.venv/bin/python scripts/verify_http.py
```

The HTTP script uses a temporary localhost:8081 container for authentication checks
and removes it afterwards. Keep Shield credentials absent for these local checks.
