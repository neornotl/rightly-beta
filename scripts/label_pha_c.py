import json

rows = [json.loads(l) for l in open("results/pha_c_sample100.jsonl", encoding="utf-8")]

manual = {}  # idx -> (A=gold noisy/unjudgeable, B=retrieval weak, C=gold wrong/mismatch)
manual.update({i: "A" for i in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 33, 34, 35, 36, 38, 39, 43, 44, 46, 47, 48, 50, 51, 53, 55, 56, 57, 58, 59, 60, 62, 64, 66, 70, 71, 72, 74, 76, 77, 79, 80, 83, 84, 85, 88, 89, 90, 92, 93, 95, 96, 97, 98]})
manual.update({i: "B" for i in [27, 32, 37, 40, 42, 45, 49, 52, 54, 61, 67, 69, 73, 75, 81, 82, 86, 91, 94, 99]})
manual.update({i: "C" for i in [12, 41, 63, 68, 78, 87]})

for i, m in enumerate(rows):
    m["label"] = manual.get(i, "A")
    m["label_note"] = "A: gold khong xac dinh duoc chu de / cau hoi bi pha (khong the kiem dinh)" if manual.get(i) == "A" else ("B: gold dung chu de, retrieval kem (co the cai thien)" if manual.get(i) == "B" else "C: gold sai quy tac / duong dan khong hop")

label_counts = {}
label_tot_ov = {}
for m in rows:
    label_counts[m["label"]] = label_counts.get(m["label"], 0) + 1
    label_tot_ov[m["label"]] = label_tot_ov.get(m["label"], 0) + m["ov"]

with open("results/pha_c_labeled100.jsonl", "w", encoding="utf-8") as f:
    for m in rows:
        f.write(json.dumps(m, ensure_ascii=False) + "\n")

print("labels:", label_counts)
for k in sorted(label_tot_ov):
    print("  avg ov", k, round(label_tot_ov[k] / label_counts[k], 1))