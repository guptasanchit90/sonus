import logging
import threading
from typing import Callable, Generic, TypeVar

from src.utils import clean_memory

T = TypeVar("T")


class ModelCache(Generic[T]):
    def __init__(
        self,
        ttl: int = 10,
        tag: str = "",
        on_evict: Callable[[], None] | None = None,
    ):
        self._ttl = ttl
        self._tag = tag
        self._logger = logging.getLogger(tag or "cache")
        self._on_evict = on_evict
        self._model: T | None = None
        self._key: str | None = None
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def get_or_load(self, key: str, loader: Callable[[], T]) -> T:
        with self._lock:
            if self._key != key:
                old_model = self._model
                old_key = self._key
                self._evict_unlocked()
                self._logger.info("Loading model '%s'", key)
                try:
                    model = loader()
                except Exception:
                    self._logger.error("Failed to load model '%s'; rolling back cache state", key)
                    self._model = old_model
                    self._key = old_key
                    if old_model is not None:
                        self._reschedule()
                    raise
                self._model = model
                self._key = key
            else:
                self._logger.debug("Using cached model '%s'", key)
            self._reschedule()
            assert self._model is not None
            return self._model

    @property
    def current(self) -> T | None:
        return self._model

    @property
    def current_key(self) -> str | None:
        return self._key

    def evict(self) -> None:
        with self._lock:
            self._evict_unlocked()

    def _evict_unlocked(self) -> None:
        if self._model is not None:
            self._logger.info("Evicting cached model '%s' after %ds idle", self._key, self._ttl)
            if self._on_evict:
                self._on_evict()
            del self._model
            self._model = None
            self._key = None
            self._cancel_timer()
            clean_memory()

    def _reschedule(self) -> None:
        self._cancel_timer()
        self._timer = threading.Timer(self._ttl, self.evict)
        self._timer.daemon = True
        self._timer.start()

    def touch(self) -> None:
        with self._lock:
            if self._model is not None:
                self._reschedule()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
