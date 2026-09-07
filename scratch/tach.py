import sys
sys.path.insert(0, r"d:\raits"); sys.path.insert(0, r"d:\raits\scratch")
import harness as H
for nhan, kw in (("chi ema=50           ", dict(ema=50)),
                 ("chi stop 2,0xATRngay ", dict(stop_basis=2.0))):
    cfg = H.Cfg(fix_fill=True, arm_hours=H.ARM_LIVE, ratchet=False,
                roska4_only=False, **kw)
    r = H.run_deploy(cfg, "baseline"); H._CACHE.clear()
    print("{}: net ${:>9,.0f}  Calmar {:>6.2f}  | sua khop {:>4} lenh ${:,.0f}"
          .format(nhan, r["net"] or 0, r["calmar"] or 0, r["sua_n"], r["sua_tot"]))
    sys.stdout.flush()
