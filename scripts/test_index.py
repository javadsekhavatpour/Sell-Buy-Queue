"""تست index server: استارت، curl /api/status، چاپ نتایج، توقف."""
import subprocess, sys, time, json, urllib.request, os, signal

ROOT = "/home/z/my-project/download/TSE_Screener"
PY = "/home/z/.venv/bin/python3"
OUT = "/tmp/test_index_result.txt"
out_f = open(OUT, "w", encoding="utf-8")
def p(*a):
    print(*a, file=out_f, flush=True)

# استارت index server
proc = subprocess.Popen(
    [PY, f"{ROOT}/dashboard_index.py", "--port", "8051"],
    cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
)
p(f"index PID={proc.pid}")

try:
    for _ in range(10):
        time.sleep(1)
        if proc.poll() is not None:
            o = proc.stdout.read()
            p("CRASHED early:")
            p(o[:1500])
            sys.exit(1)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8051/api/status", timeout=2) as r:
                data = json.loads(r.read().decode())
            break
        except Exception:
            continue
    else:
        p("timeout: index server پاسخ نداد")
        sys.exit(1)

    p("now:", data["now"])
    for s in data["symbols"]:
        p(f'  {s["name"]:6} | online={s["dashboard_online"]} | served={s.get("served_symbol")} | '
          f'match={s.get("symbol_match")} | sell={s.get("sell_score")} tier={s.get("sell_tier")} | '
          f'buy={s.get("buy_score")} tier={s.get("buy_tier")} | cls={s.get("classification")}')

    with urllib.request.urlopen("http://127.0.0.1:8051/", timeout=2) as r:
        html = r.read().decode()
    p(f"\nHTML: {len(html)} bytes, engines CSS={'engine-row' in html}, mismatch-warn={'mismatch-warn' in html}")
    p("SUCCESS")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
    p("index server stopped")
    out_f.close()
