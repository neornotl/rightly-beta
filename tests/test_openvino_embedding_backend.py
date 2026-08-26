from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from app.retrieval.hybrid_retriever import DenseIndex


class _FakeOpenVINOEncoder:
    def __init__(self, *args, **kwargs):
        self.args = args

    def encode(self, texts, **kwargs):
        return np.ones((len(texts), 384), dtype="float32")


def test_dense_index_prefers_openvino(monkeypatch):
    fake = types.ModuleType("app.retrieval.openvino_e5")
    fake.OpenVINOE5Encoder = _FakeOpenVINOEncoder
    monkeypatch.setitem(sys.modules, "app.retrieval.openvino_e5", fake)
    monkeypatch.setenv("RIGHTLY_EMBEDDING_BACKEND", "openvino")
    assert isinstance(DenseIndex()._load_model(), _FakeOpenVINOEncoder)


def test_openvino_explicit_mode_fails_closed(monkeypatch):
    fake = types.ModuleType("app.retrieval.openvino_e5")

    class Broken:
        def __init__(self, *args, **kwargs):
            raise FileNotFoundError("missing IR")

    fake.OpenVINOE5Encoder = Broken
    monkeypatch.setitem(sys.modules, "app.retrieval.openvino_e5", fake)
    monkeypatch.setenv("RIGHTLY_EMBEDDING_BACKEND", "openvino")
    with pytest.raises(RuntimeError, match="OpenVINO embedding backend unavailable"):
        DenseIndex()._load_model()


def test_invalid_embedding_backend_is_rejected(monkeypatch):
    monkeypatch.setenv("RIGHTLY_EMBEDDING_BACKEND", "magic")
    with pytest.raises(ValueError, match="auto, openvino, or pytorch"):
        DenseIndex()._load_model()
