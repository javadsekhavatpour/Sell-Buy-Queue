"""Test Phase 2.1+ signal overlay patches in web_dashboard_adaptive.py"""
import sys, os, py_compile
from pathlib import Path

BASE = Path("/home/z/my-project/download/TSE_Screener")
os.chdir(BASE); sys.path.insert(0, str(BASE))

print("=== 1. SYNTAX ===")
py_compile.compile("web_dashboard_adaptive.py", doraise=True)
print("  OK syntax")

import web_dashboard_adaptive as ada
html = ada.HTML_PAGE_ADAPTIVE

print("\n=== 2. ALL 6 HTML PATCHES ===")
checks = [
    ("cell colspan=5", 'colspan="5" style="color:#ccc"' in html),
    ("header colspan=5", 'colspan="5" style="background:#fdecea' in html),
    ("hint adaptive", "\u0622\u0628\u06cc=\u062a\u0637\u0628\u06cc\u0642\u06cc" in html),
    ("scoreHist array", "let scoreHist = [];" in html),
    ("pushScore function", "function pushScore(d)" in html),
    ("chart SIG_TH", "const SIG_TH = 50;" in html),
    ("sigMarkers loop", "for (const s of scoreHist)" in html),
    ("sigLegend text", "\u0633\u06cc\u06af\u0646\u0627\u0644\u200c\u0647\u0627 \u0631\u0648\u06cc \u0646\u0645\u0648\u062f\u0627\u0631" in html),
    ("tick hook pushScore", "pushScore(d); renderChart(d);" in html),
    ("critical polygon (star)", "\\u2605 critical" in html or "\u2605 critical" in html),
    ("sell marker (down triangle)", "\\u25bc sell" in html or "\u25bc sell" in html),
    ("buy marker (up triangle)", "\\u25b2 buy" in html or "\u25b2 buy" in html),
    ("no mojibake", "\u00d8\u00a8\u00d8" not in html),  # no Latin-1 mojibake of Persian
]
allok = True
for label, ok in checks:
    print(f"  {'OK' if ok else 'FAIL'} {label}")
    if not ok: allok = False

print("\n=== 3. NO CORRUPTED TEXT ===")
# Check no mojibake patterns remain
mojibake_markers = ["\u00d8\u00a8\u00d8\u00ad", "\u00d9\u0081\u00d8\u00b1", "\u00d8\u00b3\u00db"]
for mm in mojibake_markers:
    if mm in html:
        print(f"  FAIL: mojibake found: {repr(mm)}")
        allok = False
if allok:
    print("  OK no mojibake detected")

print(f"\n{'ALL TESTS PASSED' if allok else 'SOME TESTS FAILED'}")
