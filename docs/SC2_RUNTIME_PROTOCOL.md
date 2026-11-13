# SC2 Runtime Protocol Notes

This document separates verified Blizzard protocol behavior, source-inspected bot behavior, implemented ServerSC2 behavior, and unresolved live integration questions. A source-level inference is not a live protocol proof.

## Verified Blizzard SC2API facts

- SC2API is a protobuf protocol over WebSockets. Each SC2 process exposes its API at `/sc2api`; its listener address and port are configured with `-listen` and `-port`.
- Blizzard documents multiplayer setup using separate SC2 instances with separate listener ports.
- A host instance receives `Request.create_game`; participating clients receive `Request.join_game`.
- A join request can carry a `server_ports` PortSet and one or more `client_ports` PortSets. A PortSet contains `game_port` and `base_port`. The deprecated `shared_port` field also exists.
- `RequestJoinGame` supports player participation through `race` and observer participation through `observed_player_id`. Observer actions are a separate request type from player actions.
- SC2 reports lifecycle states including `launched`, `init_game`, `in_game`, `ended`, and `quit`.
- `RequestJoinGame` has distinct player (`race`) and observer (`observed_player_id`) participation modes. `ResponseObservation` can include terminal `player_result` records when the game ends during that observation step.
- `RequestSaveReplay` returns replay bytes, and `RequestReplayInfo` can inspect replay metadata including map, game version/build, and player results. These are candidate observer evidence sources; their behavior and availability in the target lifecycle still require live validation.

These facts establish protocol capabilities, not that the exact observer-host sequence or port layout works on a particular pinned game build.

Primary references:
- https://github.com/Blizzard/s2client-proto/blob/master/docs/protocol.md
- https://github.com/Blizzard/s2client-proto/blob/master/s2clientprotocol/sc2api.proto
- https://github.com/Blizzard/s2client-api/blob/master/src/sc2api/sc2_coordinator.cc

## Source-inspected SingularityBot behavior

Repository: https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot, branch development.

- `src/SingularityBot/Program.cs` treats a run as local only when no connection arguments remain. Otherwise it calls `GameConnection.RunLadder`.
- `src/SingularityBot.Runner/Program.cs` forwards ladder arguments to the bot program. The runner is the host-facing executable entry point.
- `GameConnection.RunLadder` connects to the supplied `gamePort`, calls `JoinGameLadder(race, startPort)`, then enters the observation/action loop.
- Each runner's `GamePort` is the WebSocket listener of the SC2 process to which that runner connects. Two player runners therefore need distinct SC2 listener endpoints/processes.
- `JoinGameLadder` currently builds a join request with `shared_port = startPort + 1`, server PortSet `(startPort + 2, startPort + 3)`, and one client PortSet `(startPort + 4, startPort + 5)`.
- Both runner processes use the same `JoinGameLadder` implementation. Blizzard's C++ coordinator builds one shared `GameSettings.ports` structure in `SetupPorts` and passes that structure to each agent's `RequestJoinGame`. This is the standard coordinator's match-scoped port-set pattern; it is not proof that the current bot payload supports a third observer client.
- The development branch contains a host-only `--CreateGame --Map <trusted-map-path>` mode. The host runner sends `RequestCreateGame` and then joins on the same connection. This flow has not been verified against a running SC2 installation.
- Runners emit `SC2_JOINED playerId=<id>` and `SC2_RESULT playerId=<id> result=<result>` stdout markers. These are untrusted runner diagnostics, not host-authoritative evidence.
- The CLI parser accepts `--GamePort` / `-g`, `--StartPort` / `-o`, and `--OpponentId`. These are SingularityBot implementation details, not a ServerSC2 admission contract.

Source links:
- https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/blob/development/src/SC2API.CSharp/GameConnection.cs
- https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/blob/development/src/SC2API.CSharp/CLArgs.cs
- https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/blob/development/src/SingularityBot/Program.cs
- https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/blob/development/src/SingularityBot.Runner/Program.cs

## Current ServerSC2 implementation (legacy runtime)

The current `Sc2ProcessSessionRuntime` is deliberately still the old two-player competitor-host implementation:

1. It launches two SC2 processes, each with a distinct listener port.
2. It resolves and launches two runner executables using the injected `ISc2BotRunnerResolver` boundary.
3. It currently passes SingularityBot-shaped arguments, including `--OpponentId`, and grants CreateGame to one participant runner.
4. It waits for two runner join markers with distinct player IDs before returning Ready.
5. Runner result markers remain diagnostics. They can be checked for player-ID consistency and early-exit handling, but they cannot complete a match.
6. `GetStatusAsync` currently remains Running unless a runner failure is detected. The fail-closed completion gate requires independently validated host-authoritative terminal results AND validated replay evidence; neither evidence source is wired into this runtime.

The current supervisor is not observer-hosted, is not a generic arbitrary-bot runner contract, and has not been exercised against live SC2. The trusted artifact resolver implementation, authoritative result source, replay capture, durable evidence, and complete live cleanup proof remain outstanding.

## Port-layout derivation (candidate only)

Inspection of Blizzard's `Coordinator::SetupPorts(num_agents, port_start)` establishes the reference coordinator's allocation pattern for N participating clients:

- `shared_port` = base + 1
- `server_ports.game_port/base_port` = base + 2 / base + 3
- each additional client's PortSet (game/base) follows, beginning at base + 4 / base + 5

