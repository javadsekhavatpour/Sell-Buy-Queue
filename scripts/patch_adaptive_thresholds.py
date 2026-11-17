"""
اسکریپت جایگزینی full_at ثابت با _get_threshold تطبیقی در موتورها.
Phase 2: یکپارچه‌سازی normalizer در sell_pressure.py و smart_accumulation.py
"""
import re
from pathlib import Path

BASE = Path("/home/z/my-project/download/TSE_Screener/early_warning")

# الگو: full_at = self.norm["factor_name"]["full_at"]
# جایگزین: full_at = self._get_threshold(snap.symbol, "factor_name")
PATTERN = re.compile(r'full_at\s*=\s*self\.norm\["(\w+)"\]\["full_at"\]')


def patch_file(filepath: str) -> int:
    path = Path(filepath)
    content = path.read_text(encoding="utf-8")
    count = 0

    def replacer(m):
        nonlocal count
        factor = m.group(1)
        count += 1
        return f'full_at = self._get_threshold(snap.symbol, "{factor}")'

    new_content = PATTERN.sub(replacer, content)
    if count > 0:
        path.write_text(new_content, encoding="utf-8")
    return count


files = [
    str(BASE / "sell_pressure.py"),
    str(BASE / "smart_accumulation.py"),
]

total = 0
for f in files:
    n = patch_file(f)
    total += n
    print(f"  {f.split('/')[-1]}: {n} جایگزاری")

print(f"\nمجموع: {total} جایگزاری")

# تأیید با syntax check
import py_compile
for f in files:
    py_compile.compile(f, doraise=True)
    print(f"  ✓ syntax صحیح: {f.split('/')[-1]}")
