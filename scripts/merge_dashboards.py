#!/usr/bin/env python3
"""ادغام web_dashboard_live.py و web_dashboard_adaptive.py در یک فایل.

خروجی: web_dashboard_adaptive.py که خودکفاست (دیگر web_dashboard_live را import نمی‌کند).
"""
import re
from pathlib import Path

PROJ = Path("/home/z/my-project/download/TSE_Screener")
live_path = PROJ / "web_dashboard_live.py"
adapt_path = PROJ / "web_dashboard_adaptive.py"
out_path = PROJ / "web_dashboard_adaptive.py"  # overwrite

live = live_path.read_text(encoding="utf-8")
adapt = adapt_path.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# ۱) استخراج کد کتابخانه‌ای از web_dashboard_live.py
# ---------------------------------------------------------------------------
# بخش اول: همه‌چیز قبل از MONITOR (imports، helpers، LiveMonitor)
marker = "MONITOR: LiveMonitor | None = None"
idx = live.index(marker)
lib_code = live[:idx]
# حذف کامنت‌های «سرور Flask» در انتهای lib_code
lib_code = lib_code.rsplit("# ---------------------------------------------------------------------------\n# سرور Flask\n# ---------------------------------------------------------------------------\n", 1)[0]

# بخش دوم: HTML_PAGE (قالب HTML بزرگ) — از "HTML_PAGE =" تا قبل از "def main()"
html_start = live.index('HTML_PAGE = ')
html_end = live.index("def main():")
html_page_code = live[html_start:html_end].rstrip() + "\n"

# ترکیب کتابخانه: lib_code + HTML_PAGE
lib_code = lib_code.rstrip() + "\n\n\n" + html_page_code

# ---------------------------------------------------------------------------
# ۲) استخراج توابع range_rules از web_dashboard_live.py
# ---------------------------------------------------------------------------
# _build_range_rules_html: از def تا def main()
m_start = live.index("def _build_range_rules_html(rules: dict) -> str:")
m_end = live.index("def main():")
build_range_html_func = live[m_start:m_end].rstrip() + "\n"

# range_rules_editor body (بدون @app.route decorator)
editor_start = live.index("@app.route(\"/range-rules\")\ndef range_rules_editor():")
editor_end = live.index("@app.route(\"/range-rules/save\"")
editor_func = live[editor_start:editor_end].rstrip() + "\n\n"

# range_rules_save body (بدون @app.route decorator)
save_start = live.index("@app.route(\"/range-rules/save\"")
save_end = live.index("def _build_range_rules_html")
save_func = live[save_start:save_end].rstrip() + "\n\n"

# ---------------------------------------------------------------------------
# ۳) اصلاح web_dashboard_adaptive.py
# ---------------------------------------------------------------------------
# حذف import web_dashboard_live as orig
adapt = adapt.replace("import web_dashboard_live as orig\n", "")

# حذف from web_dashboard_live import (...) block
adapt = re.sub(r"from web_dashboard_live import \([^)]+\)\n", "", adapt)

# حذف docstring ابتدایی و from __future__ از بخش adaptive (تکراری با کتابخانه)
adapt = re.sub(r'^""".*?"""\s*\n', '', adapt, count=1, flags=re.DOTALL)
adapt = adapt.replace("from __future__ import annotations\n", "", 1)

# جایگزینی orig.HTML_PAGE -> HTML_PAGE
adapt = adapt.replace("orig.HTML_PAGE", "HTML_PAGE")

# ---------------------------------------------------------------------------
# ۴) جایگزینی توابع delegating range_rules با نسخه‌های کامل
# ---------------------------------------------------------------------------
# پیدا کردن و حذف نسخه‌های delegating در adaptive
# range_rules_editor (delegating)
adapt_deleg_editor = '''@app.route("/range-rules")
def range_rules_editor():
    """صفحه ویرایش درصد نوسان مجاز — همان نسخه اصلی."""
    return orig.range_rules_editor()


@app.route("/range-rules/save", methods=["POST"])
def range_rules_save():
    """ذخیره درصد نوسان مجاز — همان نسخه اصلی."""
    return orig.range_rules_save()'''

if adapt_deleg_editor in adapt:
    # جایگزینی با نسخه‌های کامل + _build_range_rules_html
    replacement = editor_func + save_func + build_range_html_func
    adapt = adapt.replace(adapt_deleg_editor, replacement.rstrip())
    print("✅ توابع range_rules جایگزین شدند")
else:
    print("⚠ نسخه delegating range_rules پیدا نشد — بررسی دستی لازم است")
    # تلاش با الگوی منعطف‌تر
    adapt = re.sub(
        r'@app\.route\("/range-rules"\)\s*\ndef range_rules_editor\(\):\s*\n.*?return orig\.range_rules_editor\(\)\s*\n',
        editor_func.rstrip() + "\n",
        adapt, flags=re.DOTALL)
    adapt = re.sub(
        r'@app\.route\("/range-rules/save", methods=\["POST"\]\)\s*\ndef range_rules_save\(\):\s*\n.*?return orig\.range_rules_save\(\)\s*\n',
        save_func.rstrip() + "\n\n" + build_range_html_func.rstrip() + "\n",
        adapt, flags=re.DOTALL)

# بررسی نهایی: هیچ orig. نباید بماند
remaining_orig = [l for l in adapt.split("\n") if "orig." in l]
if remaining_orig:
    print(f"⚠ {len(remaining_orig)} خط با orig. باقی مانده:")
    for l in remaining_orig:
        print(f"  {l.strip()}")
else:
    print("✅ هیچ orig. باقی نمانده")

# ---------------------------------------------------------------------------
# ۵) ترکیب و نوشتن
# ---------------------------------------------------------------------------
merged = lib_code.rstrip() + "\n\n\n# " + "=" * 70 + "\n# داشبورد واحد: سه حالت live / db / sim (ادغام‌شده)\n# " + "=" * 70 + "\n\n" + adapt.lstrip()

out_path.write_text(merged, encoding="utf-8")
print(f"\n✅ فایل ادغام‌شده نوشته شد: {out_path}")
print(f"   حجم: {len(merged.splitlines())} خط")
