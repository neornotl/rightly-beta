"""Local OpenVINO encoder for multilingual-e5-small.

The installer exports the already-downloaded SentenceTransformers backbone to
OpenVINO IR once. Runtime inference is fully local and falls back at the caller
when OpenVINO or the IR is unavailable.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


class OpenVINOE5Encoder:
    def __init__(self, model_dir: str | Path, ir_path: str | Path, threads: int = 4):
        import openvino as ov
        from transformers import AutoTokenizer

        self.model_dir = Path(model_dir)
        self.ir_path = Path(ir_path)
        if not self.ir_path.is_file() or not self.ir_path.with_suffix(".bin").is_file():
            raise FileNotFoundError(f"OpenVINO E5 IR missing: {self.ir_path}")
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(self.model_dir), local_files_only=True
        )
        core = ov.Core()
        self.compiled = core.compile_model(
            core.read_model(str(self.ir_path)),
            "CPU",
            {
                "INFERENCE_NUM_THREADS": max(1, int(threads)),
                "PERFORMANCE_HINT": "LATENCY",
            },
        )
        self.request = self.compiled.create_infer_request()
        self.input_ids = self.compiled.input("input_ids")
        self.attention_mask = self.compiled.input("attention_mask")
        self.output = self.compiled.output(0)

    def encode(self, texts, *, normalize_embeddings=True, **_kwargs):
        encoded = self.tokenizer(
            list(texts), padding=True, truncation=True, return_tensors="np"
        )
        result = self.request.infer(
            {
                self.input_ids: encoded["input_ids"].astype("int64"),
                self.attention_mask: encoded["attention_mask"].astype("int64"),
            }
        )
        vectors = np.asarray(result[self.output], dtype="float32")
        if normalize_embeddings:
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            vectors = vectors / np.maximum(norms, 1e-12)
        return vectors.astype("float32", copy=False)


def export_openvino_ir(model_dir: str | Path, ir_path: str | Path) -> Path:
    """Export the cached E5 backbone with pooling + L2 normalization."""
    import openvino as ov
    import torch
    from sentence_transformers import SentenceTransformer

    model_dir = Path(model_dir)
    ir_path = Path(ir_path)
    ir_path.parent.mkdir(parents=True, exist_ok=True)
    sentence_model = SentenceTransformer(
        str(model_dir), local_files_only=True, device="cpu"
    )

    class Encoder(torch.nn.Module):
        def __init__(self, base):
            super().__init__()
            self.base = base

        def forward(self, input_ids, attention_mask):
            hidden = self.base(
                input_ids=input_ids, attention_mask=attention_mask, return_dict=False
            )[0]
            mask = attention_mask.unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            return torch.nn.functional.normalize(pooled, p=2, dim=1)

    sample = sentence_model.tokenizer(
        ["query: Rightly"], padding="max_length", truncation=True,
        max_length=16, return_tensors="pt"
    )
    converted = ov.convert_model(
        Encoder(sentence_model[0].auto_model).eval(),
        example_input=(sample["input_ids"], sample["attention_mask"]),
    )
    ov.save_model(converted, str(ir_path))
    return ir_path
