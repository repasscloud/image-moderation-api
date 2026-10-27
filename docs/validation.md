# Validation — 27 October 2026

Target: Docker Desktop, Linux ARM64 CPU container on macOS; Python 3.12.
This directory originally contained only the three reference Bash scripts and was
not a Git repository. The reference scripts were inspected and retained unchanged.

## Confirmed

- `docker compose build` completed, including native PDQ compilation and download
  of the pinned Freepik model snapshot.
- `docker compose up -d` started the non-root service with localhost-only publishing.
- Both local engines initialized successfully; `/ready` returned 200 with NudeNet
  and NSFW `ready`, Shield `disabled`. `/health` returned 200; Docker reported healthy.
- 56 automated tests passed; 2 optional integration tests skipped by default.
  Tests use model doubles and HTTPX MockTransport; no Shield network calls occur.
- Ruff lint and formatting checks passed.
- A generated geometric PNG scanned successfully through the running HTTP API.
  The first float32 scan took 3995.045 ms, with NudeNet 271.275 ms and Freepik
  3702.299 ms. These are individual measurements, not throughput guarantees.
- A second scan's raw results matched direct package calls exactly at the same CPU
  precision: identical NudeNet class/score/box list and Freepik boolean/score list.
  See `scripts/verify_local_models.py`. A temporary synthetic fixture is used only
  for direct comparison with the reference script's file-path call and is deleted.
- Real HTTP scans of generated JPEG, PNG and WebP all returned completed results.
- A separate temporary container with NudeNet and API_KEY enabled returned 401
  for missing credentials, 401 for an incorrect token, and 200 with real NudeNet
  inference for the correct token. That temporary container was removed.
- Actual PDQ computation matched the script's OpenCV→RGB→compute→packbits→Base64
  sequence exactly; decoding the Base64 result yielded 32 bytes. No hash was sent
  externally during this check.
- AMD64 dependency resolution produced the same pinned dependency set. This is
  resolution evidence only, not an AMD64 build or inference test.
- The generated real scan response validates against the Pydantic ScanResponse.

## Operational findings and limits

- bfloat16 inference exceeded the 120 second response deadline on this ARM64 CPU.
  The API returned a sanitized 504, and capacity stayed occupied while native work
  continued. The test container was then stopped with a short grace period to
  abandon that slow experiment. The supported CPU default is now float32; bfloat16
  remains opt-in. Numeric precision can differ from the script's default dtype.
- The float32 service used about 840 MiB after scanning in one Docker stats snapshot.
  Peak memory and sustained/concurrent production throughput were not benchmarked.
- Real authenticated Shield scanning was not attempted: no credentials were supplied
  and no external transmission of an image-derived hash was authorized by explicit
  integration-test configuration. HTTP Basic auth, exact request shape, response
  classifications, errors, timeout and 429 paths are tested with a mock transport.
- AMD64 build/inference, hardware other than this ARM64 CPU, and public deployment
  remain unverified. The service has not been published externally.
- NudeNet 3.4.2 wheel metadata says MIT, while its bundled LICENSE files contain
  AGPL-3.0. The bundled licence text is preserved under docs/licenses. Commercial
  deployment/distribution licensing needs upstream clarification.
- The service is left running locally at http://127.0.0.1:8080. Stop it with
  `docker compose down`; the named model cache is preserved.

`docs/example-response.json` is an actual generated-image response, not invented
confidence values. That simple geometric fixture itself received a NudeNet
anatomical detection, illustrating why predictions must not be treated as facts
or automatic moderation decisions.
