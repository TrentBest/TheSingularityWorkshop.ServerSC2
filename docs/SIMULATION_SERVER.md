# SimulationServer: hosted 1v1 match orchestration

## Intent

ServerSC2 should behave as a SimulationServer: it creates and owns one authoritative StarCraft II match, then launches and connects two independently admitted bot runners to that match. It is not two local single-player sessions and it is not two copies of SingularityBot's local-game path.

~~~text
ServerApp: immutable MatchAssignment (participant A + participant B)
  -> ServerSC2.ServerAppAdapter
  -> SimulationServer / ISc2SessionRuntime
       1. validate assignment and trusted SC2 profile
       2. allocate match-scoped ports and artifact directory
       3. launch two SC2 instances with distinct WebSocket listener ports
       4. designate/create the multiplayer game on the host instance
       5. launch SingularityBot runner A from admitted build A
       6. launch SingularityBot runner B from admitted build B
       7. connect each runner to its assigned SC2 listener and complete the multiplayer join
       8. observe authoritative game lifecycle and result
       9. capture replay, logs, and result evidence
       10. stop both SC2 and both runner process trees; release all resources
~~~

The two SC2 processes have separate listener ports; one is the multiplayer host and one is the joining client. Each runner connects to its assigned SC2 listener. The two runner processes are independent: separate process identities, build hashes, working directories, bounded resource budgets, stdout/stderr streams, exit observations, and participant identities. Neither runner receives authority to launch or reconfigure the SC2 host.

## Reuse the existing SingularityBot client

The current bot source already provides the player-side entry point:

- SingularityBot.Program.Run distinguishes local mode (no connection arguments) from ladder mode.
- A ladder run calls GameConnection.RunLadder.
- RunLadder connects to the supplied game port, then calls JoinGameLadder with the supplied start port and opponent ID.
- StartSC2Instance and CreateGame belong to the local single-player path. The SimulationServer must not invoke that path for either competition participant.

The host should launch the approved runner artifact with the documented ladder arguments, not embed strategy code or create a second protocol client. The host-designated runner receives `--CreateGame --Map <trusted-map-path>`; it connects to its SC2 listener, creates the multiplayer game with two participant slots, then performs the normal ladder join on that same connection. The second runner only joins. Both runners receive distinct GamePort values because they connect to separate SC2 listener processes, but both receive the same match-level StartPort base and therefore the same shared/server/client PortSet values. Blizzard's coordinator uses one shared ports structure for both join requests. The current allocator still needs to be upgraded to reserve two listener ports plus the shared five-port multiplayer block atomically; see SC2_RUNTIME_PROTOCOL.md.

## Authority and evidence

- ServerApp is authoritative for admitted participant/build identities and match assignment.
- SimulationServer is authoritative for process ownership, match startup, lifecycle observation, and host-collected artifacts.
- SC2 is authoritative for game state and terminal player result.
- A runner exit code is diagnostic evidence, never a winner declaration.
- A match is Ready only after the SC2 simulation and both runners are connected and protocol-ready.
- A match is Completed only after the SC2 terminal state and participant result mapping are captured and validated.
- Replay evidence is associated with immutable match ID, session ID, game version, map ID, and both build hashes.

No inferred winner, missing result, incomplete participant set, or ambiguous lifecycle is converted into a successful match. Fail closed and retain diagnostics.

## Trusted launch policy

Executable paths, runtime installation, fixed runner arguments, environment variables, working directories, map selection, output roots, process limits, and port allocation are trusted host configuration. Participant metadata supplies identity and immutable build references only. Resolve those references through the admitted artifact registry; never accept arbitrary client paths or raw command lines.

## Process supervision

The concrete runtime must:
- retain process handles for both SC2 instances and both bot runners;
- redirect and continuously drain stdout/stderr to bounded per-process logs;
- enforce startup, readiness, match-duration, memory, CPU, and shutdown budgets;
- detect early process exit without treating it as a game result;
- terminate child process trees on cancellation, timeout, protocol failure, and host disposal;
- make cleanup idempotent and release port leases only after owned processes are stopped or definitively abandoned with an explicit failure record;
- preserve crash diagnostics and partial replay artifacts without marking the match completed.

## Implementation sequence

1. Upgrade the lease model to reserve two distinct SC2 listener ports and one shared match StartPort base plus offsets `+1..+5` atomically.
2. Add a typed per-participant runner launch contract derived from the immutable assignment, including which participant is the designated host.
3. Implement an injectable process launcher and fake-process contract tests.
4. Implement both SC2 processes, launch the host runner with `--CreateGame --Map`, launch the joining runner without that flag, and add protocol-level health checks.
5. Launch two real SingularityBot runner processes, each attached to its assigned SC2 instance.
6. Validate readiness, terminal result, replay capture, and bounded cleanup in a local integration run.
7. Add append-oriented durable session journal and idempotent result handoff to ServerApp.

This document describes the intended vertical slice. It does not claim the process supervisor or two-runner integration already exists.
