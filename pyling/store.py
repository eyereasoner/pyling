"""Fact stores used by the Python Eyeling reasoner."""
from __future__ import annotations

import os
import pickle
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable, Iterator, Optional

from .terms import Term, Triple


class MemoryFactStore:
    def __init__(self) -> None:
        self._facts: dict[Triple, int] = {}

    async def add(self, triple: Triple, kind: str = "explicit") -> bool:
        bit = 1 if kind == "explicit" else 2
        old = self._facts.get(triple, 0)
        self._facts[triple] = old | bit
        return old == 0

    async def has(self, triple: Triple) -> bool:
        return triple in self._facts

    async def kind_of(self, triple: Triple) -> int:
        return self._facts.get(triple, 0)

    async def match(self, s: Term | None = None, p: Term | None = None, o: Term | None = None) -> AsyncIterator[Triple]:
        for tr in list(self._facts):
            if s is not None and tr.s != s:
                continue
            if p is not None and tr.p != p:
                continue
            if o is not None and tr.o != o:
                continue
            yield tr

    async def batch_add(self, triples: Iterable[Triple], kind: str = "explicit") -> int:
        n = 0
        for tr in triples:
            if await self.add(tr, kind):
                n += 1
        return n

    async def clear(self) -> None:
        self._facts.clear()

    async def close(self) -> None:
        return None

    @property
    def triples(self) -> list[Triple]:
        return list(self._facts)


class PersistentFactStore(MemoryFactStore):
    def __init__(self, path: str, name: str = "default", clear: bool = False) -> None:
        super().__init__()
        self.path = os.path.abspath(path)
        self.name = name
        os.makedirs(self.path, exist_ok=True)
        self.file_path = os.path.join(self.path, f"{name}.pickle")
        if clear:
            try:
                os.remove(self.file_path)
            except FileNotFoundError:
                pass
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "rb") as f:
                    self._facts = pickle.load(f)
            except Exception:
                self._facts = {}

    async def close(self) -> None:
        os.makedirs(self.path, exist_ok=True)
        with open(self.file_path, "wb") as f:
            pickle.dump(self._facts, f)


def create_fact_store(options: str | dict | None = None):
    if options is None or options == "memory":
        return MemoryFactStore()
    if isinstance(options, str):
        return PersistentFactStore(os.getcwd(), options)
    typ = options.get("type") or options.get("backend") or ("persistent" if options.get("name") else "memory")
    if typ == "memory":
        return MemoryFactStore()
    name = options.get("name") or "default"
    path = options.get("path") or options.get("storePath") or os.getcwd()
    return PersistentFactStore(path, name, clear=bool(options.get("clear")))
