import json
import logging
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from app.core.models import CompanyInfo

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - Unix
    msvcrt = None


logger = logging.getLogger(__name__)

_CACHE_LOCKS: dict[str, threading.RLock] = {}
_CACHE_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve(strict=False))
    with _CACHE_LOCKS_GUARD:
        lock = _CACHE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _CACHE_LOCKS[key] = lock
        return lock


class CompanyInfoCache:
    """简单 JSON 缓存，避免重复查询同一企业。"""

    def __init__(self, cache_path: str | Path):
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.cache_path.with_name(f"{self.cache_path.name}.lock")
        self._thread_lock = _thread_lock_for(self.cache_path)
        self._data = self._load()

    def _load(self) -> dict:
        if not self.cache_path.exists():
            return {}
        raw_text = self.cache_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            logger.warning("company_cache_empty 缓存文件为空，将按空缓存处理 cache_path=%s", self.cache_path)
            return {}
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.warning(
                "company_cache_invalid 缓存文件不是合法 JSON，将按空缓存处理 cache_path=%s error=%s",
                self.cache_path,
                exc,
            )
            return {}
        if not isinstance(data, dict):
            logger.warning("company_cache_invalid_type 缓存内容不是对象，将按空缓存处理 cache_path=%s", self.cache_path)
            return {}
        return data

    def get(self, company_name: str) -> CompanyInfo | None:
        item = self._data.get(company_name)
        if not item:
            return None
        return CompanyInfo(**item)

    def set(self, company_name: str, info: CompanyInfo):
        with self._locked_file():
            data = self._load()
            data[company_name] = asdict(info)
            self._write_atomic(data)
            self._data = data

    @contextmanager
    def _locked_file(self):
        with self._thread_lock:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a+b") as lock_file:
                _lock_file(lock_file)
                try:
                    yield
                finally:
                    _unlock_file(lock_file)

    def _write_atomic(self, data: dict):
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        tmp_name = None
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.cache_path.name}.",
            suffix=".tmp",
            dir=self.cache_path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(payload)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_name, self.cache_path)
            tmp_name = None
        finally:
            if tmp_name and Path(tmp_name).exists():
                Path(tmp_name).unlink()


def _lock_file(lock_file):
    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write(b"\0")
        lock_file.flush()
        os.fsync(lock_file.fileno())
    lock_file.seek(0)
    if msvcrt is not None:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
    elif fcntl is not None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)


def _unlock_file(lock_file):
    lock_file.seek(0)
    if msvcrt is not None:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    elif fcntl is not None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
