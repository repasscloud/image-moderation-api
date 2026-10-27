import pytest
from app.config import Settings
from app.services.scanner import Scanner
from tests.test_api import FakeEngine, client, scan


def test_disabled_shield_is_not_constructed(monkeypatch):
    import app.engines.arachnid_engine as module

    def forbidden(*args, **kwargs):
        raise AssertionError("Disabled Shield must not be instantiated")

    monkeypatch.setattr(module, "ArachnidEngine", forbidden)
    scanner = Scanner(Settings(enable_nudenet=False, enable_nsfw=False, _env_file=None))
    scanner.load()
    assert scanner.engines == {}


def test_configured_shield_lifecycle_and_availability():
    e = FakeEngine("arachnid")
    with client(
        Settings(arachnid_api_username="user", arachnid_api_password="pass", _env_file=None),
        {"nudenet": FakeEngine("nudenet"), "nsfw": FakeEngine("nsfw"), "arachnid": e},
    ) as c:
        assert c.get("/ready").json()["engines"]["arachnid"] == "ready"
        assert scan(c, "/v1/scan/arachnid").status_code == 200
        assert e.loads == 1


@pytest.mark.parametrize("username,password", [("only-user", None), (None, "only-password"), (None, None)])
def test_incomplete_credentials_preserve_local_scanning(username, password, capsys):
    with client(
        Settings(arachnid_api_username=username, arachnid_api_password=password, _env_file=None)
    ) as c:
        assert c.get("/ready").json()["engines"]["arachnid"] == "disabled"
        assert scan(c).json()["status"] == "completed"
    logs = capsys.readouterr().err
    assert "only-user" not in logs and "only-password" not in logs
    if username or password:
        assert "both credentials are required" in logs
