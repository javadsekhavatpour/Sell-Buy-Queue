# Fix mojibake in web_dashboard_adaptive.py
# Replaces corrupted _NEW_TICK_HEADER and _NEW_CHART_TAIL with ASCII-only JS
# Persian classification text still comes from server (s.cls)
from pathlib import Path
import re

p = Path("/home/z/my-project/download/TSE_Screener/web_dashboard_adaptive.py")
src = p.read_text(encoding="utf-8")

# --- New _NEW_TICK_HEADER: ASCII-only JS, Persian via \u escapes ---
# Using raw string so \u stays literal in script, written literally to file,
# then Python converts \uXXXX to real char at import time.
NEW_TICK = r'''_NEW_TICK_HEADER = """/* ---------- Phase 2.1+: score history for signal overlay ---------- */
let scoreHist = [];
function pushScore(d) {
  if (!d || !d.ok || !d.snapshot || !d.engines) return;
  const t = d.snapshot.tehran_time;
  if (!t) return;
  const eng = d.engines, sell = eng.sell||{}, buy = eng.buy||{}, comb = eng.combined||{};
  const entry = {
    time: t,
    sell: sell.total_score || 0,
    buy: buy.total_score || 0,
    crit: (comb.is_critical === true) || /\u0628\u062d\u0631\u0627\u0646|\u062a\u0642\u0627\u0628\u0644/.test(eng.classification||''),
    cls: eng.classification || ''
  };
  if (scoreHist.length && scoreHist[scoreHist.length-1].time === t) {
    scoreHist[scoreHist.length-1] = entry;
  } else {
    scoreHist.push(entry);
  }
  if (scoreHist.length > 300) scoreHist.shift();
}

/* ---------- \u0686\u0631\u062e\u0647 \u0628\u0647\u200c\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc ---------- */
let connOk = false;"""'''

# Replace old _NEW_TICK_HEADER (match from start marker to closing """)
pat1 = re.compile(r'_NEW_TICK_HEADER = """[\s\S]*?let connOk = false;"""', re.MULTILINE)
if pat1.search(src):
    src = pat1.sub(lambda m: NEW_TICK, src, count=1)
    print("OK: _NEW_TICK_HEADER replaced")
else:
    print("FAIL: _NEW_TICK_HEADER not found")

# --- New _NEW_CHART_TAIL: ASCII labels, Persian via \u escapes ---
NEW_CHART = r'''_NEW_CHART_TAIL = """  const dotL = `<circle cx="${X(times.length-1)}" cy="${Y(last[last.length-1])}" r="3.5" fill="#1565c0"/>`;
  // Phase 2.1+: overlay engine signals on price chart
  const SIG_TH = 50;
  let sigMarkers = "", sigCount = 0;
  for (const s of scoreHist) {
    const idx = times.indexOf(s.time);
    if (idx < 0) continue;
    const x = X(idx).toFixed(1), y = Y(last[idx]);
    let m = "";
    if (s.crit) {
      m = `<polygon points="${x},${(y-10).toFixed(1)} ${(x-7)},${(y+5).toFixed(1)} ${(x+7)},${(y+5).toFixed(1)}" fill="#f9a825" stroke="#e65100" stroke-width="1.2"><title>${s.time} \u2605 critical \u2014 sell:${N(s.sell,1)} buy:${N(s.buy,1)} | ${s.cls}</title></polygon>`;
      sigCount++;
    } else if (s.sell >= SIG_TH) {
      m = `<polygon points="${x},${(y+10).toFixed(1)} ${(x-6)},${(y-3).toFixed(1)} ${(x+6)},${(y-3).toFixed(1)}" fill="#c62828"><title>${s.time} \u25bc sell:${N(s.sell,1)} | ${s.cls}</title></polygon>`;
      sigCount++;
    } else if (s.buy >= SIG_TH) {
      m = `<polygon points="${x},${(y-10).toFixed(1)} ${(x-6)},${(y+3).toFixed(1)} ${(x+6)},${(y+3).toFixed(1)}" fill="#2e7d32"><title>${s.time} \u25b2 buy:${N(s.buy,1)} | ${s.cls}</title></polygon>`;
      sigCount++;
    }
    sigMarkers += m;
  }
  const sigLegend = `<text x="${padL+4}" y="${padT+10}" font-size="11" fill="${sigCount>0?'#5a6b7f':'#bbb'}">\u0633\u06cc\u06af\u0646\u0627\u0644\u200c\u0647\u0627 \u0631\u0648\u06cc \u0646\u0645\u0648\u062f\u0627\u0631: ${sigCount} \u0644\u062d\u0638\u0647 \u2014 \u25bc\u0641\u0631\u0648\u0634(\u2265${SIG_TH}) \u25b2\u062e\u0631\u06cc\u062f(\u2265${SIG_TH}) \u2605critical</text>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet">
    ${sigLegend}${grid}${bars}${refLine}${lineClose}${lineLast}${dotL}${sigMarkers}${ylabels}${xlabels}
  </svg>`;
}"""'''

# Replace old _NEW_CHART_TAIL (match from start to closing """ before "# Patch C")
pat2 = re.compile(r'_NEW_CHART_TAIL = """[\s\S]*?"""\n\n# Patch C', re.MULTILINE)
if pat2.search(src):
    src = pat2.sub(lambda m: NEW_CHART + "\n\n# Patch C", src, count=1)
    print("OK: _NEW_CHART_TAIL replaced")
else:
    print("FAIL: _NEW_CHART_TAIL not found")

p.write_text(src, encoding="utf-8")
print("DONE: file saved")
