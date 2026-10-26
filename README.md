# zai-weather 🌡

**中文摘要**：Z.ai/GLM Coding Plan 没有官方状态页，官方"System health"指标只测推理核心、不测网关。这个工具从你本机 ZCode 的日志里统计 API 请求的真实成功率（按小时/按天），生成静态 HTML 面板，告诉你"现在适不适合跑重任务"。纯本地、无依赖、不上传任何数据。

**EN**: There is no official status page for the Z.ai / GLM Coding Plan, and the
in-app "System health" chart measures the provider's inference core — not the
gateway coding-plan clients actually hit. During the Oct 23–25, 2026 incident
storm our client saw 13–54% success rates for hours while the official daily
metrics kept showing 99.9%+.

zai-weather answers the only question that matters to a coding-plan user:
**"is NOW a good time to start a heavy task?"** — from *your own* logs, because
your traffic is the most honest probe of the gateway you use.

## What it shows

- **Live badge** (GO / CAUTION / NO-GO) — share of successful request attempts
  in the last hour before the build, minute-accurate.
- **24-hour strip** — typical risk of each hour of day over a rolling window
  (default 14 days). Hours with <3 days of traffic sample render gray:
  **no traffic ≠ no problems**, we never paint empty hours green.
- **7-day × 24h grid** — the incident calendar; every burst is visible.
- **Quiet window** — the longest run of hours with ≥90% success and ≥3 days
  of sample. Schedule heavy runs there (or use your agent's off-peak queue).

## Quickstart

```bash
python zai_weather.py            # scans ~/.zcode/cli/log/zcode-*.jsonl → zai-heatmap.json
python build_weather.py          # renders weather.html — open it in a browser
```

Python 3.8+, stdlib only, nothing leaves your machine. Non-ZCode log dir?
`--log-dir PATH`. Schedule it (Task Scheduler / cron) and rebuild as often as
you like — e.g. every 15–60 minutes.

## How it counts

Each line in `zcode-*.jsonl` is one event:

| event | meaning |
|---|---|
| `"lastChunkType":"finish"` | a stream completed successfully |
| `"event":"model.request.failed"` + reason `network_error` / `server_error` / `rate_limited` | one failed attempt |

Retries of the same logical request count as separate attempts. The verdict is
therefore the **share of successful attempts** — friction exactly as the client
experiences it, not a server-side health metric. Thresholds: GO ≥90%,
CAUTION 50–90%, NO-GO <50% of the last hour.

## Why not just ping the API?

Synthetic pings cost quota, measure one tiny request (real pain shows up in
long SSE streams being cut mid-generation — `SocketError: other side closed`),
and only see the moment you probe. Your real traffic already contains thousands
of honest probes per day. Also: direct API probes can't authenticate with the
coding-plan credential store; local logs always work.

## Official metrics ≠ your experience

The provider's own daily numbers (decode speed / success rate) stayed at
99.9%+ on days when gateway clients logged thousands of 502s and dropped
streams. Daily grain smooths bursts; inference-core health is not gateway
health. Both views are useful — just don't confuse them. This repo tracks the
one you can act on.

## Status: research tooling, as-is

Built during the 1024-week outage storms to decide when to run heavy agentic
tasks. No warranty; MIT. Contributions welcome — especially porting the log
paths for other harnesses (Claude Code CLI, Codex, …) if they expose similar
per-request logs.

## Repo layout

```
zai_weather.py       collector: logs → zai-heatmap.json
build_weather.py     renderer: zai-heatmap.json → weather.html
sample-heatmap.json  synthetic sample (not real data)
```
