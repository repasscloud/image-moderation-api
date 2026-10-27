# Reading image-analysis results

Version: current service contract; reviewed 28 October 2026.
Audience: consuming-API developers, moderators, and LLMs interpreting **JSON results**.
The rules below explain evidence; policy choices are explicitly labelled as examples.

Companion files:

- [Machine-readable catalogue](results-reference.json): all current labels, score meanings, states and error codes.
- [LLM instructions](llm-results-instructions.md): copyable interpretation instructions and output format.
- [OpenAPI](openapi.json): request/response types and endpoints.
- [Actual generated-image response](example-response.json): real model output, not an idealized detection example.

## 1. What each engine can answer

| Question | Read | What that evidence supports |
|---|---|---|
| Did the detector predict exposed anatomy that our policy counts as nudity? | `results.nudenet.detections` | Class-specific anatomical predictions above your chosen thresholds. |
| Did the whole image meet the Freepik NSFW threshold? | `results.nsfw.is_nsfw` and `probabilities[0]` | A separate image-level NSFW signal. It does not name exposed body parts. |
| Did Shield classify a known-content match as CSAM? | `results.arachnid.classification` | A provider-reported known-content matching result. |
| Is this definitely free of nudity or CSAM? | No field can establish this | Negative predictions and database misses have limited coverage. |

The service returns **no `has_nudity`, `is_csam`, `safe`, `allowed`, age, consent,
or legal-status field**. Those are not hidden meanings of `status` or a score.
A consumer may compute a policy-scoped nudity signal, but it must keep that distinct
from facts about the image. Models can miss anatomy or misidentify ordinary objects.
The actual geometric test image in example-response.json illustrates a false anatomical prediction.

Nudity, NSFW and known-content matching are independent signals. Do not vote across
them, require local nudity before accepting a Shield match, or infer CSAM from NSFW
scores, anatomy labels, a face label, or an LLM's guess about age. A Shield CSAM match
can matter even when neither local model predicts nudity.

## 2. Parse the response before interpreting content

A successful HTTP exchange is not itself a successful content check. First inspect
the HTTP status and envelope; then inspect **each engine's own status**.

### Scan envelope

| Field | JSON type | Meaning / consumer handling |
|---|---|---|
| `scan_id` | UUID string | Identifier of this scan response. Not an image hash or proof of uniqueness of the media. |
| `status` | string enum | Execution summary defined below; not a content verdict. |
| `filename` | string or null | Bounded upload basename; null for URL scans. Never a trusted filesystem path or policy input. |
| `processing_time_ms` | number | Elapsed validation/scanning time; URL scans include download time. Not a confidence value. |
| `results` | object | Entries named `nudenet`, `nsfw`, and `arachnid`, including disabled/unrequested engines. |

### Overall status

| Value | Meaning | What to do |
|---|---|---|
| `completed` | Every requested engine completed | Read individual results; disabled engines may still be present. This does not mean all three engines ran or the image passed moderation. |
| `partial` | At least one requested engine completed and another failed | Use completed evidence; keep the failed checks unknown. |
| `failed` | No requested engine completed | No successful requested analysis; do not translate this into a negative content result. |

### Common engine fields

| Field | JSON type | Presence / meaning |
|---|---|---|
| `status` | string enum | Always present; gate all engine-specific interpretation on `completed`. |
| `inference_time_ms` | number | Present for executed attempts, including failures. For Arachnid this includes local hashing and its HTTP request. |
| `error` | object | Present on failure, with string `code` and human-readable string `message`. Branch on code/status rather than matching message text. |

| Engine status | Meaning | Content interpretation |
|---|---|---|
| `completed` | Engine returned its result | Interpret that engine's fields. Completion does not mean no detections. |
| `failed` | No usable result from that attempt | Unknown for this engine. |
| `disabled` | Configuration turned it off | Not checked. |
| `not_requested` | Enabled, but excluded by engine selection | Not checked. |

The current wire implementation **omits** inapplicable optional fields; it does not
fill every schema property with null. For example, a disabled engine is normally
`{"status":"disabled"}`. A completed NudeNet result may have an empty detections
array. Do not confuse an absent array on a failed engine with that empty array.
If a required completed-result field is absent, has the wrong type, or contains a
future unrecognized value, record an integration/unknown state instead of inventing
a default. Validate inputs against the OpenAPI contract and the engine-specific
requirements in this document; the shared schema is intentionally permissive.