The reference coordinator therefore allocates a five-port multiplayer block for two clients and a seven-port block for three clients. ServerSC2's observer process-plan reserves a scaled block based on this derivation. This is a candidate allocation model only: it does not prove that an observer is accepted as the third client or that all three join requests must carry an identical repeated PortSet collection.

The current SingularityBot adapter populates only one `client_ports` entry. A three-client observer topology may require a different payload. Do not implement it by merely adding a third SC2 listener while retaining the current one-entry request.

Reference: https://github.com/Blizzard/s2client-api/blob/master/src/sc2api/sc2_coordinator.cc (`Coordinator::SetupPorts`, `CoordinatorImp::JoinGame`).

## Observer-host target topology (not yet proven)

The agreed target topology is one neutral simulation-host/observer process plus one player SC2 process and one bot runner per entrant. The observer alone creates the game, joins as an observer, monitors authoritative lifecycle/results, and captures replay evidence. Competitors never receive CreateGame authority or observer/global vision.

The following remain explicit live proof questions:

- Does the pinned SC2 build accept CreateGame followed by RequestJoinGame(observer) on the same dedicated host connection?
- Does `observed_player_id = 0` provide the intended all-player observer perspective in this multiplayer flow?
- What exact server PortSet and repeated client PortSet collection must be supplied by the observer and every player?
- What is the correct process/join ordering for the pinned build?
- Can player clients be shown not to receive observer-only information?
- Can the observer independently read terminal player results and save a replay, and can those artifacts be correlated to immutable entrant/build/team identities?
- What shutdown sequence reliably cleans up all SC2 and runner process trees after success, timeout, partial startup, and cancellation?

The target design is described in [OBSERVER_HOST_DESIGN.md](OBSERVER_HOST_DESIGN.md). Do not change the production runtime topology until these questions have executable answers on the pinned build.

## Live proof harness acceptance contract

The first implementation milestone is a standalone, opt-in protocol probe—not a production runtime replacement. It must be inert unless explicitly invoked with all required trusted inputs.

Required inputs:
- exact SC2 executable and installation/working-directory paths;
- pinned game build/version and adapter/protocol revision;
- trusted multiplayer map identifier and local map path;
- explicit output directory for logs, replay, and machine-readable evidence;
- bounded startup, join, match, and shutdown timeouts;
- an explicit opt-in flag so ordinary builds and CI contract checks never launch SC2.

The probe must:
1. Preflight the executable, installation, map, output directory, version metadata, and required local port range before starting processes.
2. Allocate a collision-free local listener and candidate multiplayer PortSet block; report every selected port and fail on overlap.
3. Launch a dedicated host process and two isolated player processes, each with its own SC2 API listener.
4. Exercise the exact candidate CreateGame → observer join → player join sequence, recording every request, response, SC2 status transition, process exit, and timeout.
5. Assert that the observer is acknowledged as observer (including the observed player ID) and both players are acknowledged with distinct player IDs.
6. Collect observations from observer and player channels sufficient to test that players cannot see observer-only information.
7. Wait for a real terminal SC2 state, obtain result data from the observer channel, request/save a replay, and validate the replay file exists and is readable.
8. Terminate every process tree in bounded cleanup, including failure paths.
9. Emit a versioned JSON evidence manifest containing build/map/protocol metadata, process roles, port assignments, join acknowledgements, lifecycle timestamps, result records, replay hash/size, logs, cleanup outcomes, and an explicit pass/fail for each gate. Missing evidence is a failure, never an inferred pass.

The harness must not trust runner stdout as authoritative evidence. Its evidence manifest must distinguish protocol observations from diagnostics and retain raw logs for audit. A successful probe proves only the exact pinned build/map/topology exercised; it does not automatically enable other player counts, teams, maps, or game versions.

## Readiness and completion rules

- An open TCP port or live process is not protocol readiness.
- Source inspection and contract tests are not live SC2 verification.
- Runner exit codes and stdout markers are diagnostic only, never win/loss declarations.
- A match is Completed only when independently validated observer-authoritative terminal results AND validated replay evidence are both bound to the immutable match/session, game/map version, and all participant build hashes.
- Ambiguous topology, missing result, mismatched identity, invalid replay, or partial startup fails closed.

## Open bot ladder and variable participant formats

ServerSC2 is a host for compatible SC2 bots, not a SingularityBot-only host. The generic host contract must define only the boundary ServerSC2 needs:

- immutable admitted build identity and content hash;
- trusted runner artifact resolution and SHA-256 verification;
- one assigned player SC2 listener per entrant;
- match-scoped networking configuration for the proven SC2 topology;
- structured protocol join acknowledgement bound to the entrant;
- bounded lifecycle and diagnostic reporting, with observer evidence remaining authoritative.

Do not make `--OpponentId` or any strategy-specific argument mandatory. Opponents and teams are match-level concepts, not a runner's assumption that exactly one opponent exists.

Target formats include 1v1, 2v2, 3v3, FFA, and multi-team formats such as 2v2v2, subject to live verification of player limits, team setup, observer behavior, PortSet semantics, and format-aware results. A compatibility proof must eventually run at least one SingularityBot-based runner and one independent bot through the same generic host contract. Bot strategy and bot-side protocol implementations remain owned by their respective bot projects; ServerSC2 owns orchestration, isolation, fairness, and evidence.
