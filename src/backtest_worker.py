"""
V.2.12.1 — اجرای بک‌تست در یک پردازهٔ جدا (CPU سنگین بدون اثر روی حلقهٔ زندهٔ ربات).
ورودی: pickle با کلیدهای range_data, btc5, btc15, range_params, trend_data, btc_frames, trend_params, run_trend
خروجی: JSON با range, variants, recommend, trend
استفاده: python backtest_worker.py <in.pkl> <out.json> <progress.json>
"""
from __future__ import annotations

import json
import pickle
import sys
import time


def _preload() -> None:
    """تست‌ها: SD_WORKER_PRELOAD=مسیر یک ماژول (مثلاً استاب‌های آفلاین) قبل از هر import."""
    import os
    pre = os.environ.get("SD_WORKER_PRELOAD")
    if pre and os.path.isfile(pre):
        sys.path.insert(0, os.path.dirname(pre))
        __import__(os.path.splitext(os.path.basename(pre))[0])


def main(in_path: str, out_path: str, progress_path: str) -> int:
    _preload()
    import backtest_range as br
    with open(in_path, "rb") as f:
        d = pickle.load(f)
    prog: dict = {"phase": "range", "t": time.time()}

    def flush():
        try:
            prog["t"] = time.time()
            with open(progress_path, "w", encoding="utf-8") as fp:
                json.dump(prog, fp)
        except Exception:
            pass

    out: dict = {}
    flush()
    wf: dict = {}

    def _wf(res: dict, params: dict) -> dict | None:
        try:
            per = res.get("period") or {}
            prm = dict(br.DEFAULT_PARAMS)
            prm.update(params or {})
            return br.walk_forward_selection(res.get("_trades") or [], prm, float(per.get("start") or 0) * 1000,
                                             float(per.get("end") or 0) * 1000)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:200]}
    try:
        rng = br.run_backtest(d["range_data"], d["btc5"], d["btc15"], d.get("range_params") or {}, prog)
        out["range"] = rng
        out["recommend"] = br.recommend(rng)
        wf["range"] = _wf(rng, d.get("range_params"))
        prog["phase"] = "variants"
        flush()
        out["variants"] = br.run_variants(d["range_data"], d["btc5"], d["btc15"], d.get("range_params") or {}, prog)
    except Exception as e:  # noqa: BLE001
        out["range_error"] = str(e)[:300]
    if d.get("run_trend"):
        prog["phase"] = "new_strategies"
        flush()
        try:
            import backtest_strategies as bs
            ns = bs.run_new_strategies(d["trend_data"], d["btc_frames"], d.get("range_params") or {}, prog)
            out["new_strategies"] = ns
            for name, res in ns.items():
                wf[name] = _wf(res, d.get("range_params"))
        except Exception as e:  # noqa: BLE001
            out["new_strategies_error"] = str(e)[:300]
        prog["phase"] = "v216_research"
        flush()
        try:
            import backtest_strategies2 as bs2
            v = bs2.run_v216(d["trend_data"], d["btc_frames"], d.get("range_params") or {}, prog)
            out.setdefault("new_strategies", {}).update(v.get("strategies") or {})
            for name, res in (v.get("strategies") or {}).items():
                wf[name] = _wf(res, d.get("range_params"))
            out["rs_robustness"] = v.get("rs_robustness")
            if v.get("errors"):
                out["v216_part_errors"] = v.get("errors")
        except Exception as e:  # noqa: BLE001
            out["v216_error"] = str(e)[:300]
        prog["phase"] = "trend"
        flush()
        try:
            import backtest_trend as bt
            tr = bt.run_trend_backtest(d["trend_data"], d["btc_frames"], d.get("trend_params") or {}, prog, flush)
            out["trend"] = tr
            tp_ = dict(bt.DEFAULT_TREND_PARAMS)
            tp_.update(d.get("trend_params") or {})
            wf["trend"] = _wf(tr, tp_)
        except Exception as e:  # noqa: BLE001
            out["trend_error"] = str(e)[:300]
    # V.2.18.0 — پژوهش کوتاه‌مدت روی ۵۰ نماد اول (+ میم و طلا)
    if d.get("universe_data"):
        prog["phase"] = "intraday_research"
        flush()
        try:
            import backtest_intraday as bi
            ir = bi.run_intraday(d["universe_data"], d["btc_frames"], d.get("range_params") or {}, prog)
            out["intraday_research"] = ir
            for name, res in (ir.get("strategies") or {}).items():
                wf["intraday:" + name] = _wf(res, d.get("range_params"))
        except Exception as e:  # noqa: BLE001
            out["intraday_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    # V.2.17.0 — پژوهش روزانه ۲ ساله
    if d.get("daily_data"):
        prog["phase"] = "daily_research"
        flush()
        try:
            import backtest_daily as bd
            out["daily_research"] = bd.run_daily(d["daily_data"], d.get("range_params") or {})
        except Exception as e:  # noqa: BLE001
            out["daily_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    # V.2.22.0 — استراتژی‌های متن‌باز گیت‌هاب (freqtrade-strategies) روی همان دادهٔ ۹۰ روزه
    if d.get("trend_data"):
        prog["phase"] = "github_research"
        flush()
        try:
            import backtest_github as bg
            _gd = dict(d["trend_data"])   # V.2.25.0 — طلا (از دادهٔ ۵۰ نماد) برای استراتژی‌های طلا
            for _g in bg.GOLD_SYMBOLS:
                if (d.get("universe_data") or {}).get(_g):
                    _gd[_g] = d["universe_data"][_g]
            _ext = d.get("gh_ext") or {}   # V.2.40.0 — نمادهای اضافه (۱h + ۴h واقعی توبیت)
            for _s, _fr in _ext.items():
                if _s not in _gd:
                    _gd[_s] = _fr
            out["github_research"] = bg.run_github(_gd, d.get("range_params") or {},
                                                   ext={s_ for s_ in _ext if s_ not in d["trend_data"]},
                                                   long_data=d.get("long_data") or {})   # V.2.42.0 — کنترل ۳۶۵ روزه
        except Exception as e:  # noqa: BLE001
            out["github_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    out["walk_forward"] = wf

    def _strip(obj):
        if isinstance(obj, dict):
            obj.pop("_trades", None)
            for v in obj.values():
                _strip(v)
    _strip(out)
    prog["phase"] = "done"
    flush()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
