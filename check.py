with open("ENT.txt", "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")
print("\n--- FIRST 20 LINES ---")
for i, line in enumerate(lines[:20]):
    print(f"[{i}] {repr(line)}")