#!/usr/bin/env python3
"""
batch_fetcher.py
Run:
    python batch_fetcher.py
"""

import itertools
from pathlib import Path
import subprocess

# ----- import the function you already have -----
# (auto_exam_fetcher.py must be in the same folder or on PYTHONPATH)
from auto_exam_fetcher import fetch_and_process


# ===================== CONFIGURATION =====================
SUBJECTS = ["9618"]          # add / remove codes freely
YEARS    = [ "2023", "2024"]
SEASONS  = ["m","s", "w"]                        # s = summer, w = winter
VARIANTS = ["11", "12", "13", "21", "22", "23", "31", "32", "33","41", "42", "43"]

OUT_DIR  = "batch_output"
Path(OUT_DIR).mkdir(exist_ok=True)


# ===================== HELPER =============================
def _is_valid_pdf(url: str) -> bool:
    """HEAD request to see if URL points to a real PDF."""
    try:
        # wget --spider exits 0 only if file exists (HTTP 200)
        proc = subprocess.run(
            ["wget", "--spider", "-q", url],
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0
    except Exception:
        return False


# ===================== MAIN LOOP ==========================
def main():
    total = len(SUBJECTS) * len(YEARS) * len(SEASONS) * len(VARIANTS)
    counter = 0
    for subj, yr, ssn, var in itertools.product(SUBJECTS, YEARS, SEASONS, VARIANTS):
        counter += 1
        url = (
            f"https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/"
            f"{subj}_{ssn}{yr[-2:]}_qp_{var}.pdf"
        )
        print(f"[{counter:>4}/{total}] Checking {url}")
        if _is_valid_pdf(url):
            try:
                fetch_and_process(subj, yr, ssn, var, out_dir=OUT_DIR)
            except Exception as e:
                print(f"  !! Failed {subj} {yr} {ssn} {var} : {e}")
        else:
            print("  -- skipped (not found)")


if __name__ == "__main__":
    main()
