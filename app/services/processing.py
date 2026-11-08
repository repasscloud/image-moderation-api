"""Protocol preparation, not Swoovr moderation policy. Only the Worker decides pass/review."""

import hashlib
import io
from importlib.metadata import version, PackageNotFoundError

from PIL import Image, ImageOps
from app.errors import APIError
from app.services.images import validate_image


def installed(package):
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"


def process(data, job, scanner, malware, settings):
    if hashlib.sha256(data).hexdigest() != job.sourceSha256:
        raise APIError(409, "source_changed", "Upload digest did not match the processing job.")
    results = {name: {"status": "not_requested"} for name in ("nudenet", "nsfw", "arachnid")}
    results["malware"] = malware.scan(data)
    manifest = {
        "protocolVersion": 1,
        "jobId": str(job.jobId),
        "imageId": str(job.imageId),
        "sourceSha256": job.sourceSha256,
        "results": results,
        "variants": [],
        "recipeVersion": "webp-2048-320-v2",
    }
    if results["malware"].get("status") != "completed" or results["malware"].get("classification") != "clean":
        return manifest, {}
    validate_image(data, settings)
    with Image.open(io.BytesIO(data)) as dimensions:
        if min(dimensions.size) < settings.processing_min_side:
            raise APIError(422, "image_too_small", "Image dimensions are below the processing minimum.")
    scanned = scanner.scan(data, None, ["nudenet", "nsfw", "arachnid"], validated=True)
    for name in ("nudenet", "nsfw", "arachnid"):
        results[name] = {k: v for k, v in scanned["results"][name].items() if k != "raw"}
    results["nudenet"]["modelVersion"] = "nudenet-" + installed("nudenet") + "-320n"
    results["nsfw"]["modelVersion"] = "nsfw-image-detector-" + installed("nsfw-image-detector")
    revision_file = settings.model_cache / "freepik" / "REVISION"
    if revision_file.is_file():
        revision = revision_file.read_text().strip()
        if len(revision) == 40 and all(c in "0123456789abcdef" for c in revision):
            results["nsfw"]["modelRevision"] = revision
    results["arachnid"]["adapterVersion"] = "pdqhash-" + installed("pdqhash")
    if any(results[name].get("status") != "completed" for name in ("nudenet", "nsfw", "arachnid")):
        return manifest, {}
    if results["arachnid"].get("classification") != "no-known-match":
        return manifest, {}
    # No content-policy verdict here. Valid ordinary review candidates can be prepared privately.
    variants = {}
    with Image.open(io.BytesIO(data)) as source:
        oriented = ImageOps.exif_transpose(source)
        # RGBA resolves palette transparency and PNG color-key metadata as well as alpha bands.
        with oriented.convert("RGBA") as rgba, Image.new("RGB", oriented.size, "white") as flattened:
            with rgba.getchannel("A") as alpha:
                flattened.paste(rgba, mask=alpha)
            for name, side in (("display", 2048), ("thumbnail", 320)):
                with flattened.copy() as variant:
                    variant.thumbnail((side, side), Image.Resampling.LANCZOS)
                    buffer = io.BytesIO()
                    variant.save(buffer, "WEBP", quality=85, method=4, exif=b"", icc_profile=b"", xmp=b"")
                    content = buffer.getvalue()
                    variants[name] = content
                    manifest["variants"].append(
                        {
                            "name": name,
                            "contentType": "image/webp",
                            "width": variant.width,
                            "height": variant.height,
                            "bytes": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                        }
                    )
        if oriented is not source:
            oriented.close()
    if sum(map(len, variants.values())) > settings.processing_max_output_mb * 1024 * 1024:
        raise APIError(413, "output_limit", "Prepared image exceeds the output limit.")
    return manifest, variants
