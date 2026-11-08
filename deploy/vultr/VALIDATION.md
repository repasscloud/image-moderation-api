# Local implementation evidence — 9 November 2026

Tracking: [Swoovr #294](https://github.com/repasscloud/wanderconnect/issues/294).
This is local evidence, not hosted acceptance or deployment approval.

- Source Docker image built successfully on ARM64 as `swoovr-image-processor:294-local` using the pinned Dockerfile/model snapshot.
- Full Python test suite and Ruff run after final changes; exact final counts are recorded in the PR. Integration tests needing real provider credentials are skipped explicitly.
- `scripts/verify_processing_readiness.py` passed against the built image: actual nonroot UID10001 can read the mounted nonsecret control directory; no marker returns ready and drain marker refuses readiness/new requests. It uses synthetic model/scanner readiness, not real Shield acceptance.
- `scripts/verify_processing_stack.py` passed: actual ClamAV INSTREAM clean and EICAR handling against an owned disposable scanner with tiny SYNTHETIC test definitions, and real NudeNet/Freepik CPU inference on a generated green image. Synthetic signature provenance is injected only by the test; production signature-age checks are not bypassed.
- Actual FastAPI multipart response from synthetic image/fake engines was parsed and verified by the companion Cloudflare Worker tests. This proves framing/manifest agreement, not real classifier accuracy or network deployment.
- Deployment validator/Compose configuration tests passed; no private credentials were placed into source/build layers.
- Controller source review tightened the hosted processor minimum inbound key to32 characters, matching the Worker contract. The existing optional `/v1/scan` configuration remains compatible; new `/v1/process` is opt-in and requires all engines and authentication.

Not verified: AMD64 build/runtime, actual Vultr VMs/load balancer/TLS/firewall, peak throughput/latency/RAM/cost and one-host production capacity, production ClamAV definition freshness, live Shield authentication/provider-approved harmless match, model licensing clearance and full Swoovr media lifecycle cutover. The fresh independent review attempt hit an agent usage limit; no completed independent whole-branch review is claimed. Source/controller review and local tests are complete only to the scope above.

Reproduce with the commands in [README](README.md). Use a harmless provider-approved fixture for any future live Shield acceptance; never abuse imagery. Do not stop or reuse managed application containers/volumes for these tests.


## PR review follow-up — 9 November 2026

Codex review of merged PR2 identified PNG palette/color-key transparency being lost during RGB conversion. Processing now normalises the EXIF-oriented image to RGBA before compositing onto white; transform recipe is `webp-2048-320-v2`. Four format regressions cover palette PNG, RGB/gray color-key PNG and existing RGBA alpha. The first three reproduced before the fix; all four pass after it. Full suite:169 passed,2 provider tests skipped; Ruff and Docker source build passed.

The owner's publishing workflow on main is preserved. [Successful multi-platform build](https://github.com/repasscloud/image-moderation-api/actions/runs/42535592295) built source321dd43 and publishes to Docker Hub (`repasscloud/image-moderation-api`), using tags/manual releases. That published release predates this correction. Merge the follow-up fix and create a fresh image release, then use its immutable index digest on Vultr; a branch push alone does not publish this tag-triggered workflow. No existing image tag was replaced or release workflow triggered by this fix.
