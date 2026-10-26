#!/usr/bin/env python3
"""zai-weather builder — render weather.html from zai-heatmap.json.

Standalone static page (no server, no dependencies). The "now" badge is
computed in the browser from the viewer's clock; the embedded data is whatever
the collector saw at build time (see staleness marker for old builds).

Usage: python build_weather.py [--in zai-heatmap.json] [--out weather.html]
Python 3.8+, stdlib only.
"""
import argparse
import datetime
import html
import json
from pathlib import Path

HEX = {"green": "#22c55e", "yellow": "#eab308", "red": "#ef4444"}
DAYS_UA_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

CSS = """
:root{--bg:#0f172a;--card:#1e293b;--text:#e2e8f0;--dim:#94a3b8;--line:#334155}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:15px/1.55 'Segoe UI',system-ui,sans-serif;padding:28px;max-width:1100px}
h1{font-size:22px;margin-bottom:4px}
.sub{color:var(--dim);font-size:12.5px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.title{font-size:15px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px}
.row{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:10px}
.badge{color:#0f172a;font-weight:700;font-size:15px;padding:6px 14px;border-radius:8px;background:#475569;white-space:nowrap}
.subline{color:var(--dim);font-size:13px}
.legend{margin-left:auto;display:flex;gap:10px;color:var(--dim);font-size:11.5px;align-items:center;flex-wrap:wrap}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px;vertical-align:-1px}
.strip{display:grid;grid-template-columns:repeat(24,1fr);gap:3px;margin:8px 0 2px}
.cell{height:22px;border-radius:4px;background:#475569;position:relative}
.cell.now{outline:2px solid #e2e8f0;outline-offset:1px}
.cell.now::after{content:"▲";position:absolute;top:-13px;left:50%;transform:translateX(-50%);color:#e2e8f0;font-size:9px}
.hlabels{display:grid;grid-template-columns:repeat(24,1fr);gap:3px;color:var(--dim);font-size:10px;text-align:center}
.days{margin-top:12px;display:grid;gap:4px}
.day{display:grid;grid-template-columns:74px repeat(24,1fr);gap:3px;align-items:center}
.day .d{color:var(--dim);font-size:11px}
.day .cell{height:15px}
.cell.void{background:#111a2c;border:1px solid #1e293b}
.foot{color:var(--dim);font-size:11.5px;margin-top:12px}
"""

JS = """
(function () {
  var hm = window.__ZAI__; if (!hm) return;
  var HEX = {green:'#22c55e', yellow:'#eab308', red:'#ef4444'};
  var NAME = {green:'GO', yellow:'CAUTION', red:'NO-GO'};
  var now = new Date(), h = now.getHours();
  var badge = document.getElementById('badge'), sub = document.getElementById('sub');
  var th = hm.hours ? hm.hours[h] : null;
  var typical = (th && th.days >= 3 && th.rate !== null)
    ? (th.rate >= 0.9 ? 'green' : th.rate >= 0.5 ? 'yellow' : 'red') : null;
  var live = hm.live, liveV = null, liveFresh = false;
  if (live && live.total > 0) {
    var to = new Date(live.to.replace(' ', 'T'));
    liveFresh = (now - to) < 4 * 3600000;
    if (live.verdict === 'GO') liveV = 'green';
    else if (live.verdict === 'CAUTION') liveV = 'yellow';
    else if (live.verdict === 'NO-GO') liveV = 'red';
  }
  if (liveFresh && liveV) {
    badge.style.background = HEX[liveV];
    badge.textContent = NAME[liveV] + ' — now';
    sub.textContent = 'last hour before build: ' + Math.round(live.rate * 100) +
      '% success (' + live.ok + ' ok / ' + live.fail + ' failed attempts)';
  } else if (typical) {
    badge.style.background = HEX[typical];
    badge.textContent = NAME[typical] + ' — typical for ' + ('0' + h).slice(-2) + ':00';
    sub.textContent = 'by hour of day (' + th.days + 'd sample): ' +
      Math.round(th.rate * 100) + '% success';
  } else {
    badge.textContent = '— no data for this hour';
    sub.textContent = 'no traffic sample for this hour';
  }
  if (liveV && !(liveFresh && liveV)) {
    sub.textContent += ' · build-time live: ' + live.verdict +
      (live.total ? ' ' + Math.round(live.rate * 100) + '%' : '');
  }
  var cur = document.querySelector('.strip .cell[data-h="' + h + '"]');
  if (cur) cur.classList.add('now');
  var gen = new Date(hm.generated.replace(' ', 'T'));
  if ((now - gen) > 6 * 3600000) {
    var foot = document.getElementById('foot');
    if (foot) foot.innerHTML = '⚠ stale data (&gt;6h since build) — ' + foot.innerHTML;
  }
})();
"""


