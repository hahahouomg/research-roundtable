def recall_at_3(ranking, relevant):
    return len(set(ranking[:3]) & relevant) / len(relevant)


relevant = {"A", "C"}
baseline = ["B", "A", "C"]
candidate = ["C", "B", "D"]

print(f"baseline={recall_at_3(baseline, relevant):.2f}")
print(f"candidate={recall_at_3(candidate, relevant):.2f}")
