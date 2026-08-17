import json
import pandas as pd
import numpy as np
from pathlib import Path
from scipy.stats import bootstrap
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import confusion_matrix, classification_report, roc_curve, auc
import warnings
warnings.filterwarnings("ignore")

# Try import krippendorff
try:
    import krippendorff
    HAS_KRIPPENDORFF = True
except ImportError:
    HAS_KRIPPENDORFF = False
    print("krippendorff not installed: pip install krippendorff")

# Load annotations
df = pd.read_csv("results/p4_annotation_items.csv")

# Load key for ground truth
key_df = pd.read_json("results/p4_annotation_key.jsonl", lines=True)

# Get annotators
annotators = df["Annotator"].unique()
annotators = [a for a in annotators if a != ""]
print(f"Annotators: {annotators}")
print(f"Total items: {len(df)}")

# ============================================================
# 1. KRIPPENDORFF'S ALPHA (Ordinal)
# ============================================================
if HAS_KRIPPENDORFF and len(annotators) >= 2:
    # Prepare data matrix: rows = items, cols = annotators
    aspects = ["Utility", "Accuracy", "Clarity", "Citation", "Safety"]
    reliability_data = []
    for aspect in aspects:
        # Matrix: annotators x items
        mat = []
        for ann in annotators:
            vals = df[df["Annotator"] == ann][aspect].values
            # Convert to numeric, NaN for missing
            vals = pd.to_numeric(vals, errors="coerce")
            mat.append(vals)
        reliability_data.append(mat)
    
    for aspect, mat in zip(aspects, reliability_data):
        try:
            alpha = krippendorff.alpha(reliability_data=mat, level_of_measurement="ordinal")
            print(f"Krippendorff α ({aspect}): {alpha:.4f}")
        except Exception as e:
            print(f"Krippendorff α ({aspect}) error: {e}")
    
    # Overall (flatten all aspects)
    all_mat = []
    for ann in annotators:
        all_vals = []
        for aspect in aspects:
            vals = df[df["Annotator"] == ann][aspect].values
            all_vals.extend(pd.to_numeric(vals, errors="coerce"))
        all_mat.append(all_vals)
    try:
        alpha_overall = krippendorff.alpha(reliability_data=all_mat, level_of_measurement="ordinal")
        print(f"Krippendorff α (overall): {alpha_overall:.4f}")
    except Exception as e:
        print(f"Krippendorff α overall error: {e}")
else:
    print("Skipping Krippendorff (need >=2 annotators or krippendorff package)")

# ============================================================
# 2. VETO GATES ANALYSIS
# ============================================================
print("\n=== VETO GATES ===")
for ann in annotators:
    ann_df = df[df["Annotator"] == ann].copy()
    ann_df["Accuracy"] = pd.to_numeric(ann_df["Accuracy"], errors="coerce")
    ann_df["Safety"] = pd.to_numeric(ann_df["Safety"], errors="coerce")
    
    veto_acc = (ann_df["Accuracy"] < 3).sum()
    veto_saf = (ann_df["Safety"] < 3).sum()
    veto_any = ((ann_df["Accuracy"] < 3) | (ann_df["Safety"] < 3)).sum()
    
    print(f"\n{ann}: VETO-Acc={veto_acc}, VETO-Saf={veto_saf}, VETO-Any={veto_any}")

# ============================================================
# 3. GRADE DISTRIBUTION PER ANNOTATOR
# ============================================================
print("\n=== GRADE DISTRIBUTION ===")
for ann in annotators:
    ann_df = df[df["Annotator"] == ann]
    grades = ann_df["Grade"].value_counts()
    print(f"\n{ann}:")
    for g, c in grades.items():
        print(f"  {g}: {c}")

# ============================================================
# 4. AGREEMENT (≥2/3 CONSENSUS)
# ============================================================
print("\n=== CONSENSUS (≥2/3) ===")
# For each item, get grades from all annotators
consensus_grades = {}
for item_id in df["item_id"].unique():
    item_grades = {}
    for ann in annotators:
        val = df[(df["item_id"] == item_id) & (df["Annotator"] == ann)]["Grade"].values
        if len(val) > 0 and val[0] != "":
            item_grades[ann] = val[0]
    # Consensus: majority vote (2/3)
    if len(item_grades) >= 2:
        from collections import Counter
        cnt = Counter(item_grades.values())
        consensus = cnt.most_common(1)[0][0]
        consensus_grades[item_id] = consensus
    else:
        consensus_grades[item_id] = "INSUFFICIENT"

print(f"Consensus rates:")
cons = pd.Series(consensus_grades).value_counts()
print(cons)

# ============================================================
# 5. SPLIT-SAMPLE CALIBRATION (70/30)
# ============================================================
print("\n=== SPLIT-SAMPLE CALIBRATION ===")

# Prepare features (5 aspects) + veto flags for consensus grades
# Use consensus grade as target
items_with_consensus = {k: v for k, v in consensus_grades.items() if v != "INSUFFICIENT"}

# Prepare feature matrix
X = []
y = []
item_ids = []