HTTP 200 carries completed or partial scans. HTTP 502 can carry either an all-engine
failed scan envelope, or (for URL retrieval) an `error` envelope. Inspect shape, not
just status. HTTP 504 has an error envelope and exposes no partial scan results,
even if native work continues after the response deadline. A lost connection or
non-JSON proxy error likewise provides no completed scan response to interpret.

## 3. NudeNet: deciding whether your policy has a nudity signal

### Detection fields

A completed result contains `detections`, an array of objects:

| Field | JSON type | Meaning |
|---|---|---|
| `class` | case-sensitive string | One of the labels below. This is the JSON key, even though the internal Pydantic field is named `label`. |
| `score` | number | Per-detection model confidence, normally 0–1. Not a calibrated probability of image-level nudity, an age score, or a legal conclusion. |
| `box` | array of four integers | `[x, y, width, height]` in decoded/oriented image pixels, from the top-left. Not normalized coordinates or `[x1,y1,x2,y2]`. |

For `[10,20,30,40]`, the corresponding bottom-right coordinate is `[40,60]`.
Match viewer orientation and scaling when drawing a box. Multiple detections can
refer to one person or overlapping regions; box count is not a person count. Do not
sum scores as a probability of nudity.

### Every current class

The group names in this table are **documentation/consumer policy categories**, not
extra output labels. Descriptions explain the label wording, not verified anatomy
or a person's gender identity. Retain original model labels in your audit evidence.

| Exact label | Predicted region | Suggested policy category |
|---|---|---|
| `FEMALE_GENITALIA_EXPOSED` | Exposed genital region | genital/anus exposure |
| `MALE_GENITALIA_EXPOSED` | Exposed genital region | genital/anus exposure |
| `ANUS_EXPOSED` | Exposed anus | genital/anus exposure |
| `FEMALE_BREAST_EXPOSED` | Exposed breast | breast exposure |
| `BUTTOCKS_EXPOSED` | Exposed buttocks | buttocks exposure |
| `MALE_BREAST_EXPOSED` | Exposed chest | bare chest |
| `FEMALE_GENITALIA_COVERED` | Covered genital region | covered anatomy |
| `FEMALE_BREAST_COVERED` | Covered breast | covered anatomy |
| `BUTTOCKS_COVERED` | Covered buttocks | covered anatomy |
| `ANUS_COVERED` | Covered anus | covered anatomy |
| `BELLY_EXPOSED` | Exposed abdomen | other anatomy |
| `BELLY_COVERED` | Covered abdomen | covered anatomy |
| `ARMPITS_EXPOSED` | Exposed armpit | other anatomy |
| `ARMPITS_COVERED` | Covered armpit | covered anatomy |
| `FEET_EXPOSED` | Exposed foot | other anatomy |
| `FEET_COVERED` | Covered foot | covered anatomy |
| `FACE_FEMALE` | Face label | face; no age inference |
| `FACE_MALE` | Face label | face; no age inference |

