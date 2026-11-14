# First Race Ladder — Local 1v1

## Goal

Prove the smallest useful end-to-end competition: one pinned SingularityBot build plays three independent 1v1 matches, facing one built-in StarCraft II Computer opponent as each race:

1. Terran
2. Protoss
3. Zerg

This is a local development ladder, not public matchmaking, a rated ladder, or a tournament service.

## Match profile

- Entrant: one immutable SingularityBot build reference (version plus SHA-256).
- Opponent: one native SC2 Computer player, with race fixed per match.
- Format: 1v1; one bot-controlled participant and one SC2 Computer participant.
- Schedule: three matches, one per opponent race, run sequentially.
- Bot race: Terran for the first pass, matching SingularityBot's current product objective; do not assume Random or multi-race support.
- Map and Computer difficulty: trusted host configuration, identical across all three matches.
- Game version, data build, map identity/hash, bot build hash, opponent race, and difficulty: recorded in each match manifest.
- No client-supplied executable paths, map paths, process arguments, or port assignments.

Each match is a fresh game. The ladder advances only after the previous match has a host-validated terminal result and replay evidence. A failed launch, timeout, missing result, or invalid replay is recorded as infrastructure failure—not a bot loss.

## Required topology

The intended host topology remains one neutral SC2 observer/simulation-host process plus one isolated player SC2 process and one SingularityBot runner. The observer creates the game with exactly one Participant and one Computer PlayerSetup; the observer joins with an explicitly configured observed-player perspective; the SingularityBot runner joins the player process. The Computer race changes between the three matches.

The observer must not be replaced by the bot process, and the bot must not receive observer/global vision. The existing legacy two-runner production runtime is not the implementation of this profile.

## Acceptance gates

### A. Bot readiness

- SingularityBot has a reproducible build and a runnable headless runner.
- Its selected race, command-line contract, and SC2 API compatibility are explicit.
- It can complete a controlled local 1v1 against a Computer opponent without host-side strategy or adapter changes.

### B. SC2 protocol

- A pinned local SC2 build accepts observer-hosted CreateGame with one Participant and one Computer.
- The observer and player connections join successfully.
- The bot's assigned player ID and the Computer's player ID are unambiguous.
- GameInfo and fog-respecting observations are captured for observer and player.
- A controlled visibility scenario proves the player does not receive observer-only information.

### C. Match lifecycle and evidence

- The host observes authoritative SC2 terminal results; runner stdout markers are diagnostic only.
- The observer saves the replay.
- ReplayInfo independently validates map, game build, and player results against the match assignment.
- The host persists a terminal match record with the immutable bot build, opponent race, result, replay hash, and evidence references.
- Process and port cleanup is bounded and verified.

### D. Three-match ladder

- The same bot build, map, bot race, Computer difficulty, and game build are used for all three matches.
- Only the Computer opponent race changes: Terran, Protoss, Zerg.
- All three match records are independently valid before the ladder is marked complete.
- Summaries report wins/losses/draws and infrastructure failures separately; no rating is calculated from this three-game smoke ladder.

## Current readiness

**Not runnable yet.** The repository's current production supervisor is still the legacy two-player competitor-host implementation. The opt-in probe can attempt the two-player observer setup and capture post-join GameInfo/Observation snapshots, but it has not yet been run against a real local SC2 installation. The schema-backed CreateGame builder and opt-in `--race-match` path now exercise one Participant plus an explicitly raced/difficulty-configured Computer opponent, using two SC2 processes and capturing GameInfo/Observation snapshots. The participant JoinGame is sent by the probe harness; it does not launch SingularityBot. Actual bot-runner launch/attachment, controlled visibility proof, authoritative terminal result capture, replay save/validation, and the three-match scheduler remain outstanding.

The SingularityBot development branch is actively implementing a Terran economy/production player and has regression coverage plus a headless runner entry point. Its roadmap still distinguishes automated tests from match-verified behavior: the full opening, movement, tactical safety, and intended outcome need a real SC2 match/replay. That is a separate readiness gate; this ServerSC2 repository must not change its strategy or bot-side protocol adapter.

## Implementation order

1. Prove a single local SC2 game with one Participant and one Computer for each opponent race using a dedicated opt-in harness.
2. Prove the selected SingularityBot build can join and play that game.
3. Capture controlled observer/player visibility evidence.
4. Add observer-authoritative terminal result and replay validation.
5. Implement the sequential three-match runner and durable ladder summary.
6. Only then call the local race ladder runnable.

No production topology replacement, merge, release, publication, deployment, or branch deletion is authorized by this plan.
