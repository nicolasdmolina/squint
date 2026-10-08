"""Settings: `server/squint.toml` plus environment overrides.

Environment variables (all optional):
  SQUINT_CONFIG            path to the TOML file (default: server/squint.toml)
  SQUINT_PROFILE           model profile name from [profiles.*] (default: [models].profile)
  SQUINT_HOST, SQUINT_PORT where uvicorn listens (default 127.0.0.1:8017)
  SQUINT_IDLE_UNLOAD_S     unload the models after this many idle seconds (default 600)
  SQUINT_RESULT_TTL_S      keep finished results in memory this long (default 600)
  SQUINT_CALIBRATION_DIR   where thresholds.json / report.json live (default: <repo>/calibration)
  SQUINT_WEB_DIST          built web UI to serve at / (default: <repo>/web/dist)
  SQUINT_KEYCHAIN_SERVICE  Keychain generic-password service name (default: squint-password)
  SQUINT_LOG_LEVEL         python logging level (default INFO)
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = SERVER_DIR.parent
DEFAULT_CONFIG = SERVER_DIR / "squint.toml"


@dataclass(frozen=True)
class ModelFile:
    path: str  # absolute path on disk
    repo: str | None = None  # Hugging Face repo to download from
    filename: str | None = None  # file inside that repo
    revision: str | None = None


@dataclass(frozen=True)
class ModelProfile:
    name: str
    observer_label: str
    performer_label: str
    observer: ModelFile
    performer: ModelFile
    tokenizer: ModelFile
    context_tokens: int = 2048
    overlap_tokens: int = 512
    batch_tokens: int = 512
    gpu_layers: int = -1
    flash_attn: str = "auto"

    @property
    def observer_path(self) -> str:
        return self.observer.path

    @property
    def performer_path(self) -> str:
        return self.performer.path

    @property
    def model_pair(self) -> dict:
        return {"observer": self.observer_label, "performer": self.performer_label}


@dataclass(frozen=True)
class Limits:
    min_words: int = 20
    percent_min_words: int = 150
    max_words: int = 2500
    max_chars: int = 40_000
    max_tokens: int = 12_000
    checks_per_hour: int = 30

    def public(self) -> dict:
        return {
            "min_words": self.min_words,
            "percent_min_words": self.percent_min_words,
            "max_words": self.max_words,
            "checks_per_hour": self.checks_per_hour,
        }


@dataclass(frozen=True)
class Settings:
    profile: ModelProfile
    host: str = "127.0.0.1"
    port: int = 8017
    limits: Limits = field(default_factory=Limits)
    idle_unload_s: float = 600.0
    result_ttl_s: float = 600.0
    max_queue: int = 50
    calibration_dir: Path = REPO_DIR / "calibration"
    web_dist: Path = REPO_DIR / "web" / "dist"
    keychain_service: str = "squint-password"
    session_ttl_s: int = 30 * 24 * 3600
    login_max_failures: int = 5
    login_window_s: int = 15 * 60
    login_global_max_failures: int = 50
    login_global_window_s: int = 3600
    max_upload_bytes: int = 10 * 1024 * 1024
    max_json_bytes: int = 1024 * 1024

    def with_overrides(self, **kw) -> "Settings":
        return replace(self, **kw)


def _resolve(path: str, base: Path) -> str:
    p = Path(os.path.expanduser(path))
    return str(p if p.is_absolute() else (base / p).resolve())


def _model_file(raw: dict | str, base: Path) -> ModelFile:
    if isinstance(raw, str):
        return ModelFile(path=_resolve(raw, base))
    return ModelFile(
        path=_resolve(raw["path"], base),
        repo=raw.get("repo"),
        filename=raw.get("filename"),
        revision=raw.get("revision"),
    )


def load_profiles(config_path: Path | None = None) -> tuple[dict[str, ModelProfile], dict]:
    path = Path(config_path or os.environ.get("SQUINT_CONFIG") or DEFAULT_CONFIG)
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    base = path.resolve().parent
    profiles = {}
    for name, p in (raw.get("profiles") or {}).items():
        profiles[name] = ModelProfile(
            name=name,
            observer_label=p["observer_label"],
            performer_label=p["performer_label"],
            observer=_model_file(p["observer"], base),
            performer=_model_file(p["performer"], base),
            tokenizer=_model_file(p["tokenizer"], base),
            context_tokens=int(p.get("context_tokens", 2048)),
            overlap_tokens=int(p.get("overlap_tokens", 512)),
            batch_tokens=int(p.get("batch_tokens", 512)),
            gpu_layers=int(p.get("gpu_layers", -1)),
            flash_attn=str(p.get("flash_attn", "auto")),
        )
    return profiles, raw


def load_settings(config_path: Path | None = None, profile: str | None = None) -> Settings:
    profiles, raw = load_profiles(config_path)
    name = profile or os.environ.get("SQUINT_PROFILE") or (raw.get("models") or {}).get("profile")
    if not name or name not in profiles:
        raise SystemExit(f"unknown model profile {name!r}; known: {', '.join(sorted(profiles))}")
    srv = raw.get("server") or {}
    lim = raw.get("limits") or {}
    env = os.environ
    return Settings(
        profile=profiles[name],
        host=env.get("SQUINT_HOST", srv.get("host", "127.0.0.1")),
        port=int(env.get("SQUINT_PORT", srv.get("port", 8017))),
        limits=Limits(**{k: int(v) for k, v in lim.items()}),
        idle_unload_s=float(env.get("SQUINT_IDLE_UNLOAD_S", srv.get("idle_unload_s", 600))),
        result_ttl_s=float(env.get("SQUINT_RESULT_TTL_S", srv.get("result_ttl_s", 600))),
        max_queue=int(srv.get("max_queue", 50)),
        calibration_dir=Path(env.get("SQUINT_CALIBRATION_DIR", REPO_DIR / "calibration")),
        web_dist=Path(env.get("SQUINT_WEB_DIST", REPO_DIR / "web" / "dist")),
        keychain_service=env.get("SQUINT_KEYCHAIN_SERVICE", srv.get("keychain_service", "squint-password")),
    )
