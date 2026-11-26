"""A deterministic, dependency-free baseline embedder.

Feature hashing over words and character trigrams, with Arabic normalisation (diacritics, alef/yaa/taa-marbuta forms).
It is lexical: it finds shared words, not shared meaning, and it cannot match an Arabic query to English-only text.
It exists so retrieval runs offline and in CI, and as the baseline that a real multilingual model must beat
(see evals/retrieval.jsonl).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

_DIACRITICS = re.compile(r"[ً-ْٰـ]")  # tashkeel + superscript alef + tatweel
_TOKEN = re.compile(r"[\w؀-ۿ]+", re.UNICODE)


def normalize(text: str) -> str:
    t = _DIACRITICS.sub("", text.lower())
    t = re.sub("[إأآٱ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه")
    return t


class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _features(self, text: str) -> list[tuple[str, float]]:
        feats: list[tuple[str, float]] = []
        for word in _TOKEN.findall(normalize(text)):
            if len(word) < 2:
                continue
            feats.append(("w:" + word, 1.0))
            padded = f"#{word}#"
            for i in range(len(padded) - 2):
                feats.append(("c:" + padded[i : i + 3], 0.5))
        return feats

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feat, weight in self._features(text):
            h = int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "big")
            sign = 1.0 if (h >> 63) & 1 else -1.0
            vec[h % self.dim] += sign * weight
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
