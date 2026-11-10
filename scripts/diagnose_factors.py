"""اسکریپت تشخیصی - چاپ امتیازهای هر شاخص برای هر سناریو."""
import sys
import json
from pathlib import Path

ROOT = Path("/home/z/my-project/download/TSE_Screener")
sys.path.insert(0, str(ROOT))

from early_warning import (
    SimulationDataCollector,
    SellPressureDetector,
    SmartAccumulationDetector,
)

with open(ROOT / "config" / "warning_thresholds.json", "r", encoding="utf-8") as f:
    config = json.load(f)

for scenario in ["sell_pressure", "accumulation", "mixed"]:
    print(f"\n{'='*70}\nسناریو: {scenario}\n{'='*70}")
    sim = SimulationDataCollector(config, scenario=scenario, seed=42)
    snapshots = sim.generate_series(num_samples=90)

    sp_det = SellPressureDetector(config)
    acc_det = SmartAccumulationDetector(config)

    last = snapshots[-1]
    print(f"\nآخرین نمونه (t={last.tehran_time}):")
    print(f"  last={last.last_price:.2f}  close={last.close_price:.2f}  base={last.yesterday_price:.0f}")
    print(f"  buyer_power={last.buyer_power:.3f}  money_flow_ratio={last.real_money_flow_ratio:+.4f}")
    print(f"  buy_count={last.real_buy_count}  sell_count={last.real_sell_count}")
    print(f"  best_buy_vol={last.best_buy_volume}  best_sell_vol={last.best_sell_volume}")

    prev = snapshots[-2]
    sp = sp_det.evaluate(last, prev)
    acc = acc_det.evaluate(last, prev, snapshots[-6:-1])

    print(f"\nفشار فروش: {sp.total_score:.1f} - {sp.level}")
    print("  فاکتورها:")
    for f in sp.factors:
        print(f"    {f.label:42s}: raw={f.raw_value:9.4f}  norm={f.normalized:.3f}  score={f.score:5.2f}/{f.max_points}")

    print(f"\nجمع‌آوری:  {acc.total_score:.1f} - {acc.level}")
    print("  فاکتورها:")
    for f in acc.factors:
        print(f"    {f.label:42s}: raw={f.raw_value:9.4f}  norm={f.normalized:.3f}  score={f.score:5.2f}/{f.max_points}")
