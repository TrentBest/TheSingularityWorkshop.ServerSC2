# SimulationServer: observer-hosted 1v1 match orchestration

## Intent

ServerSC2 should behave as a SimulationServer: it owns one authoritative StarCraft II match, but neither competitor owns game creation. The target topology uses one dedicated SC2 simulation-host process that joins as an observer, two player SC2 processes, and two independently admitted bot runners.

See [OBSERVER_HOST_DESIGN.md](OBSERVER_HOST_DESIGN.md) for the candidate startup sequence, fairness constraints, port-allocation questions, and proof gates.

```text
ServerApp: immutable MatchAssignment (participant A + participant B)
  -> ServerSC2.ServerAppAdapter
  -> SimulationServer / ISc2SessionRuntime
       1. validate assignment and trusted SC2 profile
       2. resolve and hash-verify both immutable runner artifacts
       3. allocate observer + two player listener ports and complete multiplayer PortSet footprint
       4. launch dedicated SC2 simulation host
       5. create trusted multiplayer map and join simulation host as observer
       6. launch two player SC2 instances
       7. launch runner A and runner B, each attached only to its own player listener
       8. verify observer readiness and both distinct player join identities
       9. observe authoritative lifecycle, results, and replay
      10. stop all five child processes and release the match lease
```

This is the target flow. The exact order and PortSet semantics must be established by live integration proof. The current source runtime still launches two SC2 processes and two runners with one competitor designated as CreateGame host; that implementation is not yet the observer-host topology.

## Authority and isolation

- ServerApp is authoritative for admitted participant/build identities and match assignment.
- SimulationServer is authoritative for process ownership, match startup, lifecycle observation, and host-collected artifacts.
- SC2 is authoritative for game state and terminal player result.
- The observer process has no competitor identity and must not submit player actions.
- Each runner connects only to its own player SC2 listener. Observer observations, global vision, replay state, and observer-derived hidden information must never be forwarded to a bot.
- A runner exit code is diagnostic evidence, never a winner declaration.
- A match is Ready only after the observer and both player runners are connected and protocol-ready.
- A match is Completed only after terminal SC2 result evidence is captured and correlated to both acknowledged player IDs and immutable participant assignments.
- Replay evidence is associated with immutable match ID, session ID, game version, map ID, and both build hashes.

No inferred winner, missing result, incomplete participant set, or ambiguous lifecycle is converted into a successful match. Fail closed and retain diagnostics. Do not fall back to competitor-hosted mode if observer startup fails.

## Fairness policy

Both players must use the same pinned game version, map, game settings, and equivalent resource budgets. Player slot and starting-location assignment must be randomized or alternated under trusted match policy rather than permanently mapping assignment order to a favored spawn. Record assigned slots, start locations, process limits, build hashes, and evidence hashes.

The observer-host role removes the designated-competitor-host asymmetry; it does not by itself eliminate hardware, scheduling, latency, map-side, or resource asymmetries.

## Trusted launch policy

Executable paths, runtime installation, fixed runner arguments, environment variables, working directories, map selection, output roots, process limits, and port allocation are trusted host configuration. Participant metadata supplies identity and immutable build references only. Resolve those references through the admitted artifact registry; never accept arbitrary client paths or raw command lines.

## Process supervision

The current concrete runtime owns two SC2 process handles and two runner process handles, marker-based readiness/result observation, and process-tree termination. The observer-host implementation must extend supervision to three SC2 processes and two runners and must:
- resolve each admitted immutable build through a trusted artifact resolver and verify its SHA-256 before launch;
- create and join the observer process without granting CreateGame to a competitor;
- validate observer readiness and correlate each player result to that player's join acknowledgement;
- persist bounded per-process stdout/stderr logs;
- enforce match-duration, memory, and CPU budgets;
- capture SC2-authoritative result and replay evidence from the observer channel;
- prove cleanup idempotence under cancellation, timeout, protocol failure, and partial startup;
- preserve crash diagnostics and partial replay artifacts without marking the match completed.

## Implementation sequence

1. Prove CreateGame followed by observer join on the pinned SC2 build, including `observed_player_id = 0` semantics.
2. Derive and test the complete observer-plus-two-player PortSet allocation.
3. Implement the observer-host process lifecycle and remove competitor CreateGame arguments.
4. Complete trusted artifact resolution and SHA-256 verification for each immutable bot build.
5. Add contract tests for observer readiness, player identity correlation, isolation, topology, and partial-start cleanup.
6. Run three real SC2 processes and both SingularityBot runners on a machine with the configured SC2 installation and map.
7. Validate terminal result mapping, observer replay capture, fairness metadata, and bounded cleanup in a local integration run.
8. Add append-oriented durable session journal and idempotent result handoff to ServerApp.
