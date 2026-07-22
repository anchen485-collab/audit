import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env_file(path: str | Path | None = None) -> dict[str, str]:
    """读取 .env 文件；已有系统环境变量不覆盖，方便线上部署注入真实 key。"""
    env_path = Path(path) if path else PROJECT_ROOT / ".env"
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
        os.environ.setdefault(key, value)
    return values


def get_storage_dir() -> Path:
    """读取存储目录；测试时可以通过环境变量覆盖。"""
    load_env_file()
    storage_dir = os.getenv("AUDIT_STORAGE_DIR") or "storage"
    return Path(storage_dir).resolve()


def ensure_storage_dirs() -> dict[str, Path]:
    """创建上传、输出、缓存目录，并返回这些路径。"""
    storage_dir = get_storage_dir()
    paths = {
        "root": storage_dir,
        "uploads": storage_dir / "uploads",
        "outputs": storage_dir / "outputs",
        "cache": storage_dir / "cache",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def get_category_rules_json_path() -> Path:
    """读取分类规则 JSON 路径；默认放在 storage 根目录下。"""
    load_env_file()
    configured_path = os.getenv("CATEGORY_RULES_JSON_PATH")
    if configured_path:
        return Path(configured_path).resolve()
    return (get_storage_dir() / "category_rules.json").resolve()


def get_category_rules_excel_path() -> Path | None:
    """读取分类表 Excel 源文件路径；为空时表示不自动生成 JSON。"""
    load_env_file()
    configured_path = os.getenv("CATEGORY_RULES_EXCEL_PATH")
    if not configured_path:
        return None
    return Path(configured_path).resolve()
