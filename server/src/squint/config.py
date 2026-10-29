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
  SQUINT_REQUIRE_PASSWORD  1/true: refuse to start when no password is found (default: [server].require_password)
  SQUINT_LOG_LEVEL         python logging level (default INFO)
  SQUINT_MODE              full (default) or preview: classifier only, with [preview] limits
  SQUINT_APP               1/true: running inside Squint for Mac ([app] limits, no password)
  SQUINT_DATA_DIR          base for relative model paths (default: the config file's directory)
  SQUINT_EDGE_SECRET       cloud backends: /api answers only requests carrying X-Squint-Edge with this
                           value (the Worker adds it), and X-Squint-Client names the client to rate-limit
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
    extracts_per_hour: int = 30  # file uploads per client

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
    mode: str = "full"  # full | preview (classifier only, no Binoculars; docs/api-contract.md v1.3)
    app: bool = False  # Squint for Mac (squint.desktop): a single local user, so no password or rate cap
    host: str = "127.0.0.1"
    port: int = 8017
    limits: Limits = field(default_factory=Limits)
    idle_unload_s: float = 600.0
    result_ttl_s: float = 600.0
    max_queue: int = 50
    calibration_dir: Path = REPO_DIR / "calibration"
    web_dist: Path = REPO_DIR / "web" / "dist"
    keychain_service: str = "squint-password"
    require_password: bool = False
    edge_secret: str | None = None  # SQUINT_EDGE_SECRET: only the edge Worker may call /api
    session_ttl_s: int = 30 * 24 * 3600
    login_max_failures: int = 5  # per client: then 429 until the window passes
    login_window_s: int = 15 * 60
    login_global_max_failures: int = 50  # all clients: past this every attempt is slowed, never blocked
    login_global_window_s: int = 3600
    login_global_delay_s: float = 1.0
    max_upload_bytes: int = 10 * 1024 * 1024
    extract_wait_s: float = 5.0  # wait this long for the one extraction slot, then 503 busy
    max_json_bytes: int = 1024 * 1024

    def with_overrides(self, **kw) -> "Settings":
        return replace(self, **kw)


def _flag(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
    base = Path(os.environ["SQUINT_DATA_DIR"]) if os.environ.get("SQUINT_DATA_DIR") else path.resolve().parent
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
    lim = dict(raw.get("limits") or {})
    env = os.environ
    mode = env.get("SQUINT_MODE", srv.get("mode", "full"))
    if mode not in ("full", "preview"):
        raise SystemExit(f"unknown server mode {mode!r}; use full or preview")
    app = _flag(env.get("SQUINT_APP", False))
    max_queue = srv.get("max_queue", 50)
    if app:
        lim.update(raw.get("app") or {})
    elif mode == "preview":
        preview = dict(raw.get("preview") or {})
        max_queue = preview.pop("max_queue", max_queue)
        lim.update(preview)
    return Settings(
        profile=profiles[name],
        mode=mode,
        app=app,
        host=env.get("SQUINT_HOST", srv.get("host", "127.0.0.1")),
        port=int(env.get("SQUINT_PORT", srv.get("port", 8017))),
        limits=Limits(**{k: int(v) for k, v in lim.items()}),
        idle_unload_s=float(env.get("SQUINT_IDLE_UNLOAD_S", srv.get("idle_unload_s", 600))),
        result_ttl_s=float(env.get("SQUINT_RESULT_TTL_S", srv.get("result_ttl_s", 600))),
        max_queue=int(max_queue),
        calibration_dir=Path(env.get("SQUINT_CALIBRATION_DIR", REPO_DIR / "calibration")),
        web_dist=Path(env.get("SQUINT_WEB_DIST", REPO_DIR / "web" / "dist")),
        keychain_service=env.get("SQUINT_KEYCHAIN_SERVICE", srv.get("keychain_service", "squint-password")),
        require_password=_flag(env.get("SQUINT_REQUIRE_PASSWORD", srv.get("require_password", False))),
        edge_secret=env.get("SQUINT_EDGE_SECRET") or None,
    )
