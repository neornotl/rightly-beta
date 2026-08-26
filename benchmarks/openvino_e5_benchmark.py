"""Offline OpenVINO benchmark for Rightly's cached E5-small query encoder.

This is deliberately outside the production runtime.  It reads the existing
Hugging Face snapshot and corpus cache, never calls the Hub, and writes only
benchmark artifacts below ``--out-dir``.  The exporter uses the same BERT
backbone, masked mean pooling and L2 normalization as SentenceTransformers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import time
from pathlib import Path

import numpy as np


QUERIES = [
    "query: quy dinh khi vuot den do",
    "query: thu tuc cap lai can cuoc cong dan",
    "query: quyen loi bao hiem y te",
    "query: dieu kien dang ky khai sinh qua han",
    "query: xu phat vi pham giao thong",
]


def _wrapper(torch, backbone):
    class Encoder(torch.nn.Module):
        def __init__(self, base):
            super().__init__()
            self.base = base

        def forward(self, input_ids, attention_mask):
            hidden = self.base(
                input_ids=input_ids,
                attention_mask=attention_mask,
                return_dict=False,
            )[0]
            mask = attention_mask.unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            return torch.nn.functional.normalize(pooled, p=2, dim=1)

    return Encoder(backbone).eval()


def _export_ir(model_dir: Path, xml_path: Path):
    import openvino as ov
    import torch
    from sentence_transformers import SentenceTransformer

    sentence_model = SentenceTransformer(
        str(model_dir), local_files_only=True, device="cpu"
    )
    tokenizer = sentence_model.tokenizer
    # A short example is enough because the inputs are dynamic in both axes.
    encoded = tokenizer(
        ["query: benchmark"],
        padding="max_length",
        truncation=True,
        max_length=16,
        return_tensors="pt",
    )
    wrapped = _wrapper(torch, sentence_model[0].auto_model)
    ov_model = ov.convert_model(
        wrapped,
        example_input=(encoded["input_ids"], encoded["attention_mask"]),
    )
    ov.save_model(ov_model, str(xml_path))
    return sentence_model


def _load_sentence_model(model_dir: Path):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(str(model_dir), local_files_only=True, device="cpu")


def _configure_torch(threads: int) -> dict[str, int]:
    import torch

    torch.set_num_threads(int(threads))
    interop = max(1, min(2, int(threads) // 2))
    try:
        torch.set_num_interop_threads(interop)
    except RuntimeError:
        # PyTorch refuses changing inter-op threads after work has started.
        pass
    return {
        "intra_op_threads": int(torch.get_num_threads()),
        "interop_threads": int(torch.get_num_interop_threads()),
    }


def _tokenize(sentence_model, texts):
    preprocess = getattr(sentence_model, "preprocess", None)
    if preprocess is not None:
        return preprocess(texts)
    return sentence_model.tokenize(texts)


def _timed(values):
    values = [float(v) for v in values]
    return {
        "runs": len(values),
        "warmup_excluded": 1,
        "mean_ms": round(statistics.mean(values[1:]), 3),
        "median_ms": round(statistics.median(values[1:]), 3),
        "p95_ms": round(float(np.percentile(values[1:], 95)), 3),
        "min_ms": round(min(values[1:]), 3),
        "max_ms": round(max(values[1:]), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path(".benchmarks/e5"))
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--runs", type=int, default=15)
    args = parser.parse_args()
    if args.runs < 3:
        raise SystemExit("--runs must be >= 3")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    xml_path = args.out_dir / "e5_small_query_encoder.xml"
    json_path = args.out_dir / "openvino_e5_results.json"
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    import openvino as ov

    torch_settings = _configure_torch(args.threads)
    core = ov.Core()
    devices = list(core.available_devices)
    device = "CPU"
    if device not in devices:
        raise RuntimeError(f"OpenVINO CPU device unavailable: {devices}")
    compile_config = {
        "INFERENCE_NUM_THREADS": int(args.threads),
        "PERFORMANCE_HINT": "LATENCY",
    }

    if xml_path.exists() and (xml_path.with_suffix(".bin")).exists():
        sentence_model = _load_sentence_model(args.model_dir)
        export_method = "cached_openvino_ir"
    else:
        sentence_model = _export_ir(args.model_dir, xml_path)
        export_method = "ov.convert_model_from_cached_pytorch"
    compile_started = time.perf_counter()
    compiled = core.compile_model(core.read_model(str(xml_path)), device, compile_config)
    compile_ms = (time.perf_counter() - compile_started) * 1000
    infer = compiled.create_infer_request()
    input_ids = compiled.input("input_ids")
    attention_mask = compiled.input("attention_mask")

    # Reference embeddings and tokenization are computed once per query.
    reference = sentence_model.encode(
        QUERIES, normalize_embeddings=True, show_progress_bar=False
    ).astype("float32")
    tokenized = _tokenize(sentence_model, QUERIES)
    ids = tokenized["input_ids"].detach().cpu().numpy().astype("int64")
    masks = tokenized["attention_mask"].detach().cpu().numpy().astype("int64")

    # Warmup + one-query calls mirror the production query path.  The
    # SentenceTransformers and OpenVINO measurements both include tokenization
    # so the comparison does not accidentally credit OpenVINO for omitted work.
    sequence = [QUERIES[i % len(QUERIES)] for i in range(args.runs)]
    series = []
    all_st_measured = []
    all_ov_measured = []
    for series_number in range(1, 4):
        sentence_model.encode([sequence[0]], normalize_embeddings=True, show_progress_bar=False)
        st_times = []
        for query in sequence:
            started = time.perf_counter()
            sentence_model.encode([query], normalize_embeddings=True, show_progress_bar=False)
            st_times.append((time.perf_counter() - started) * 1000)

        first_tokens = _tokenize(sentence_model, [sequence[0]])
        first_ids = first_tokens["input_ids"].detach().cpu().numpy().astype("int64")
        first_masks = first_tokens["attention_mask"].detach().cpu().numpy().astype("int64")
        infer.infer({input_ids: first_ids, attention_mask: first_masks})
        ov_times = []
        for query in sequence:
            started = time.perf_counter()
            tokens = _tokenize(sentence_model, [query])
            query_ids = tokens["input_ids"].detach().cpu().numpy().astype("int64")
            query_masks = tokens["attention_mask"].detach().cpu().numpy().astype("int64")
            infer.infer({input_ids: query_ids, attention_mask: query_masks})
            ov_times.append((time.perf_counter() - started) * 1000)
        all_st_measured.extend(st_times[1:])
        all_ov_measured.extend(ov_times[1:])
        series.append({
            "series": series_number,
            "sentence_transformers": _timed(st_times),
            "openvino_end_to_end": _timed(ov_times),
            "speedup_end_to_end": round(statistics.mean(st_times[1:]) / statistics.mean(ov_times[1:]), 3),
        })

    # Agreement across all fixed queries, plus top-k agreement against the
    # existing real corpus cache.  The cache is read-only.
    all_ov = []
    for i in range(len(QUERIES)):
        all_ov.append(np.asarray(infer.infer({input_ids: ids[i:i+1], attention_mask: masks[i:i+1]})[compiled.output(0)][0], dtype="float32"))
    all_ov = np.asarray(all_ov)
    cosines = np.sum(reference * all_ov, axis=1)
    corpus = np.load(args.cache, allow_pickle=True)
    matrix = corpus["embeddings"]
    corpus_ids = corpus["ids"]
    topk_agreement = []
    for ref_vec, ov_vec in zip(reference, all_ov):
        ref_top = np.argsort(-(matrix @ ref_vec))[:10]
        ov_top = np.argsort(-(matrix @ ov_vec))[:10]
        topk_agreement.append(len(set(ref_top.tolist()) & set(ov_top.tolist())) / 10)

    model_hash = hashlib.sha256((args.model_dir / "model.safetensors").read_bytes()).hexdigest()
    result = {
        "record_type": "post_submission_openvino_benchmark",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "post_submission": True,
        "offline_only": True,
        "python": platform.python_version(),
        "openvino": ov.__version__,
        "available_devices": devices,
        "device_benchmarked": device,
        "compile_config": compile_config,
        "torch_settings": torch_settings,
        "model": "intfloat/multilingual-e5-small",
        "model_dir": "<HF_CACHE>/models--intfloat--multilingual-e5-small/snapshots/<snapshot>",
        "model_safetensors_sha256": model_hash,
        "embedding_dim": int(reference.shape[1]),
        "corpus_rows": int(matrix.shape[0]),
        "export_method": export_method,
        "exported_ir": str(xml_path),
        "queries": QUERIES,
        "compile_ms": round(compile_ms, 3),
        "series": series,
        "openvino_measured_ms_all_series": {
            "runs": len(all_ov_measured), "warmups_excluded": 3,
            "mean_ms": round(statistics.mean(all_ov_measured), 3),
            "median_ms": round(statistics.median(all_ov_measured), 3),
            "p95_ms": round(float(np.percentile(all_ov_measured, 95)), 3),
        },
        "sentence_transformers_measured_ms_all_series": {
            "runs": len(all_st_measured), "warmups_excluded": 3,
            "mean_ms": round(statistics.mean(all_st_measured), 3),
            "median_ms": round(statistics.median(all_st_measured), 3),
            "p95_ms": round(float(np.percentile(all_st_measured, 95)), 3),
        },
        "speedup_end_to_end_series_mean": round(statistics.mean([row["speedup_end_to_end"] for row in series]), 3),
        "speedup_end_to_end_series_median": round(statistics.median([row["speedup_end_to_end"] for row in series]), 3),
        "speedup_end_to_end_series_min": round(min(row["speedup_end_to_end"] for row in series), 3),
        "speedup_end_to_end_series_max": round(max(row["speedup_end_to_end"] for row in series), 3),
        "embedding_cosine_min": round(float(cosines.min()), 8),
        "embedding_cosine_mean": round(float(cosines.mean()), 8),
        "embedding_cosine_max": round(float(cosines.max()), 8),
        "top10_overlap_min": round(float(min(topk_agreement)), 4),
        "top10_overlap_mean": round(float(statistics.mean(topk_agreement)), 4),
        "top10_overlap_per_query": topk_agreement,
        "top1_reference": str(corpus_ids[np.argmax(matrix @ reference[0])]),
        "top1_openvino": str(corpus_ids[np.argmax(matrix @ all_ov[0])]),
        "limitations": [
            "CPU-only benchmark; no GPU/NPU claim.",
            "Export reads the existing local model snapshot and does not prove production integration.",
            "No accuracy ground-truth benchmark; cosine/top-k checks only validate export equivalence.",
        ],
    }
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
