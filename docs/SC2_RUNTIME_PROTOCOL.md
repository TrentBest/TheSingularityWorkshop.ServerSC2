# SC2 Runtime Protocol Notes

This document separates verified SC2API behavior, verified SingularityBot implementation details, and unresolved ladder-host integration details.

## Verified SC2API facts

- The SC2API is a protobuf protocol over WebSockets. The game API endpoint is /sc2api.
- The WebSocket listener address and port are configured on the SC2 process command line with -listen and -port.
- Blizzard's protocol documentation describes multiplayer setup as launching two game instances on separate ports, designating a host, sending Request.create_game, and sending Request.join_game from both clients.
- The SC2API protocol exposes game lifecycle status values including launched, init_game, in_game, ended, and quit.

References:
- https://github.com/Blizzard/s2client-proto/blob/master/docs/protocol.md
- https://github.com/Blizzard/s2client-proto/blob/master/s2clientprotocol/sc2api.proto
- https://blizzard.github.io/s2client-api/classsc2_1_1_coordinator.html

## Verified SingularityBot source contract

Repository: https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot, branch development.

- src/SingularityBot/Program.cs treats the run as local only when no connection arguments remain. Otherwise it calls GameConnection.RunLadder.
- src/SingularityBot.Runner/Program.cs forwards ladder arguments to the bot program. The runner is therefore the host-facing executable entry point.
- src/SC2API.CSharp/GameConnection.cs implements RunLadder as: connect to gamePort, call JoinGameLadder(race, startPort), then enter the observation/action loop.
- JoinGameLadder derives SC2 multiplayer port sets from the supplied start port: shared port = start + 1; server game/base ports = start + 2/+3; client game/base ports = start + 4/+5. It requests raw and score interface data.
- StartSC2Instance launches the SC2 executable with -listen, -port, and -displayMode 0. That is used by the local-game path, not by RunLadder.
- CreateGame creates a local game with one participant and one built-in computer opponent. It is not a two-bot match creator.
- The ladder CLI parser accepts --GamePort / -g, --StartPort / -o, and --OpponentId. Its parser advances in name/value pairs; the server must emit only supported, correctly paired arguments.

Source links:
- https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/blob/development/src/SC2API.CSharp/GameConnection.cs
- https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/blob/development/src/SC2API.CSharp/CLArgs.cs
- https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/blob/development/src/SingularityBot/Program.cs
- https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/blob/development/src/SingularityBot.Runner/Program.cs

## Bot runner vs simulation host

The bot's ladder path is a participant client. It does not launch the authoritative simulation, create the match, or supervise its opponent. ServerSC2 must host the simulation and launch two independent runner processes from the two immutable admitted build references. Do not call RunSinglePlayer twice: that would create two separate bot-vs-computer sessions, not a 1v1 match.

## Unresolved topology gate

The code proves the arithmetic of the StartPort bundle but does not, by itself, prove how the external ladder manager allocates and shares these ports between two bot clients. Blizzard's documented multiplayer setup also describes two SC2 instances in its client-managed workflow. Before launching real matches, verify:

1. whether the hosted competition topology is one shared SC2 process or two coordinated SC2 instances;
2. which endpoint each runner connects to;
3. whether both runners receive the same GamePort, and whether they receive the same or distinct StartPort values;
4. which process owns CreateGame / host designation in this topology;
5. how the server observes authoritative player results and requests/saves replay artifacts.

Do not infer these details from parameter names. The current ServerSC2 port lease reserves one game port and one start-port base per match; it is not yet proven sufficient for the two-runner allocation.

## Readiness and completion rules

- An open TCP port or live process is not protocol readiness.
- Each runner must complete its SC2 protocol join and be associated with the expected participant identity.
- A match is Ready only when the authoritative simulation and both admitted runners are ready.
- A runner exit code is not a win/loss result.
- A match is Completed only after SC2 reports terminal state and the host validates the player-result mapping.
- Replay and result artifacts must be bound to match/session identity, game/map version, and both bot build hashes.
- Ambiguous topology, missing result, mismatched identity, or partial startup fails closed.

## Implementation gate

The ISc2SessionRuntime seam is the right place for the concrete SimulationServer. Implement its process supervisor only after the topology questions above are resolved. The runtime must own fixed host launch arguments, both runner process trees, protocol-level readiness, authoritative result/replay capture, and bounded cleanup.
