import json

import pytest

from portrait_qa import config
from portrait_qa.errors import ConfigError


def write(tmp_path, data, raw=None):
    path = tmp_path / "config.json"
    path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
    return path


def test_missing_file_means_defaults(tmp_path):
    s = config.load(tmp_path / "config.json")
    assert s.server.host == "127.0.0.1" and s.server.port == 8080 and s.server.api_key == ""
    assert s.default_profile == "default"


def test_partial_file(tmp_path):
    s = config.load(write(tmp_path, {"server": {"port": 9000}, "quality": {"min_score": 70}}))
    assert s.server.port == 9000 and s.server.host == "127.0.0.1"
    assert s.quality.min_score == 70 and s.quality.min_sharpness == 15.0


def test_custom_profile_and_default(tmp_path):
    data = {
        "default_profile": "terminal",
        "profiles": {"terminal": {"width": 480, "height": 640, "max_kb": 100, "background": [240, 240, 240]}},
    }
    s = config.load(write(tmp_path, data))
    profile = s.all_profiles["terminal"]
    assert profile.name == "terminal" and profile.background == (240, 240, 240)
    assert "default" in s.all_profiles  # built-ins stay available


def test_utf8_bom_is_accepted(tmp_path):
    """Notepad on older Windows saves UTF-8 with a BOM."""
    path = tmp_path / "config.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"server": {"port": 8181}}).encode())
    assert config.load(path).server.port == 8181


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"serverr": {}}, "unknown key"),
        ({"server": {"prot": 1}}, "unknown key"),
        ({"server": {"port": "8080"}}, "server.port must be int"),
        ({"server": {"port": 70000}}, "port"),
        ({"server": {"port": 80.5}}, "server.port must be int"),
        ({"server": {"cors_origins": "https://app.example"}}, "list of strings"),
        ({"server": {"api_key": None}}, "must not be null"),
        ({"profiles": {"x": {"width": 300, "height": 400, "background": "abc"}}}, "list of 3 integers"),
        ({"profiles": {"x": {"width": 300, "height": 400, "background": [1, 2, [3]]}}}, "list of 3 integers"),
        ({"profiles": {"x": {"width": 300, "height": 400, "name": "y"}}}, "remove 'name'"),
        ({"log_level": 5}, "log_level must be str"),
        ({"default_profile": ["a"]}, "default_profile must be str"),
        ({"quality": {"min_sharpness": -5}}, "min_sharpness"),
        ({"quality": {"min_brightness": 200, "max_brightness": 100}}, "brightness"),
        ({"quality": {"min_eye_distance_px": 100}}, "eye_distance"),
        ({"quality": {"min_score": 150}}, "min_score"),
        ({"default_profile": "nope"}, "not a known profile"),
        ({"profiles": {"x": {"width": 300}}}, "profiles.x"),
        ({"profiles": {"x": {"width": 300, "height": 400, "eye_line": 0.95}}}, "eye_line"),
        ({"profiles": {"x": 5}}, "must be an object"),
        ({"log_level": "loud"}, "log_level"),
        ({"detector": {"max_side": 50}}, "max_side"),
    ],
)
def test_invalid_config(tmp_path, data, message):
    with pytest.raises(ConfigError, match=message):
        config.load(write(tmp_path, data))


def test_invalid_json_reports_the_line(tmp_path):
    with pytest.raises(ConfigError, match="line 2"):
        config.load(write(tmp_path, None, raw='{\n  "server": ,\n}'))


def test_decimals_and_integral_floats(tmp_path):
    s = config.load(write(tmp_path, {"quality": {"min_eye_distance_px": 45.5}, "server": {"port": 9000.0}}))
    assert s.quality.min_eye_distance_px == 45.5
    assert s.server.port == 9000 and isinstance(s.server.port, int)


def test_null_max_kb_is_allowed(tmp_path):
    s = config.load(write(tmp_path, {"profiles": {"raw": {"width": 300, "height": 400, "max_kb": None}}}))
    assert s.all_profiles["raw"].max_kb is None


def test_save_and_load_round_trip(tmp_path):
    s = config.load(write(tmp_path, {"profiles": {"t": {"width": 300, "height": 400}}}))
    s.server.api_key = "secret-key-123456"
    s.server.host = "0.0.0.0"
    path = config.save(s, tmp_path / "out" / "config.json")
    again = config.load(path)
    assert again.to_dict() == s.to_dict()
    assert not list(path.parent.glob("*.tmp"))


def test_env_var_selects_the_file(tmp_path, monkeypatch):
    path = write(tmp_path, {"server": {"port": 9123}})
    monkeypatch.setenv(config.CONFIG_ENV, str(path))
    assert config.default_config_path() == path
    assert config.load().server.port == 9123
