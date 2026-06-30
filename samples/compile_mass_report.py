#!/usr/bin/env python3
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "samples" / "mass_corpus"
LOG_FILE = CORPUS / "results.jsonl"
REPORT_FILE = CORPUS / "DISCRIMINATION_REPORT.md"

def main():
    if not LOG_FILE.exists():
        print("No results.jsonl found.")
        return
        
    results = []
    with open(LOG_FILE, "r") as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
                
    # Sort by category, then by file name
    results.sort(key=lambda x: (x["category"], x["file"]))
    
    with open(REPORT_FILE, "w") as f:
        f.write("# Satyum Mass Discrimination Report\n\n")
        f.write(f"Total Files Tested: {len(results)}\n\n")
        f.write("| # | File | Category | Genuine | Verdict | Score | Key Signal |\n")
        f.write("|---|------|----------|---------|---------|-------|------------|\n")
        
        for i, r in enumerate(results, 1):
            score_str = f"{r['score']:.1f}" if r['score'] is not None else "N/A"
            f.write(f"| {i} | `{r['file']}` | {r['category']} | {r['is_genuine']} | {r['verdict']} | {score_str} | `{r['key_signal']}` |\n")
            
    print(f"Report compiled: {REPORT_FILE}")

if __name__ == "__main__":
    main()
