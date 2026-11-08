import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "vultr_validate", Path(__file__).parents[1] / "deploy/vultr/validate.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def files(tmp_path):
    private = tmp_path / "processor.env"
    private.write_text(
        "API_KEY=fictional-service-key-at-least-32-chars-$value\nARACHNID_API_USERNAME=fixture-user\nARACHNID_API_PASSWORD=fixture-password\n"
    )
    private.chmod(0o600)
    control = tmp_path / "control"
    control.mkdir(mode=0o755)
    config = tmp_path / "compose.env"
    config.write_text(
        f"PROCESSOR_IMAGE=registry.example.test/processor@sha256:{'a' * 64}\nPROCESSOR_BIND_IP=10.0.0.2\nPROCESSOR_ENV_FILE={private}\nPROCESSOR_CONTROL_DIR={control}\n"
    )
    return config, private


def test_literal_secrets_not_interpolated(tmp_path):
    config, private = files(tmp_path)
    assert module.validate(config)["PROCESSOR_BIND_IP"] == "10.0.0.2"
    assert module.load(private)["API_KEY"] == "fictional-service-key-at-least-32-chars-$value"


def test_private_permissions_required(tmp_path):
    config, private = files(tmp_path)
    private.chmod(0o644)
    with pytest.raises(ValueError):
        module.validate(config)


@pytest.mark.parametrize(
    "line",
    [
        "PROCESSOR_IMAGE=repo:latest",
        "PROCESSOR_BIND_IP=0.0.0.0",
        "PROCESSOR_BIND_IP=8.8.8.8",
        "PROCESSOR_BIND_IP=$(echo private)",
    ],
)
def test_unsafe_config_rejected(tmp_path, line):
    config, _ = files(tmp_path)
    key = line.split("=")[0]
    config.write_text(
        "\n".join(line if entry.startswith(key + "=") else entry for entry in config.read_text().splitlines())
    )
    with pytest.raises(ValueError):
        module.validate(config)


def test_private_control_directory_rejected_for_nonroot_container(tmp_path):
    config, _ = files(tmp_path)
    (tmp_path / "control").chmod(0o700)
    with pytest.raises(ValueError):
        module.validate(config)
