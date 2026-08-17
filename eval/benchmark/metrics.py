"""
Metrics calculation for benchmark evaluation.
"""

import math
from collections import defaultdict
from typing import Dict, List


def recall_at_k(retrieved: List[str], relevant: List[str], k: int) -> float:
    """Recall@k for retrieval."""
    if not relevant:
        return 1.0 if not retrieved[:k] else 0.0
    retrieved_k = set(retrieved[:k])
    return len(retrieved_k & set(relevant)) / len(relevant)


def ndcg_at_k(retrieved: List[str], relevant: List[str], k: int) -> float:
    """nDCG@k for retrieval."""
    if not relevant:
        return 1.0

    dcg = 0.0
    for i, doc_id in enumerate(retrieved[:k]):
        if doc_id in relevant:
            dcg += 1.0 / math.log2(i + 2)  # i is 0-indexed

    ideal_dcg = sum(1.0 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return dcg / ideal_dcg if ideal_dcg > 0 else 0.0


def mrr(retrieved: List[str], relevant: List[str]) -> float:
    """Mean Reciprocal Rank."""
    for i, doc_id in enumerate(retrieved):
        if doc_id in relevant:
            return 1.0 / (i + 1)
    return 0.0


def accuracy(predictions: List[str], labels: List[str]) -> float:
    """Simple accuracy."""
    if not predictions:
        return 0.0
    return sum(p == label for p, label in zip(predictions, labels)) / len(predictions)


def precision_recall_f1(tp: int, fp: int, fn: int) -> Dict[str, float]:
    """Precision, Recall, F1 from counts."""
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return {"precision": prec, "recall": rec, "f1": f1}


def confusion_matrix(
    predictions: List[str], labels: List[str], classes: List[str]
) -> Dict[str, Dict[str, int]]:
    """Confusion matrix as nested dict."""
    matrix = {c: {c2: 0 for c2 in classes} for c in classes}
    for p, label in zip(predictions, labels):
        if label in matrix and p in matrix[label]:
            matrix[label][p] += 1
    return matrix


def latency_percentiles(latencies: List[float], percentiles: List[int] = None) -> Dict[str, float]:
    """Calculate latency percentiles."""
    if not latencies:
        return {}
    if percentiles is None:
        percentiles = [50, 90, 95, 99]
    sorted_lat = sorted(latencies)
    n = len(sorted_lat)
    result = {}
    for p in percentiles:
        idx = min(n - 1, int(n * p / 100))
        result[f"p{p}"] = sorted_lat[idx]
    result["max"] = sorted_lat[-1]
    result["mean"] = sum(sorted_lat) / n
    return result


def bootstrap_confidence_interval(
    values: List[float], n_bootstrap: int = 1000, confidence: float = 0.95
) -> Dict[str, float]:
    """Bootstrap confidence interval for mean."""
    import random

    if not values:
        return {"mean": 0, "ci_lower": 0, "ci_upper": 0}

    means = []
    n = len(values)
    for _ in range(n_bootstrap):
        sample = [random.choice(values) for _ in range(n)]
        means.append(sum(sample) / n)

    means.sort()
    alpha = (1 - confidence) / 2
    lower_idx = int(n_bootstrap * alpha)
    upper_idx = int(n_bootstrap * (1 - alpha))

    return {"mean": sum(values) / n, "ci_lower": means[lower_idx], "ci_upper": means[upper_idx]}


def aggregate_by_group(
    results: List[Dict], group_key: str, metric_keys: List[str]
) -> Dict[str, Dict[str, float]]:
    """Aggregate metrics by a grouping key."""
    groups = defaultdict(list)
    for r in results:
        key = r.get(group_key, "UNKNOWN")
        groups[key].append(r)

    aggregated = {}
    for key, group_results in groups.items():
        agg = {"count": len(group_results)}
        for mk in metric_keys:
            vals = [r[mk] for r in group_results if mk in r and r[mk] is not None]
            if vals:
                agg[f"{mk}_mean"] = sum(vals) / len(vals)
                agg[f"{mk}_p50"] = latency_percentiles(vals).get("p50", 0)
        aggregated[key] = agg
    return aggregated


def response_style_scores(answer_text: str) -> Dict[str, int]:
    """
    Score response style 1-5 based on observable criteria.
    This is a rule-based approximation; human audit needed for true scores.
    """
    scores = {}
    words = answer_text.split()

    # Brevity (1-5): shorter is better for voice
    if len(words) <= 50:
        scores["brevity"] = 5
    elif len(words) <= 100:
        scores["brevity"] = 4
    elif len(words) <= 200:
        scores["brevity"] = 3
    elif len(words) <= 400:
        scores["brevity"] = 2
    else:
        scores["brevity"] = 1

    # Stepwise structure (1-5): has numbered steps or clear transitions
    step_indicators = [
        "bước 1",
        "bước 2",
        "thứ nhất",
        "thứ hai",
        "tiếp theo",
        "sau đó",
        "cuối cùng",
    ]
    step_count = sum(1 for ind in step_indicators if ind in answer_text.lower())
    if step_count >= 3:
        scores["stepwise"] = 5
    elif step_count >= 1:
        scores["stepwise"] = 3
    else:
        scores["stepwise"] = 1

    # Legal jargon (1-5): fewer complex terms = better
    jargon_terms = [
        "theo quy định tại khoản",
        "theo điều",
        "theo điểm",
        "hiệu lực pháp luật",
        "cơ quan nhà nước có thẩm quyền",
    ]
    jargon_count = sum(1 for j in jargon_terms if j in answer_text.lower())
    if jargon_count == 0:
        scores["low_jargon"] = 5
    elif jargon_count <= 1:
        scores["low_jargon"] = 4
    elif jargon_count <= 2:
        scores["low_jargon"] = 3
    elif jargon_count <= 3:
        scores["low_jargon"] = 2
    else:
        scores["low_jargon"] = 1

    # Actionable next step (1-5)
    action_indicators = ["nộp", "làm", "đến", "liên hệ", "gọi", "tra cứu", "bước tiếp theo"]
    has_action = any(ind in answer_text.lower() for ind in action_indicators)
    scores["actionable"] = 5 if has_action else 1

    # Citation spoken naturally (1-5)
    cite_indicators = ["theo", "theo quy định", "theo luật", "theo nghị định"]
    has_cite = any(ind in answer_text.lower() for ind in cite_indicators)
    scores["spoken_citation"] = 5 if has_cite else 1

    # No fake empathy (1-5)
    fake_empathy = ["tôi hiểu", "tôi đồng cảm", "rất tiếc", "chia buồn", "an ủi"]
    has_fake = any(ind in answer_text.lower() for ind in fake_empathy)
    scores["no_fake_empathy"] = 1 if has_fake else 5

    # Does not pretend to be human (1-5)
    pretend_human = ["tôi nghĩ", "tôi tin", "theo tôi", "cảm giác của tôi"]
    has_pretend = any(ind in answer_text.lower() for ind in pretend_human)
    scores["not_pretend_human"] = 1 if has_pretend else 5

    return scores


def estimated_listening_time(answer_text: str, wpm: int = 150) -> float:
    """Estimate listening time in seconds (Vietnamese ~150 words/min)."""
    words = len(answer_text.split())
    return (words / wpm) * 60


__all__ = [
    "recall_at_k",
    "ndcg_at_k",
    "mrr",
    "accuracy",
    "precision_recall_f1",
    "confusion_matrix",
    "latency_percentiles",
    "bootstrap_confidence_interval",
    "aggregate_by_group",
    "response_style_scores",
    "estimated_listening_time",
]
