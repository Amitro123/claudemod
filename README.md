# clawd-hud — a pixel spark for Claude Code

![clawd-hud demo](assets/clawd-hud.gif)

A Claude Code plugin that puts a little animated spark above the prompt, with a pixel battery for each of your usage limits, and adds a prompt-cache timer and a context meter beside the model picker. It works on personal plans and on enterprise seats.

## What it shows

**Above the prompt (the `AbovePrompt` band)**
- **The spark** on the left. What it does follows what Claude is doing:

| Mood | When | Scenes |
|---|---|---|
| `idle` | waiting for you | drifting with a firefly, juggling, watering a sprout |
| `working` | a turn is running | at the terminal, stacking blocks, pondering, sending out sub-agents |
| `working` > 90s | a hard task | a smoke break on a crate joins the rotation |
| `loop` | the same tool with the same input 3× in one turn | riding a coaster loop it can't get out of |
| `done` | the turn answered | fireworks and a hop (a lightbulb if the task was hard) |
| `relax` | 4 min after `done` | stargazing on a hill, a pool float, cocoa by a snowy window |
| `error` | API error or refusal | goes gray under a little storm cloud, then idle |

- **A battery per usage window**, showing what is **left**: green above 30%, amber above 10%, red below. Each has a "resets in …" countdown.

| | Personal (Pro / Max) | Enterprise |
|---|---|---|
| Batteries | `5h` window, `7d` weekly | `7d` weekly, `mo` monthly spend cap ("over by …" past 100%) |
| Cost | not shown | `$` spent this session |
| "resets in" | the API's reset time | the API's reset time; for the spend cap without one, the 1st of next month |
| Cache timer (`auto`) | 1 hour | 5 minutes |

**Beside the model picker (the `SessionMode` slot)**
- **Cache bolt**: counts down the prompt-cache TTL from the last response. Green while warm, amber in the last minute, gray once cold.
- **Context capsule**: how full the context window is, e.g. `ctx 34% · 68k/200k`.

In a terminal (which can't draw SVG) the same readings show up as a text spark `✦(•_•)` and `▰▰▰▱▱` batteries. A one-line summary also goes to the status bar.

## Install

```text
/plugin marketplace add Amitro123/claudemod
/plugin install clawd-hud@clawd-hud
```

## Options

Set with `claude plugin configure clawd-hud@clawd-hud`, or in the plugin settings:

| Option | Values | Default | What it does |
|---|---|---|---|
| `plan` | `auto`, `personal`, `enterprise` | `auto` | Which limits to show. `auto` switches to enterprise as soon as the account reports a monthly spend limit (`spend_limit`). |
| `cacheTtl` | `auto`, `5m`, `1h` | `auto` | The cache timer's length. `auto` is 1h on personal plans and 5m on enterprise. |

## How it works

- `hooks/register.tsx` hooks `session.start`, `session.measure`, `turn.start`, `tool.call`, `turn.complete` and `ui.render`, keeps its state in atoms, and redraws the spark 8 times a second.
- `hooks/scene.ts` paints one frame of a mood on an 88×20 pixel stage. Every motion is a plain function of the time since the mood began, so a redraw lands on the same frame and never restarts an animation.
- `hooks/gauges.ts` draws the batteries, the bolt and the capsule as plain SVG, so the demo renderer uses the exact same art.
- `tests/plan.test.tsx` checks the personal and enterprise views, the spend-cap overflow and both cache timers. Run it with `claude plugin test plugins/clawd-hud`.

## Changelog

**0.6.0**: a new look. The spark mascot, its scenes, the stage and the batteries, bolt and capsule are all new, drawn by a new animation engine. Everything else carries over: plans, timers, loop detection, the hard-task and eureka moments.

**0.5.0**: renamed from `pixel-buddy` to `clawd-hud` (install again; old settings don't carry over). Enterprise mode. The loop detector's `tool.call` hook got a registration `.catch`, so it can never block a tool call.

**0.4.1**: only a real answer celebrates (a refusal gets the error mood). The cache countdown flips to "cold" even after the machine slept. Timers no longer stack up when `session.start` fires again. No more "resets in NaNm".

**0.4.0**: the hard-task smoke break, the eureka lightbulb and the loop coaster. **0.3.0**: the error mood.

## Regenerating the GIF

The GIF is rendered from the plugin's real `scene.ts` and `gauges.ts`, so it is not a mock-up:

```bash
cd demo
npm install
node render-frames.mjs   # needs Node ≥ 22.18 or ≥ 23.6 (runs the .ts files with built-in type stripping)
python make-gif.py       # needs Pillow
```
