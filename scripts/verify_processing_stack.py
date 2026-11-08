"""Owned local Docker smoke test: real clamd with tiny synthetic definitions; no provider credentials.

Runs a disposable scanner/network and uses a supplied built processor image to test
INSTREAM clean/EICAR handling and both actual CPU models on a synthetic image.
Never touches managed application containers or production signature volumes.
"""

import argparse
import hashlib
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

CLAMAV = "clamav/clamav@sha256:c21aa18cc0a358678255a3dfb343a4555b58f71b97d7b869df8fdf7ea0a5b4b1"
# Standard harmless antivirus test string, not malware.
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def run(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, **kwargs)


def main(image):
    name = "swoovr-294-smoke-" + uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix=name) as tmp:
        folder = Path(tmp)
        folder.joinpath("test.hdb").write_text(
            f"{hashlib.md5(EICAR).hexdigest()}:{len(EICAR)}:Eicar-Test-Signature\n"
        )
        folder.joinpath("clamd.conf").write_text(
            "Foreground yes\nDatabaseDirectory /fixtures\nTCPSocket 3310\nTCPAddr 0.0.0.0\nPidFile /tmp/clamd.pid\nTemporaryDirectory /tmp\nLogTime yes\nStreamMaxLength 10M\nAlertExceedsMax yes\n"
        )
        source = """
import hashlib,io,json,time
from PIL import Image
from app.config import Settings
from app.services.clamav import ClamAV
from app.services.scanner import Scanner
s=Settings(_env_file=None,clamav_host="scanner",clamav_timeout_seconds=2,model_cache="/opt/models",enable_nudenet=True,enable_nsfw=True)
client=ClamAV(s)
# Tiny test definitions have no production database version/timestamp. ONLY this test
# injects an explicit synthetic provenance label; production freshness is not bypassed.
client.version=lambda:{"engineVersion":"real-clamd/synthetic-db", "signatureVersion":"synthetic-eicar"}
for attempt in range(30):
 try:
  if client.command(b"zPING\\0")=="PONG": break
 except OSError: time.sleep(1)
else: raise RuntimeError("Owned scanner did not become ready")
eicar=bytes.fromhex("EICAR_HEX")
assert client.scan(b"clean synthetic data")["classification"]=="clean"
assert client.scan(eicar)["classification"]=="infected"
scanner=Scanner(s);scanner.load()
assert scanner.ready["nudenet"] and scanner.ready["nsfw"]
buf=io.BytesIO();Image.new("RGB",(640,480),"green").save(buf,"PNG")
result=scanner.scan(buf.getvalue(),None,["nudenet","nsfw"])
assert result["results"]["nudenet"]["status"]=="completed"
assert result["results"]["nsfw"]["status"]=="completed"
scanner.close()
print(json.dumps({"clamav":"real INSTREAM clean/EICAR passed; synthetic definitions", "models":"real NudeNet/Freepik CPU inference passed", "shield":"NOT RUN; no provider credentials"}))
""".replace("EICAR_HEX", EICAR.hex())
        run("network", "create", "--internal", name, stdout=subprocess.DEVNULL)
        try:
            run(
                "run",
                "-d",
                "--rm",
                "--name",
                name,
                "--network",
                name,
                "--network-alias",
                "scanner",
                "--read-only",
                "--tmpfs",
                "/tmp:size=32m",
                "--memory",
                "256m",
                "--cpus",
                "1",
                "--mount",
                f"type=bind,source={folder},target=/fixtures,readonly",
                "--entrypoint",
                "clamd",
                CLAMAV,
                "--config-file=/fixtures/clamd.conf",
                stdout=subprocess.DEVNULL,
            )
            run(
                "run",
                "--rm",
                "-i",
                "--network",
                name,
                "--read-only",
                "--tmpfs",
                "/tmp:size=64m",
                "--memory",
                "4g",
                "--cpus",
                "2",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--entrypoint",
                "python",
                image,
                "-",
                input=source.encode(),
                timeout=240,
            )
        finally:
            subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(
                ["docker", "network", "rm", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    main(parser.parse_args().image)