See the [upstream label list](https://github.com/notAI-tech/NudeNet/blob/v3/README.md).
Covered regions, faces, feet, abdomen and armpits do not independently establish
exposure of genitals, breasts, anus or buttocks. In particular, **do not flag every
label ending in `_EXPOSED` as nudity**. A bare-chest or buttocks rule is an explicit
application choice; neither should be silently equated to genital exposure.

### Implementable consumer rule

1. Define the anatomical classes your product calls nudity.
2. Choose and version thresholds, ideally per class, using a representative,
   appropriately sourced validation set. There is no validated universal threshold
   supplied by this service. Measure false positives and false negatives.
3. Only inspect a completed NudeNet result. Flag a **nudity signal** when at least
   one selected class has `score >= threshold_for_that_class`.
4. Preserve the matched class, score and box as evidence. Return `no_signal_detected`
   if none qualify, not `definitely_no_nudity`. If the engine failed/was not run or
   the completed result is malformed, use `unknown`.
5. Route ambiguous scores, unexpected labels and conflicting signals through your
   own review rules; do not suppress a known-content match because of local scores.

**Illustrative policy, not a recommended production calibration:** count the three
exposed genital/anus labels, exposed breasts and exposed buttocks; use 0.50 as the
threshold for this example only. Treat bare chest separately. A threshold comparison
can be expressed as:

```python
# Consumer-side pseudocode: validate result shape/types before this step.
# These values illustrate mechanics; calibrate/version your own policy.
thresholds = {
    "FEMALE_GENITALIA_EXPOSED": 0.50,
    "MALE_GENITALIA_EXPOSED": 0.50,
    "ANUS_EXPOSED": 0.50,
    "FEMALE_BREAST_EXPOSED": 0.50,
    "BUTTOCKS_EXPOSED": 0.50,
}
engine = response["results"]["nudenet"]
if engine["status"] != "completed":
    nudity_state = "unknown"
    evidence = []
else:
    evidence = [d for d in engine["detections"]
                if d["class"] in thresholds
                and d["score"] >= thresholds[d["class"]]]
    nudity_state = "signal_detected" if evidence else "no_signal_detected"
```

A `MALE_GENITALIA_EXPOSED` score of 0.70 qualifies under that example. An
`ARMPITS_EXPOSED` score of 0.99 does not. A selected label scoring 0.49 does not
qualify under that example, but is not proof of absence. All numbers in this
paragraph are synthetic instructional values, not new inference measurements.
The pseudocode assumes the known-label/type validation described above has already
succeeded; unrecognized labels should be surfaced rather than silently cleared.

The service's `NUDENET_CONFIDENCE_THRESHOLD` adds an output filter; default 0 retains
the library's returned detections. It does not remove the library's own candidate
and non-maximum-suppression filtering. A consumer threshold cannot recover boxes
already filtered out by the service/library. For the pinned 3.4.2 code, candidate
filtering uses 0.2 and OpenCV NMS uses score threshold 0.25 and IoU 0.45; these are
implementation details, not recommended moderation thresholds. Source:
[pinned algorithm](https://github.com/notAI-tech/NudeNet/blob/v3/nudenet/nudenet.py).

## 4. Freepik: NSFW does not mean anatomical nudity or CSAM

A completed NSFW result has:

| Field | JSON type | Meaning |
|---|---|---|
| `classification` | boolean | The package's default `is_nsfw` result; **not** a string such as `medium`. |
| `is_nsfw` | boolean | Same library boolean, repeated with an explicit name. Do not count the two fields as independent votes. |
| `probabilities` | array of objects | One score dictionary for this single-image API; read `probabilities[0]`. |

| Score key | Meaning in the Python package |
|---|---|
| `neutral` | Model mass for neutral |
| `low` | Cumulative model mass for low + medium + high |
| `medium` | Cumulative model mass for medium + high |
| `high` | Model mass for high |

Scores are numbers normally in 0–1. The default boolean is `medium >= 0.5`, including
equality. False means this threshold was not met, not that nudity or CSAM is absent.
There are no documented anatomy-specific definitions here that let you equate
`medium` with breasts, `high` with genital exposure, or any category with minors.
Source: [package implementation](https://github.com/freepik-company/nsfw_image_detector/blob/main/nsfw_image_detector/detector.py).

Synthetic arithmetic example:

```json
[{"neutral":0.10,"low":0.90,"medium":0.70,"high":0.20}]
```

This yields `is_nsfw=true`. The values are cumulative and must not be added together
or fed to an argmax as an exclusive class distribution. In exact arithmetic you
could recover approximate exclusive masses using `low-medium` and `medium-high`,
but floating-point rounding applies; those derived values are **not API fields**.
The service preserves the package values. Its package scoring differs from the
separate Transformers pipeline example on the
[model card](https://huggingface.co/Freepik/nsfw_image_detector); do not substitute
that pipeline's output schema for this service's schema. CPU dtype can change scores;
validate thresholds on the deployed precision.

Use Freepik as a complementary NSFW signal. If your requirement is specifically
visible nudity, use your NudeNet class policy to express that requirement; do not
rename an NSFW boolean `has_nudity` without explicitly documenting that different rule.

## 5. Shield: known CSAM and harmful/abusive matching

Read Shield only if `results.arachnid.status == "completed"`. Its absence, disablement,
selection exclusion, timeout or failure is **not a negative CSAM check**. Readiness
only means the client was configured; it does not prove a successful authenticated match query.

| Field | JSON type | Meaning |
|---|---|---|
| `classification` | string | Shield's result for the submitted PDQ hash; exact values below. Distinct from Freepik's boolean field of the same name. |
| `match_type` | string or null | Provider mode: currently `exact`, `near`, or null. Do not invent a distance/confidence from it. |
| `pdq_quality` | integer | Local PDQ hash-suitability measure, not a CSAM probability, severity, or match confidence. |
| `raw` | object | Original parsed Shield response; retain if needed under your own restricted audit policy. |

| Exact classification | Consumer state | Interpretation |
|---|---|---|
| `csam` | `known_csam_match` | Shield returned its CSAM classification. Preserve as known-content evidence and invoke your controlled handling workflow. Do not downgrade it because local scores are low. |
| `harmful-abusive-material` | `known_harmful_abusive_match` | Separate provider category; retain its exact value rather than renaming it CSAM. |
| `no-known-match` | `no_known_match` | No known database match returned. Not proof that the media is safe or that novel/unmatched CSAM is absent. |
| `test` | `test_result` | Test classification; do not treat it as a real CSAM positive or as a clean production result. |
| Any other string | `unknown_classification` | Preserve the string and surface it to an operator/integration owner. Never silently translate it into safe/no match. |

These consumer states are suggested application vocabulary, **not extra API fields**.
Keep engine `failed`, `disabled`, `not_requested`, missing or malformed results as
`unknown`, with the reason recorded. An all-engines `completed` response can still
contain Arachnid `disabled` if credentials were not configured.

This service submits only a local 256-bit PDQ hash, not the image or signed source
URL. `exact` is the provider's matching mode for this query; it is not a promise of
SHA-256 equality of the uploaded file's bytes. `near` is also matching evidence,
not a numeric probability. Do not discard a provider-positive classification simply
because quality is low. No local quality-based suppression is implemented. PDQ's
quality output concerns the usefulness of image features for hashing:
[PDQ reference](https://github.com/facebook/ThreatExchange/tree/main/pdq).

Shield checks known-content fingerprints; the local models do not provide a novel
CSAM classifier or a reliable age determination. The provider describes Shield as
one component of a broader moderation strategy:
[Project Arachnid](https://projectarachnid.com/en/).

### Raw response fields

Current upstream schema: [Shield OpenAPI](https://shield.projectarachnid.com/openapi.json).

| Path | JSON type | Handling |
|---|---|---|
| `raw.scanned_hashes` | object | Mapping of Base64 PDQ hashes to provider results. The adapter selects the submitted hash for the top-level classification. Do not just choose an arbitrary first key. |
| `raw.scanned_hashes[hash].classification` | string | Same provider category used at the engine top level. |
| `raw.scanned_hashes[hash].match_type` | string or null, optional | Provider matching mode. May be absent upstream; top-level adapter then returns null. |
| `raw.scanned_hashes[hash].near_match_details` | array, optional | Provider detail records, if returned; absent is not equivalent to a negative classification. |
| `...near_match_details[].classification` | string | Provider classification of that detail record. Preserve any disagreement; do not overwrite top-level classification using array order. |
| `...near_match_details[].timestamp` | number | Provider-supplied timestamp. This service does not define its units/semantics; not the local scan time. |
| `...near_match_details[].sha1_base32` | string | Provider-supplied fingerprint; not a locally calculated upload checksum. |
| `...near_match_details[].sha256_hex` | string | Provider-supplied fingerprint; not a locally calculated upload checksum. |

Unknown extra provider fields can appear in raw. Keep the source category intact;
do not manufacture a confidence percentage or unsupported identity facts. Hashes
and provider records can be sensitive: avoid general request logs and unnecessary
LLM/external transmission. This guide needs JSON examples, not harmful media.

## 6. Worked interpretation cases

All cases below are hypothetical logic examples, not new model results.

| Returned evidence | Correct interpretation |
|---|---|
| NudeNet completed, genital class above configured threshold; Shield disabled | Nudity signal under that policy; CSAM check unavailable. |
| NudeNet completed, only feet/armpits/face; Freepik true | No nudity signal under the exposed-intimate-anatomy example; separate NSFW signal present. |
| NudeNet completed, empty array; Freepik false; Shield no-known-match | No selected anatomical detection, NSFW threshold not met, no known match. Not proof of safety. |
| Overall completed, Shield disabled | Local work may have completed; no known-content check occurred. |
| Overall partial, NudeNet failed, Freepik false | Nudity unknown, NSFW threshold not met; do not turn the first into false. |
| Shield csam; NudeNet empty and Freepik false | Known CSAM match from Shield; local negatives do not override it. |
| Shield harmful-abusive-material | Preserve separate harmful/abusive match; do not relabel it CSAM. |
| Shield test / new string / timeout | Test result / unknown classification / unavailable check, respectively. |
| HTTP 504 or a proxy error without scan envelope | No usable completed scan response; retry/review according to your own bounded workflow. |

## 7. Error catalogue

Non-scan error envelope: `{"error":{"code":"...","message":"..."}}`.
Errors inside a failed engine use the same two string fields under that engine.
An error status is never evidence that the image lacks nudity/known harmful content.

| Error code(s) | Usual HTTP status | Meaning / caller response |
|---|---|---|
| `unauthorized` | 401 | Missing/incorrect API Bearer token; fix credentials. |
| `invalid_request`, `invalid_multipart`, `invalid_image`, `disconnected` | 400 | Bad request body/image, invalid length, or interrupted upload; correct input. |
| `upload_timeout` | 408 | Incoming body deadline; retry only under your bounded policy. |
| `request_too_large`, `image_too_large`, `pixel_limit`, `dimension_limit` | 413 | Request, downloaded/uploaded bytes, pixels or side length exceeds limits. |
| `unsupported_format`, `animated_image`, `image_encoding_unsupported` | 415 | Unsupported image, multi-frame content, or HTTP content encoding. |
| `validation_error`, `invalid_upload`, `invalid_engine`, `engine_disabled` | 422 | Schema/file/selection/configuration mismatch. `validation_error` messages intentionally omit submitted values. |
| `invalid_image_url`, `image_host_not_allowed`, `image_destination_blocked` | 422 | Invalid URL, hostname outside allowlist, or DNS destination not public. |
| `image_download_failed` | 502 | Remote status/redirect, DNS/connect/TLS/protocol failure, or invalid remote response. No image analysis result implied. |
| `busy`, `no_engines` | 503 | Admission full (`Retry-After: 1`) or no engines enabled. |
| `scan_timeout`, `image_download_timeout` | 504 | Overall work or download deadline; no scan envelope returned. |
| `internal_error` | 500 | Sanitized unexpected failure. |
| `http_error` | varies | Framework HTTP error such as unknown route or unsupported method; not a scan result. |
| `engine_unavailable`, `inference_failed` | per-engine; 200 partial or 502 all failed | Initialization unavailable or inference failed. |
| `upstream_timeout`, `upstream_rate_limited`, `upstream_error`, `upstream_response_invalid` | per-engine; 200 partial or 502 all failed | Shield timeout, 429, remote failure, or invalid response. These codes do not mean no-known-match. |

Some malformed remote/native failures can reach the sanitized generic error path;
future error codes must default to an unknown/failed check, not a negative check.

## 8. Diagnostics are not analysis

| Endpoint / field | Meaning |
|---|---|
| `/health`: `status="ok"` | Process liveness only. |
| `/ready`: `ready` boolean | All enabled engine initializations succeeded. All-disabled is ready but cannot scan. |
| `/ready`: engine `ready` / `failed` / `disabled` | Initialization state, not an image verdict or verified Shield credentials. |
| `/v1/engines`: `enabled`, `ready` booleans | Configuration and initialization availability. |

## 9. Integration checklist

- Specify required engines explicitly when policy requires their coverage, or verify
  their presence/status after default all-enabled scanning. A missing credential
  must not silently turn a required Shield check into approval.
- Validate JSON types; for example, Freepik boolean `false` is not string `"false"`.
- Use explicit unknown/not-checked states rather than defaulting missing fields to false.
- Record model/service precision, class selection, thresholds and policy version in
  your consuming application so later decisions are reproducible. The current
  response does not include all that configuration, so do not claim it does.
- Keep nudity, NSFW and Shield classifications separate in storage and audit output.
- Calibrate on permitted, representative data; track errors across the content your
  application actually receives. Do not use this guide's demonstration cutoff as a
  measured commercial operating point.
- If an LLM summarizes results, provide the structured response and explicit policy;
  require field citations and prohibit age/legality/safety guesses. The companion
  instructions provide that contract. Deterministic parsing should implement the
  threshold rule; an LLM can explain the already-computed evidence.
