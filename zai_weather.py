#!/usr/bin/env python3
"""zai-weather collector — provider stability heatmap from local ZCode logs.

Reads ~/.zcode/cli/log/zcode-*.jsonl (the ZCode CLI logs) and computes, in LOCAL
hours:

  live   — exact last --live-min minutes before the run (minute granularity)
  hours  — per-hour-of-day aggregate over --days (typical risk of an hour)
  recent — last 7 days x 24h grid (incident calendar)
  quiet  — longest run of "green" hours with >=3 days of coverage

Counting rules (one line in the JSONL = one event):
  failed attempt = line with "event":"model.request.failed" and reason in
                   {network_error, server_error, rate_limited}
  success        = line with "lastChunkType":"finish" (a completed stream)

Retries of the same logical request count as separate attempts — the metric is
"share of successful attempts", i.e. friction as the user experiences it.

Hours WITHOUT traffic are NOT hours without problems: per-hour sample size
(days) is tracked separately, and hours below the coverage gate render gray,
never green.

Usage:
  python zai_weather.py [--days 14] [--live-min 60]
                        [--log-dir PATH] [--out zai-heatmap.json]

Python 3.8+, stdlib only.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

LOG_DIR_DEFAULT = Path.home() / ".zcode" / "cli" / "log"
FAIL_REASONS = {"network_error", "server_error", "rate_limited"}
TS = re.compile(r'"timestamp":"([^"]+)"')
REASON = re.compile(r'"reason":"([a-z_]+)"')


def verdict(ok, fail):
    if ok + fail == 0:
        return "NO-DATA"
    rate = ok / (ok + fail)
    if rate >= 0.9:
        return "GO"
    if rate >= 0.5:
        return "CAUTION"
    return "NO-GO"


def collect(log_dir):
    """(date, hour) buckets for the calendar + (date, minute-of-day) buckets
    for the exact live window."""
    buckets = defaultdict(lambda: {"ok": 0, "fail": 0})
    minutes = defaultdict(lambda: {"ok": 0, "fail": 0})
    if not log_dir.exists():
        sys.exit("zai-weather: log dir not found: %s" % log_dir)
    files = sorted(log_dir.glob("zcode-*.jsonl"))
    if not files:
        sys.exit("zai-weather: no zcode-*.jsonl logs in %s" % log_dir)
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            is_ok = '"lastChunkType":"finish"' in line
            is_fail = '"event":"model.request.failed"' in line
            if not (is_ok or is_fail):
                continue
            if is_fail:
                m = REASON.search(line)
                if not m or m.group(1) not in FAIL_REASONS:
                    continue
            m = TS.search(line)
            if not m:
                continue
            try:
                t = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
            except ValueError:
                continue
            lt = t.astimezone()
            kind = "ok" if is_ok else "fail"
            buckets[(lt.date().isoformat(), lt.hour)][kind] += 1
            minutes[(lt.date(), lt.hour * 60 + lt.minute)][kind] += 1
    return buckets, minutes


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=14,
                    help="window for the per-hour-of-day aggregate (default 14)")
    ap.add_argument("--live-min", type=int, default=60,
                    help="live verdict window in minutes (default 60)")
    ap.add_argument("--log-dir", default=str(LOG_DIR_DEFAULT),
                    help="ZCode CLI log dir (default ~/.zcode/cli/log)")
    ap.add_argument("--out", default="zai-heatmap.json", help="output JSON path")
    args = ap.parse_args()

    log_dir = Path(args.log_dir)
    now = datetime.now().astimezone()
    buckets, minutes = collect(log_dir)

    # live — exact window by minute (do NOT sum whole hour cells here)
    live_from = now - timedelta(minutes=args.live_min)
    live_key = (live_from.date(), live_from.hour * 60 + live_from.minute)
    live_ok = live_fail = 0
    for (d, mofday), c in minutes.items():
        if (d, mofday) >= live_key:
            live_ok += c["ok"]
            live_fail += c["fail"]

    # hours — per hour of day over the window
    since = (now - timedelta(days=args.days)).date()
    hours = []
    for h in range(24):
        ok = fail = days = 0
        for (d, hh), c in buckets.items():
            if hh == h and date.fromisoformat(d) >= since:
                ok += c["ok"]
                fail += c["fail"]
                days += 1
        total = ok + fail
        hours.append({"h": h, "ok": ok, "fail": fail, "days": days,
                      "rate": round(ok / total, 3) if total else None})

    # quiet — longest run of green hours (coverage >= 3 days AND rate >= 0.9)
    green = [x["days"] >= 3 and x["rate"] is not None and x["rate"] >= 0.9
             for x in hours]
    best_len = best_start = cur_len = cur_start = 0
    for i, g in enumerate(green + [False]):
        if g and cur_len == 0:
            cur_start = i
        cur_len = cur_len + 1 if g else 0
        if cur_len > best_len:
            best_len, best_start = cur_len, cur_start
    quiet = ("%02d:00\u2013%02d:00" % (best_start, best_start + best_len)
             if best_len >= 3 else "unknown (not enough data)")

    # recent — last 7 days grid
    recent = []
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).date().isoformat()
        cells = []
        for h in range(24):
            c = buckets.get((d, h))
            if c and (c["ok"] or c["fail"]):
                total = c["ok"] + c["fail"]
                cells.append({"ok": c["ok"], "fail": c["fail"],
                              "rate": round(c["ok"] / total, 3)})
            else:
                cells.append(None)
        recent.append({"date": d, "cells": cells})

    total = live_ok + live_fail
    out = {
        "generated": now.strftime("%Y-%m-%d %H:%M"),
        "live": {
            "ok": live_ok, "fail": live_fail, "total": total,
            "rate": round(live_ok / total, 3) if total else None,
            "verdict": verdict(live_ok, live_fail),
            "from": live_from.strftime("%Y-%m-%d %H:%M"),
            "to": now.strftime("%Y-%m-%d %H:%M"),
        },
        "hours": hours,
        "recent": recent,
        "quiet": quiet,
        "window_days": args.days,
    }
    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print("OK: %s rebuilt at %s | live %s (%dok/%dfail) | quiet %s"
          % (args.out, out["generated"], out["live"]["verdict"],
             live_ok, live_fail, quiet))


if __name__ == "__main__":
    main()
