import asyncio
import logging
import threading
from typing import Callable, Generic, TypeVar

from src.utils import clean_memory

T = TypeVar("T")

_cache_registry: list["ModelCache"] = []


def bind_cache_loops(loop: asyncio.AbstractEventLoop) -> None:
    for cache in _cache_registry:
        cache._bind_loop(loop)


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
        self._timer_handle: asyncio.TimerHandle | None = None
        self._thread_timer: threading.Timer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        _cache_registry.append(self)

    def _bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

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
        if self._loop is not None:
            self._timer_handle = self._loop.call_later(self._ttl, self.evict)
        else:
            self._thread_timer = threading.Timer(self._ttl, self.evict)
            self._thread_timer.daemon = True
            self._thread_timer.start()

    def touch(self) -> None:
        with self._lock:
            if self._model is not None:
                self._reschedule()

    def _cancel_timer(self) -> None:
        if self._timer_handle is not None:
            self._timer_handle.cancel()
            self._timer_handle = None
        if self._thread_timer is not None:
            self._thread_timer.cancel()
            self._thread_timer = None


def get_loaded_models() -> list[dict]:
    """Retrieve details of all models currently loaded in memory caches."""
    loaded = []
    for cache in _cache_registry:
        if cache.current_key is not None:
            loaded.append(
                {
                    "model": cache.current_key,
                    "engine": cache._tag,
                    "ttl": cache._ttl,
                }
            )
    return loaded


def unload_models(model_id: str | None = None, unload_all: bool = False) -> list[dict]:
    """Unload specific or all models from memory caches."""
    import os

    unloaded = []
    for cache in _cache_registry:
        if cache.current_key is not None:
            key = cache.current_key
            tag = cache._tag

            should_unload = False
            if unload_all:
                should_unload = True
            elif model_id:
                basename = os.path.splitext(os.path.basename(key))[0]
                if (
                    model_id == key
                    or model_id == tag
                    or model_id == basename
                    or model_id in key
                ):
                    should_unload = True

            if should_unload:
                cache.evict()
                unloaded.append(
                    {
                        "model": key,
                        "engine": tag,
                    }
                )
    return unloaded

