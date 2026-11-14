"""Settings, read from a single ``config.json``.

Location: ``--config`` / ``PORTRAIT_QA_CONFIG``; otherwise ``config.json`` next to the executable (frozen build)
or in the current directory. A missing file means all defaults. Unknown keys are refused so a typo does not
silently fall back to a default.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .crop import BUILTIN_PROFILES, OutputProfile
from .errors import ConfigError
from .quality import QualityThresholds

CONFIG_ENV = "PORTRAIT_QA_CONFIG"


@dataclass
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 8080
    api_key: str = ""  # empty = no authentication (fine on 127.0.0.1; set one when listening on the network)
    max_concurrency: int = 0  # 0 = number of CPU cores
    queue_timeout_seconds: float = 10.0  # wait this long for a free worker before answering 503
    cors_origins: list[str] = field(default_factory=list)  # e.g. ["https://my-app.example"] for browser apps


@dataclass
class LimitSettings:
    max_upload_mb: float = 10.0
    max_megapixels: float = 50.0


@dataclass
class DetectorSettings:
    score_threshold: float = 0.6
    max_side: int = 640


@dataclass
class Settings:
    server: ServerSettings = field(default_factory=ServerSettings)
    limits: LimitSettings = field(default_factory=LimitSettings)
    detector: DetectorSettings = field(default_factory=DetectorSettings)
    quality: QualityThresholds = field(default_factory=QualityThresholds)
    default_profile: str = "default"
    profiles: dict[str, OutputProfile] = field(default_factory=dict)  # extra / overriding profiles
    log_level: str = "info"

    @property
    def all_profiles(self) -> dict[str, OutputProfile]:
        return {**BUILTIN_PROFILES, **self.profiles}

    @property
    def max_upload_bytes(self) -> int:
        return int(self.limits.max_upload_mb * 1024 * 1024)

    @property
    def max_pixels(self) -> int:
        return int(self.limits.max_megapixels * 1_000_000)

    def concurrency(self) -> int:
        return self.server.max_concurrency or max(1, os.cpu_count() or 1)

    def validate(self) -> None:
        s = self.server
        if not 1 <= s.port <= 65535:
            raise ConfigError(f"server.port must be 1-65535, got {s.port}")
        if s.max_concurrency < 0:
            raise ConfigError("server.max_concurrency must be >= 0")
        if self.limits.max_upload_mb <= 0 or self.limits.max_megapixels <= 0:
            raise ConfigError("limits must be positive")
        if not 0.1 <= self.detector.score_threshold <= 0.99:
            raise ConfigError("detector.score_threshold must be between 0.1 and 0.99")
        if not 160 <= self.detector.max_side <= 2048:
            raise ConfigError("detector.max_side must be between 160 and 2048")
        try:
            self.quality.validate()
        except ValueError as exc:
            raise ConfigError(f"quality: {exc}") from exc
        for profile in self.profiles.values():
            try:
                profile.validate()
            except ValueError as exc:
                raise ConfigError(str(exc)) from exc
        if self.default_profile not in self.all_profiles:
            raise ConfigError(f"default_profile {self.default_profile!r} is not a known profile")
        if self.log_level.lower() not in ("debug", "info", "warning", "error"):
            raise ConfigError("log_level must be debug, info, warning or error")

    def to_dict(self) -> dict:
        return {
            "server": asdict(self.server),
            "limits": asdict(self.limits),
            "detector": asdict(self.detector),
            "quality": asdict(self.quality),
            "default_profile": self.default_profile,
            "profiles": {name: _profile_dict(p) for name, p in self.profiles.items()},
            "log_level": self.log_level,
        }


def _profile_dict(p: OutputProfile) -> dict:
    data = p.to_dict()
    data.pop("name")
    return data


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _coerce(annotation: str, value, where: str):
    """Check ``value`` against a field annotation (as written in the dataclass) and return it normalized."""
    optional = annotation.endswith("| None")
    base = annotation.removesuffix("| None").strip()
    if value is None:
        if optional:
            return None
        raise ConfigError(f"{where} must not be null")
    if base == "bool":
        if isinstance(value, bool):
            return value
    elif base == "int":
        if _is_number(value) and float(value).is_integer():
            return int(value)
    elif base == "float":
        if _is_number(value):
            return float(value)
    elif base == "str":
        if isinstance(value, str):
            return value
    elif base == "list[str]":
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return list(value)
    elif base == "tuple[int, int, int]":
        if (
            isinstance(value, (list, tuple))
            and len(value) == 3
            and all(_is_number(v) and float(v).is_integer() for v in value)
        ):
            return tuple(int(v) for v in value)
    else:  # pragma: no cover - a new field type needs a rule here
        raise AssertionError(f"no type rule for {annotation!r} ({where})")
    expected = {"tuple[int, int, int]": "a list of 3 integers", "list[str]": "a list of strings"}.get(base, base)
    raise ConfigError(f"{where} must be {expected}{' or null' if optional else ''}, got {json.dumps(value)}")


def _build(cls, data, section: str):
    if not isinstance(data, dict):
        raise ConfigError(f"{section} must be an object")
    known = {f.name: f for f in fields(cls)}
    unknown = set(data) - set(known)
    if unknown:
        raise ConfigError(f"unknown key(s) in {section}: {', '.join(sorted(unknown))}")
    values = {key: _coerce(str(known[key].type), value, f"{section}.{key}") for key, value in data.items()}
    try:
        return cls(**values)
    except TypeError as exc:  # pragma: no cover - defensive
        raise ConfigError(f"{section}: {exc}") from exc


def from_dict(data: dict) -> Settings:
    if not isinstance(data, dict):
        raise ConfigError("config must be a JSON object")
    top = {f.name for f in fields(Settings)}
    unknown = set(data) - top
    if unknown:
        raise ConfigError(f"unknown key(s) in config: {', '.join(sorted(unknown))}")
    profiles = {}
    raw_profiles = data.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        raise ConfigError("profiles must be an object")
    for name, raw in raw_profiles.items():
        if not isinstance(raw, dict):
            raise ConfigError(f"profiles.{name} must be an object")
        if "name" in raw:
            raise ConfigError(f"profiles.{name}: the profile name is the key; remove 'name'")
        profiles[name] = _build(OutputProfile, {**raw, "name": name}, f"profiles.{name}")
    settings = Settings(
        server=_build(ServerSettings, data.get("server", {}), "server"),
        limits=_build(LimitSettings, data.get("limits", {}), "limits"),
        detector=_build(DetectorSettings, data.get("detector", {}), "detector"),
        quality=_build(QualityThresholds, data.get("quality", {}), "quality"),
        default_profile=_coerce("str", data.get("default_profile", "default"), "default_profile"),
        profiles=profiles,
        log_level=_coerce("str", data.get("log_level", "info"), "log_level"),
    )
    settings.validate()
    return settings


def app_dir() -> Path:
    """Folder of the executable when frozen, else the current directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def default_config_path() -> Path:
    env = os.environ.get(CONFIG_ENV)
    return Path(env) if env else app_dir() / "config.json"


def load(path: Path | None = None) -> Settings:
    path = Path(path) if path else default_config_path()
    if not path.exists():
        settings = Settings()
        settings.validate()
        return settings
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return from_dict(data)


def save(settings: Settings, path: Path | None = None) -> Path:
    settings.validate()
    path = Path(path) if path else default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings.to_dict(), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path
