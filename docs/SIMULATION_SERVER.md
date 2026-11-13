# SimulationServer: observer-hosted SC2 match orchestration

## Intent

ServerSC2 owns one authoritative StarCraft II match for any admitted, SC2-supported competition format. A match consists of a dedicated SC2 simulation-host process that joins as an observer, plus one player SC2 process and one independently launched bot runner per entrant.

The match assignment—not hard-coded host logic—defines participant count, entrant/build identities, team grouping, and format. The target includes 1v1, 2v2, 3v3, FFA, and multi-team formats such as 2v2v2, subject to proven SC2 limits and game setup semantics.

See [OBSERVER_HOST_DESIGN.md](OBSERVER_HOST_DESIGN.md) for process roles, generic bot compatibility, candidate startup sequence, fairness constraints, port allocation, and proof gates.

```text
ServerApp: immutable MatchAssignment (N entrants + teams + format)
  -> ServerSC2.ServerAppAdapter
  -> SimulationServer / ISc2SessionRuntime
       1. validate assignment, format, and trusted SC2 profile
       2. resolve and hash-verify every immutable runner artifact
       3. allocate observer + N player listener ports and complete multiplayer PortSet footprint
       4. launch dedicated SC2 simulation host
       5. create trusted game and join simulation host as observer
       6. launch N player SC2 instances
       7. launch N independent runners, each attached only to its own player listener
       8. verify observer readiness and all unique player join identities
       9. observe authoritative lifecycle, format-aware results, and replay
      10. stop all child processes and release the match lease
```

This is the target flow. The exact order, team mapping, and PortSet semantics must be established by live integration proof. The current source runtime still launches two SC2 processes and two runners with one competitor designated as CreateGame host; that implementation is neither observer-hosted nor format-general.

## Authority and isolation

- ServerApp is authoritative for admitted entrant/build identities, match assignment, team grouping, and competition format.
- SimulationServer is authoritative for process ownership, match startup, lifecycle observation, and host-collected artifacts.
- SC2 is authoritative for game state and terminal player results.
- The observer process has no competitor identity and must not submit player actions.
- Each runner connects only to its own player SC2 listener. Observer observations, global vision, replay state, and observer-derived hidden information must never be forwarded to any bot.
- A runner exit code is diagnostic evidence, never a winner declaration.
- A match is Ready only after the observer and every player runner are connected and protocol-ready.
- A match is Completed only after terminal SC2 result evidence is captured and correlated to every acknowledged player ID and immutable entrant/team assignment.
- Result semantics are format-aware: team wins, FFA placements, draws, ties, disconnects, and forfeits must be preserved rather than reduced to a two-player winner/loser pair.
- Replay evidence is associated with immutable match/session identity, game version, map ID, format, and all entrant build hashes.

No inferred winner, missing result, incomplete participant set, or ambiguous lifecycle is converted into a successful match. Fail closed and retain diagnostics. Do not fall back to competitor-hosted mode if observer startup fails.

## Fairness policy

All player clients use the same pinned game version, map, game settings, and equivalent resource budgets. Player slot and starting-location assignment must be randomized or rotated under trusted match policy while preserving team groupings. Record entrant-to-player mapping, team IDs, assigned slots, start locations, process limits, build hashes, and evidence hashes.

The observer-host role removes the designated-competitor-host asymmetry; it does not by itself eliminate hardware, scheduling, latency, map-side, or resource asymmetries.

## Generic bot compatibility

The host accepts any admitted bot build that implements the documented runner/SC2API compatibility contract. It does not require SingularityBot assemblies, strategy, or CLI conventions. SingularityBot (including its ExampleBot foundation) is a toolkit developers can choose to use; it is not the ladder's execution dependency. A separate compatibility shim may adapt a particular runner package, but that shim must remain outside generic match orchestration.

## Trusted launch policy

Executable paths, runtime installation, fixed runner arguments, environment variables, working directories, map selection, output roots, process limits, and port allocation are trusted host configuration. Entrant metadata supplies identity, immutable build references, and approved team/format assignment only. Resolve build references through the admitted artifact registry; never accept arbitrary client paths or raw command lines.

## Process supervision

The current concrete runtime owns two SC2 process handles and two runner process handles, marker-based readiness/result observation, and process-tree termination. The target supervisor must extend to one observer plus N player SC2 processes and N runners and must:
- resolve each admitted immutable build through a trusted artifact resolver and verify its SHA-256 before launch;
- create and join the observer process without granting CreateGame to a competitor;
- validate observer readiness and correlate each player result to that player's join acknowledgement and team;
- persist bounded per-process stdout/stderr logs;
- enforce match-duration, memory, and CPU budgets per entrant;
- capture SC2-authoritative format-aware result and replay evidence from the observer channel;
- prove cleanup idempotence under cancellation, timeout, protocol failure, and partial startup;
- preserve crash diagnostics and partial replay artifacts without marking the match completed.

## Implementation sequence

1. Prove CreateGame followed by observer join on the pinned SC2 build, including `observed_player_id = 0` semantics.
2. Derive and test the complete PortSet allocation for observer plus N player clients.
3. Prove player/team setup and terminal result semantics for each enabled match format.
4. Implement the observer-host process lifecycle and remove competitor CreateGame arguments.
5. Define the generic runner contract and prove both a SingularityBot runner and an independent bot can attach.
6. Complete trusted artifact resolution and SHA-256 verification for every immutable entrant build.
7. Add contract tests for variable participant counts, team identity, observer readiness, result mapping, isolation, and partial-start cleanup.
8. Run real SC2 integration matches at 1v1 and at least one team/FFA format.
9. Validate terminal result mapping, observer replay capture, fairness metadata, and bounded cleanup in local integration.
10. Add append-oriented durable session journal and idempotent result handoff to ServerApp.

