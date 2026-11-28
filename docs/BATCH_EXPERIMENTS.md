# Batch Simulation and Bot Experiments

## Purpose

ServerSC2 should support two related execution workloads:

- **Opening laboratory:** compare small, declared changes to a bot's opening decisions under a controlled StarCraft II scenario.
- **Build regression laboratory:** evaluate immutable bot builds against a repeatable scenario suite as the bot grows.

This is an extension of the SC2 match-execution host, not a strategy engine. SingularityBot remains the owner of bot behavior, canonical configuration contracts, and build production. ServerSC2 owns isolated match execution, bounded scheduling, SC2-side observation/evidence, and measurement collection.

Tracked by [issue #5](https://github.com/TrentBest/TheSingularityWorkshop.ServerSC2/issues/5).

## The three layers

1. **Experiment manifest** — immutable declaration of the baseline, candidate variants, scenario, exact bot build/configuration identities, map and game build, seed/randomization policy, budgets, and metric schema.
2. **Match workers** — isolated SC2 process groups and bot runners. Every match has its own ports, output directory, lifecycle, resource limits, and evidence record.
3. **Analysis** — deterministic derivation from retained raw samples. Results include paired deltas, uncertainty, and infrastructure failures separately from bot outcomes.

A candidate should be a data-only delta against a named baseline, expressed through SingularityBot's existing trusted configuration contracts. Do not introduce a second profile catalogue or allow experiment data to carry executable code, arbitrary runner arguments, or launch paths.

## Rendering and simulation speed are separate questions

The current opt-in probe launches SC2 with `-displayMode 0`. That is a launch-mode setting, not verified proof that rendering is disabled. The first benchmark must establish what the pinned SC2 build actually renders, whether an offscreen/headless mode is supported, and what performance changes when presentation is suppressed.

Even if rendering is eliminated, SC2 still has to advance its own simulation. Measure at least:

- SC2 game frames/game time per wall-clock second;
- match wall-clock duration and simulated duration;
- CPU time/utilization, memory, and process health;
- startup, join, terminal-observation, replay-save, and cleanup costs.

Do not assume the game simulation can run unboundedly faster than real time. Distinguish presentation frame rate, simulation/game-loop progression, and host scheduling overhead.

## First experiment: opener micro-decisions

Start with one pinned map, game build, bot race, opponent profile, game speed, and a small parameter surface. For example, a candidate might change one trusted opener setting—such as a production threshold or a decision timing—while all other configuration remains identical.

For every candidate, record:

- candidate ID and exact declared delta from baseline;
- immutable bot build ID and build digest;
- exact configuration payload digest and schema/catalogue/runtime pins;
- map identity and hash, SC2 game/data build, matchup, game speed;
- participant slot/team/start-location assignment;
- seed if controllable and verifiably applied; otherwise record the engine's known randomization limits;
- worker machine profile, concurrency level, process budgets, and launch settings;
- match ID, raw observation sample references, terminal evidence, replay hash, and failure classification.

Run a baseline and candidate under matched conditions where the engine permits. Rotate player slots/start locations across repetitions to detect side bias. Separate **exploration** (finding promising changes) from **confirmation** (repeating finalists across a predeclared scenario/seed set).

## Measurement model: preserve raw data

Raw samples are the source of truth. Derived metrics must be versioned and reproducible from them. A sample should carry a match ID, SC2 game-loop/frame index, game time when available, wall-clock timestamp, observer role, schema version, and the observed values.

Useful opener measurements include:

- supply, worker count, minerals, gas, and resource collection where available;
- structures/units and their completion/production milestones;
- first production start/completion times;
- idle production time and observed queue state where available;
- command/decision counts and action timing where the bot exposes trusted telemetry;
- terminal result and replay-derived outcome.

Keep two clocks:

- **Simulation clock:** SC2 game loop and game time. Use this for in-game timing and frame-aligned comparisons.
- **Wall clock:** elapsed real time. Use this for throughput, latency, and machine-capacity analysis.

Normalization is not a magic noise eraser. Every normalized value must name its denominator and cohort. Examples:

- production events per simulated minute;
- resources or production per worker-minute;
- milestone time in game loops or simulated seconds;
- candidate-minus-baseline delta for a matched scenario;
- wall-clock seconds per simulated game minute.

Retain raw values alongside normalized values. Never normalize away a meaningful effect (for example, an opener that deliberately has fewer workers). Preserve missing samples and censored matches; do not silently interpolate them. Report distributions (median and quantiles), paired deltas, and uncertainty intervals rather than relying on a single average. A normalized metric may reduce scale effects, but it does not remove randomness, confounding, or measurement error.

## Parallelism and capacity

Use a bounded worker pool, not an unbounded process fan-out. Each worker must own:

- a unique SC2 listener and multiplayer PortSet allocation;
- isolated process groups and bounded stdout/stderr logs;
- a unique match evidence directory;
- CPU/memory/process limits and a match timeout;
- cancellation and verified cleanup.

Benchmark sequentially first, then increase concurrency in controlled steps. Plot throughput and per-match wall-clock time against concurrency and record resource saturation. The safe concurrency limit is measured for a named machine profile and SC2 build; it is not a universal constant.

Thousands of matches may be possible across a sufficiently large fleet and over time, but cannot be assumed for one workstation. Distinguish total experiment size from simultaneous worker count.

## Failure and evidence policy

- A crash, timeout, incomplete observer evidence, invalid replay, or cleanup failure is an infrastructure outcome, not a bot loss.
- Keep failed-run diagnostics and classify them; exclude them from bot win/loss scoring while including them in reliability/throughput reporting.
- Do not mark a match complete without the existing host-authoritative terminal-result and replay-evidence gates.
- Never expose observer/global-vision data to player runners.
- Keep replay evidence distinct from periodic observation telemetry.
- Do not automatically promote a winning candidate. Return a reviewed candidate through SingularityBot's normal configuration/build pipeline.

## Delivery sequence

1. Prove display/offscreen behavior and measure one-match simulation-vs-wall-clock throughput.
2. Define a versioned experiment manifest and minimal raw opener-sample schema.
3. Run a tiny sequential matrix: baseline plus at least two one-variable candidates.
4. Produce reproducible paired analysis with raw data, normalized metrics, uncertainty, and replay/evidence references.
5. Add bounded parallel workers only after sequential evidence and cleanup are sound.
6. Measure concurrency/throughput curves and set machine-profile-specific caps.
7. Reuse the same harness for immutable build-vs-build regression suites.

## Current readiness

The existing probe already has an opt-in process bootstrap and passes `-displayMode 0`, but does not yet prove true render suppression, continuous time-series collection, live observer-authoritative match completion, or replay validation on a real SC2 installation. The production runtime is still the legacy two-player implementation. Therefore, this document defines the target experiment architecture; it does not claim that batch bot matches are currently runnable.