def esc(s):
    return html.escape(str(s), quote=True)


def _rate_color(rate):
    if rate >= 0.9:
        return HEX["green"]
    if rate >= 0.5:
        return HEX["yellow"]
    return HEX["red"]


def build(hm):
    strip = []
    for x in hm["hours"]:
        if x["days"] >= 3 and x["rate"] is not None:
            strip.append("<div class='cell' data-h='%d' style='background:%s' "
                         "title=\"%02d:00 · %d%% success · %dd sample\"></div>"
                         % (x["h"], _rate_color(x["rate"]), x["h"],
                            round(x["rate"] * 100), x["days"]))
        else:
            strip.append("<div class='cell' data-h='%d' "
                         "title=\"%02d:00 · little data (%dd sample)\"></div>"
                         % (x["h"], x["h"], x["days"]))
    labels = "".join("<span>%02d</span>" % h if h % 3 == 0 else "<span></span>"
                     for h in range(24))
    rows = []
    for day in hm["recent"]:
        d = datetime.date.fromisoformat(day["date"])
        cells = []
        for h, c in enumerate(day["cells"]):
            if c is None:
                cells.append("<div class='cell void' "
                             "title=\"%s %02d:00 · no traffic\"></div>"
                             % (d.strftime("%d.%m"), h))
            else:
                cells.append("<div class='cell' style='background:%s' "
                             "title=\"%s %02d:00 · %d%% (%d ok / %d failed)\"></div>"
                             % (_rate_color(c["rate"]), d.strftime("%d.%m"), h,
                                round(c["rate"] * 100), c["ok"], c["fail"]))
        rows.append("<div class='day'><span class='d'>%s %s</span>%s</div>"
                    % (DAYS_UA_EN[d.weekday()], d.strftime("%d.%m"), "".join(cells)))
    payload = json.dumps(hm, ensure_ascii=False).replace("</", "<\\/")
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>zai-weather — GLM coding plan gateway stability</title>
<style>%s</style></head><body>
<h1>🌡 zai-weather — GLM coding plan stability</h1>
<div class="sub">built from local ZCode logs · %s · regenerate:
<code>python zai_weather.py &amp;&amp; python build_weather.py</code></div>
<div class="card">
<div class="title">Is NOW a good time for heavy tasks?</div>
<div class="row"><div class="badge" id="badge">…</div>
<div class="subline" id="sub">computing from your clock…</div>
<div class="legend"><span><i style="background:#22c55e"></i>≥90%%</span>
<span><i style="background:#eab308"></i>50–90%%</span><span><i style="background:#ef4444"></i>&lt;50%%</span>
<span><i style="background:#475569"></i>little data</span><span><i style="background:#111a2c;border:1px solid #1e293b"></i>no traffic</span></div></div>
<div class="strip">%s</div>
<div class="hlabels">%s</div>
<div class="days">%s</div>
<div class="foot" id="foot">quiet window: %s · heavy tasks — quiet hours or off-peak queue ·
build: %s · source: ZCode logs (zcode-*.jsonl) · MIT</div>
</div>
<script>window.__ZAI__ = %s;</script>
<script>%s</script>
</body></html>""" % (CSS, esc(hm["generated"]), "".join(strip), labels,
                     "".join(rows), esc(hm.get("quiet", "—")),
                     esc(hm["generated"]), payload, JS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="zai-heatmap.json")
    ap.add_argument("--out", default="weather.html")
    args = ap.parse_args()
    hm = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    Path(args.out).write_text(build(hm), encoding="utf-8", newline="\n")
    print("OK: %s built from %s (%s)" % (args.out, args.inp, hm["generated"]))


if __name__ == "__main__":
    main()
