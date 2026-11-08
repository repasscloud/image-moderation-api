"""Validate private operator files without interpolation, sourcing or secret output."""

import ipaddress
import re
import stat
import sys
from pathlib import Path


def load(path):
    values = {}
    for line in path.read_text().splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise ValueError("Invalid or duplicate environment key")
        values[key] = value
    return values


def validate(path):
    config = load(path)
    required = ("PROCESSOR_IMAGE", "PROCESSOR_BIND_IP", "PROCESSOR_ENV_FILE", "PROCESSOR_CONTROL_DIR")
    if any(not config.get(k) or "REPLACE_" in config[k] for k in required):
        raise ValueError("Missing deployment configuration")
    if not re.fullmatch(r"[a-zA-Z0-9._:/-]+@sha256:[0-9a-f]{64}", config["PROCESSOR_IMAGE"]):
        raise ValueError("Processor image must be pinned by digest")
    ip = ipaddress.ip_address(config["PROCESSOR_BIND_IP"])
    if not ip.is_private or ip.is_unspecified or ip.is_loopback:
        raise ValueError("Bind to a specific private VPC address")
    for value in config.values():
        if any(c in value for c in "$`\n\r\"'"):
            raise ValueError("Deployment settings must be literal unquoted data")
    private = Path(config["PROCESSOR_ENV_FILE"])
    control = Path(config["PROCESSOR_CONTROL_DIR"])
    if not private.is_absolute() or not private.is_file() or private.is_symlink():
        raise ValueError("Private runtime env must be a regular absolute file")
    if stat.S_IMODE(private.stat().st_mode) & 0o077:
        raise ValueError("Private runtime env must have permissions 0600 or stricter")
    secrets = load(private)
    if any(
        not secrets.get(k) or "REPLACE_" in secrets[k]
        for k in ("API_KEY", "ARACHNID_API_USERNAME", "ARACHNID_API_PASSWORD")
    ):
        raise ValueError("Missing mandatory runtime credentials")
    if len(secrets["API_KEY"]) < 32:
        raise ValueError("Inbound processor API key must be at least 32 characters")
    if not control.is_absolute() or not control.is_dir() or control.is_symlink():
        raise ValueError("Create a private absolute control directory first")
    mode = stat.S_IMODE(control.stat().st_mode)
    if mode & 0o005 != 0o005 or mode & 0o022:
        raise ValueError(
            "Control directory must be readable/traversable by container UID10001 and not group/world writable"
        )
    return config


if __name__ == "__main__":
    try:
        config = validate(Path(sys.argv[1]))
        if "--control" in sys.argv[2:]:
            print(config["PROCESSOR_CONTROL_DIR"])
    except (ValueError, OSError, IndexError):
        sys.exit(
            "Invalid deployment configuration; check required paths, digest, private IP and secret-file permissions."
        )
