from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


# 프로젝트 루트 마커. 이 중 하나라도 있으면 그 디렉터리를 루트로 본다.
_ROOT_MARKERS = ("pyproject.toml", "run.bat", "setup.bat")


def _project_root() -> Path:
    """설치 레이아웃에 의존하지 않고 루트를 찾는다.

    예전 구현은 `Path(__file__).parents[2]` 였다. src/<pkg>/settings.py 레이아웃
    에서는 맞지만, 패키지가 다른 프로젝트 안에 통째로 복사돼 들어가면 깊이가
    달라져서 엉뚱한 상위 폴더(예: D:/00work)를 루트로 잡는다. 그러면 config/ 와
    workspace/ 가 프로젝트 밖을 가리켜, 정작 프로젝트 안에 있는 발음사전을
    못 읽는 사고가 난다. 그래서 마커 파일을 위로 훑어 찾고, 못 찾으면
    예전 동작으로 떨어진다.

    SUPERTONIC_PROJECT_ROOT 로 언제든 못박을 수 있다.
    """
    override = os.environ.get("SUPERTONIC_PROJECT_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    here = Path(__file__).resolve()
    for parent in here.parents:
        if any((parent / m).exists() for m in _ROOT_MARKERS):
            return parent
    return here.parents[2] if len(here.parents) > 2 else here.parent


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


@dataclass(frozen=True)
class Settings:
    project_root: Path
    onnx_dir: Path
    voice_styles_dir: Path
    voice_map_path: Path
    pronunciation_map_path: Path
    expression_tags_path: Path
    workspace_root: Path
    use_gpu_mode: str            # "auto" | "1" | "0" (true/false도 허용)
    default_speed: float
    default_total_step: int
    default_lang: str
    batch_chunk_size: int
    host: str
    port: int

    def resolve_use_gpu(self) -> bool:
        mode = self.use_gpu_mode.strip().lower()
        if mode in ("1", "true", "yes", "on"):
            return True
        if mode in ("0", "false", "no", "off"):
            return False
        try:
            import onnxruntime as ort
            return ort.get_device().upper() == "GPU"
        except Exception:
            return False


def load() -> Settings:
    root = _project_root()
    assets = _env_path("SUPERTONIC_ASSETS_DIR", root / "assets")
    # supertonic-3 레이아웃: assets/onnx/*.onnx + tts.json + unicode_indexer.json,
    # assets/voice_styles/*.json
    onnx_dir = assets / "onnx" if (assets / "onnx").exists() else assets
    return Settings(
        project_root=root,
        onnx_dir=onnx_dir,
        voice_styles_dir=assets / "voice_styles",
        voice_map_path=_env_path("SUPERTONIC_VOICE_MAP", root / "config" / "voice_map.yaml"),
        pronunciation_map_path=_env_path("SUPERTONIC_PRONUNCIATION_MAP", root / "config" / "pronunciation_map.yaml"),
        expression_tags_path=_env_path("SUPERTONIC_EXPRESSION_TAGS", root / "config" / "expression_tags.yaml"),
        workspace_root=_env_path("SUPERTONIC_WORKSPACE", root / "workspace"),
        use_gpu_mode=_env_str("SUPERTONIC_USE_GPU", "auto"),
        default_speed=float(_env_str("SUPERTONIC_DEFAULT_SPEED", "1.00")),
        default_total_step=_env_int("SUPERTONIC_TOTAL_STEP", 8),
        default_lang=_env_str("SUPERTONIC_DEFAULT_LANG", "ko"),
        batch_chunk_size=_env_int("SUPERTONIC_BATCH_CHUNK_SIZE", 4),
        host=_env_str("SUPERTONIC_HOST", "0.0.0.0"),
        port=_env_int("SUPERTONIC_PORT", 7878),
    )