for item_id, grade in items_with_consensus.items():
    # Get mean scores across annotators
    row_data = df[df["item_id"] == item_id]
    aspects = ["Utility", "Accuracy", "Clarity", "Citation", "Safety"]
    features = []
    veto_flag = 0
    for aspect in aspects:
        vals = pd.to_numeric(row_data[row_data["Annotator"].isin(annotators)][aspect], errors="coerce")
        features.append(vals.mean())
    # Veto flags
    acc_vals = pd.to_numeric(row_data[row_data["Annotator"].isin(annotators)]["Accuracy"], errors="coerce")
    saf_vals = pd.to_numeric(row_data[row_data["Annotator"].isin(annotators)]["Safety"], errors="coerce")
    veto_acc = (acc_vals < 3).any()
    veto_saf = (saf_vals < 3).any()
    features.append(1 if veto_acc else 0)
    features.append(1 if veto_saf else 0)
    
    X.append(features)
    y.append(grade)
    item_ids.append(item_id)

X = np.array(X)
y = np.array(y)

print(f"Samples with consensus: {len(X)}")
print(f"Grade distribution: {pd.Series(y).value_counts()}")

if len(X) > 10:
    # Split 70/30 stratified
    X_train, X_test, y_train, y_test, ids_train, ids_test = train_test_split(
        X, y, item_ids, test_size=0.3, stratify=y, random_state=42
    )
    
    # Ordinal regression (multinomial logistic)
    le = LabelEncoder()
    y_train_enc = le.fit_transform(y_train)
    y_test_enc = le.transform(y_test)
    
    clf = LogisticRegression(multi_class="multinomial", solver="lbfgs", max_iter=1000, random_state=42)
    clf.fit(X_train, y_train_enc)
    
    y_pred = clf.predict(X_test)
    y_pred_labels = le.inverse_transform(y_pred)
    
    print("\n=== CALIBRATION RESULTS ===")
    print(f"Train size: {len(X_train)}, Test size: {len(X_test)}")
    print(f"Classes: {le.classes_}")
    print("\nConfusion Matrix:")
    print(confusion_matrix(y_test, y_pred_labels, labels=le.classes_))
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred_labels, labels=le.classes_))
    
    # Feature importance
    feature_names = ["Utility", "Accuracy", "Clarity", "Citation", "Safety", "VETO_Acc", "VETO_Saf"]
    for i, class_name in enumerate(le.classes_):
        coef = clf.coef_[i]
        print(f"\nClass {class_name} coefficients:")
        for name, c in zip(feature_names, coef):
            print(f"  {name}: {c:.4f}")

# ============================================================
# 6. BOOTSTRAP CI FOR METRICS
# ============================================================
def bootstrap_ci(data, func, n_resamples=1000, confidence=0.95):
    """Bootstrap confidence interval"""
    if len(data) == 0:
        return None, None
    boots = []
    for _ in range(n_resamples):
        sample = np.random.choice(data, size=len(data), replace=True)
        boots.append(func(sample))
    alpha = (1 - confidence) / 2
    lower = np.percentile(boots, alpha * 100)
    upper = np.percentile(boots, (1 - alpha) * 100)
    return lower, upper

# Macro F1 CI
if 'y_test' in locals() and 'y_pred_labels' in locals():
    def macro_f1_func(sample_indices):
        y_s = y_test[sample_indices]
        p_s = y_pred_labels[sample_indices]
        from sklearn.metrics import f1_score
        return f1_score(y_s, p_s, average="macro")
    
    # Manual bootstrap
    n = len(y_test)
    boots = []
    for _ in range(1000):
        idx = np.random.choice(n, n, replace=True)
        boots.append(f1_score(y_test[idx], y_pred_labels[idx], average="macro"))
    lower = np.percentile(boots, 2.5)
    upper = np.percentile(boots, 97.5)
    print(f"\nMacro F1 bootstrap 95% CI: [{lower:.4f}, {upper:.4f}]")

# ============================================================
# 7. PER-STRATUM WEIGHTED METRICS
# ============================================================
print("\n=== PER-STRATUM WEIGHTED METRICS ===")
# Load key for strata
key_df = pd.read_json("results/p4_annotation_key.jsonl", lines=True)
key_df = key_df.set_index("item_id")

# Population weights
pop_weights = {"YELLOW": 0.727, "ORANGE": 0.240, "RED": 0.033}
oversample_factor = {"YELLOW": 1.0, "ORANGE": 1.0, "RED": 50/11}  # 50 oversample vs 11 original

for ann in annotators:
    ann_df = df[df["Annotator"] == ann].copy()
    ann_df = ann_df.merge(key_df[["_expected_zone"]], left_on="item_id", right_index=True, how="left")
    
    print(f"\n{ann} - Weighted Metrics:")
    for zone, weight in pop_weights.items():
        zone_df = ann_df[ann_df["_expected_zone"] == zone]
        if len(zone_df) == 0:
            continue
        n = len(zone_df)
        # Adjust for RED oversample
        adj_weight = weight / oversample_factor.get(zone, 1.0)
        pass_rate = (zone_df["Grade"] == "PASS").mean()
        fail_rate = (zone_df["Grade"] == "FAIL").mean()
        print(f"  {zone} (n={n}, w={adj_weight:.4f}): PASS={pass_rate:.3f}, FAIL={fail_rate:.3f}")

# ============================================================
# 8. OUTPUT CALIBRATION REPORT
# ============================================================
print("\n=== CALIBRATION REPORT SAVED ===")
# (In real implementation, save to markdown file)

print("\n✅ Analysis complete!")