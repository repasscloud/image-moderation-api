# Standalone image moderation service

The supplied specification is the implementation contract. No application-specific policies or remote media fetching are introduced. The three original shell scripts remain unchanged.

1. Establish tests for configuration, shared auth, selection, image validation, readiness and partial failures; run them before implementation.
2. Implement typed settings, sanitized JSON errors/logging, bounded pre-parser admission/body handling, lifespan model ownership and a serial inference executor. Keep capacity occupied until timed-out native work actually finishes.
3. Adapt the exact NudeNet package detector, Freepik package API, and PDQ packbits/Base64 plus Shield Basic authentication. Test adapters separately, including HTTP failures.
4. Pin dependencies and model snapshot; build a non-root CPU Docker image and localhost-only Compose deployment. Cache model weights in a dedicated setup step with offline runtime loading.
5. Run unit tests, Docker build, container health/readiness, synthetic image inference, direct-library parity and authentication checks. Export the application-generated OpenAPI contract and record precise limitations.

Decisions: one worker; one admitted scan by default with immediate 503 when busy; 40 million decoded pixels; 20 MiB file limit plus 64 KiB multipart overhead; 30 second upload deadline; 120 second scan deadline. Timeouts cannot kill a native inference thread, so it retains its capacity until completion. Failed model startup keeps liveness available and readiness false. Shield is never contacted during startup. Freepik classification is its actual boolean `is_nsfw`, not an invented categorical argmax over cumulative probabilities.
