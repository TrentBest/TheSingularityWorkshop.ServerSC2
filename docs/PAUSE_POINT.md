# ServerSC2 Pause Point

## Current state

- Active work is on `development`; the repository currently has exactly `master` and `development`.
- The current production `Sc2ProcessSessionRuntime` is still the legacy two-player competitor-host implementation: two SC2 processes, two runners, and CreateGame authority assigned to one participant. It is not the observer-host target.
- Runner `SC2_JOINED` markers are used for readiness/player-ID correlation. Runner `SC2_RESULT` markers are diagnostic only. The runtime's completion gate is deliberately fail-closed: it remains Running until independently validated host-authoritative terminal results AND validated replay evidence are supplied. Neither evidence source is wired into production runtime yet.
- The production runtime still requires exactly two participants. Team IDs and the observer-oriented process plan do not make the supervisor format-general.
- A first host-side evidence contract now exists in `Sc2MatchEvidence.cs`: schema-v1 evidence binds the immutable participant/build assignment, observer session/process identity, host-owned JoinGame player-ID bindings, explicit SC2 terminal status, per-player results, replay artifact identity/size/digests, map identity, and replay build metadata. Its validator rejects missing/duplicate/unknown participant identities, Undecided results, replay-result disagreement, digest/size failures, and provenance mismatches.
- The completion gate now accepts only a `Sc2MatchEvidenceValidation` object produced by the validator; caller-supplied booleans are no longer sufficient. The production runtime currently passes no evidence (`null`) and therefore remains Running. The evidence contract is not yet populated by a live observer controller or durable artifact store.
- `Sc2MatchProcessPlan` is a validated intermediate contract for one neutral observer plus N player SC2 clients and N runners. It is not consumed by the production supervisor.
- `ISc2BotRunnerResolver` is only a trusted resolution boundary. A production implementation must resolve immutable build IDs and verify each artifact against its admitted SHA-256 before launch.
- The port lease model scales observer-plus-participant reservations, but reservations are process-local; they are not OS socket reservations or proof that SC2 accepts the candidate PortSet layout.
- No live SC2 observer-host match, controlled-visibility proof, terminal-result capture, replay validation, or full process-cleanup proof has been established.

## Standalone SC2 protocol probe

The opt-in developer harness is implemented under `tools/sc2-probe/`. It uses pinned developer-only dependencies (`s2clientprotocol==5.0.17.98310.0` and `websocket-client==1.9.2`); these are not ServerSC2 production dependencies.

The probe has distinct evidence levels:

1. **Default bootstrap:** only with explicit `--execute`, preflights trusted paths/ports/version inputs, launches three isolated SC2 processes, sends RequestPing to each API endpoint, records build metadata/logs, and performs bounded cleanup.
2. **Opt-in setup sequence:** additionally requires `--setup-sequence` and explicit observer perspective, player races, server PortSet, and repeated client PortSets. It attempts observer-hosted CreateGame, observer JoinGame, and both player JoinGame requests; after acknowledgements it captures GameInfo and fog-respecting raw Observation snapshots from all three connections.
3. **Opt-in race match setup:** `--race-match` attempts one Participant plus a native Computer opponent and captures setup observations. The probe itself joins the player endpoint; it does not launch SingularityBot.

These are protocol/bootstrap/setup milestones, not a played SingularityBot match. Successful setup acknowledgements do not prove observer perspective semantics, player information isolation, supported three-client PortSet behavior, terminal results, replay validity, or production readiness. The controlled visibility scenario, authoritative terminal observation, replay capture/metadata cross-check, and complete lifecycle proof remain open. CI uses fake protocol transports and never launches SC2.

See [SC2 runtime protocol notes](SC2_RUNTIME_PROTOCOL.md) for exact invocation inputs, request/evidence semantics, and unresolved live questions.

## SingularityBot integration boundary

SingularityBot remains independently owned and must not be modified as a ServerSC2 workaround. The current runner's existing ladder CLI contract is recorded in [the first race ladder plan](FIRST_RACE_LADDER.md): `--GamePort`, `--StartPort`, and `--OpponentId`. This is an observed compatibility detail, not the generic ServerSC2 runner contract. The first planned smoke ladder is one Terran bot against native Computer opponents of Terran, Protoss, and Zerg; it is not a claim that the bot plays all three races or is ladder-ready.

ServerSC2 must eventually prove the existing runner against a real supported SC2 installation using immutable build resolution and a compatible trusted port allocation. Do not infer live compatibility from source inspection, fake sockets, or successful protocol setup performed by the probe itself.

## Cross-repository runner contract status

- SingularityBot responded to [Issue #13](https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/issues/13) on 2026-11-14 with source-backed findings, runner-side primitives, a v1 contract document, and deterministic player-result resolver tests. Reported revision: `997a7c4af2c769bc978e0183b4a93659c15f0f05` on `development`.
- The response identifies `RunLadder` / `Connect(gamePort)` as the existing attach-to-host-launched-process path. It reports new `GameConnection.JoinObserver`, one-shot typed `Observe`, `SaveReplay`, and `GetReplayInfo` primitives, plus player-result resolution by explicit `PlayerResult.PlayerId`. See [runner contract v1](https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/blob/development/docs/server-sc2-runner-contract-v1.md).
- The runner response explicitly does not claim live proof of the three-client topology or observer perspective. Its proxy also discards the original WebSocket response frame; byte-exact raw evidence must therefore be captured by a host-owned observer transport or addressed by a separately reviewed runner API change.
- **Unresolved contract discrepancy:** the runner contract says the first participant may issue CreateGame and then join as Participant A, while ServerSC2's opt-in probe documentation describes CreateGame on the observer connection before observer and participant joins. Do not silently choose between these sequences. Reconcile the intended game-creation owner and prove the selected sequence against the pinned SC2 build before production wiring.
- ServerSC2 remains responsible for process-tree supervision, cancellation/timeouts, assignment authority, raw evidence provenance, bounded replay persistence/hash, immutable evidence, and fail-closed completion. Do not modify SingularityBot as a workaround; coordinate any further runner changes through its issue.
- The production runtime remains the legacy two-participant/two-runner topology. The newly documented runner primitives do not automatically integrate into ServerSC2 or establish live compatibility.

## Next implementation gates

1. Reconcile the CreateGame ownership discrepancy between the runner v1 contract and ServerSC2's observer-host probe sequence. Select one explicit protocol sequence and prove it on a pinned SC2 build; do not assume the third-client topology or `observed_player_id` perspective from schema comments.
2. Close the standalone probe's remaining live gates: validate observer perspective and PortSet layout; prove controlled player/observer information separation; observe a real terminal state; save/read/cross-check replay evidence; and prove bounded cleanup on success and failure.
3. Wire a host-owned observer controller into production only after the selected protocol sequence is proven. It must own process supervision, observer readiness, lifecycle polling, terminal results, and replay capture. Never fall back to runner stdout or an unproven competitor-host topology.
3. Add immutable, versioned evidence bound to match/session IDs, map and SC2 build, participant/player IDs, admitted build IDs and SHA-256s, terminal results, replay identity/hash/size, timestamps, and validation diagnostics. Bound artifact storage and clean up partial writes/cancellation.
4. Replace fixed-two-participant runtime assumptions only alongside verified SC2 player/team/port semantics and format-aware result validation. Keep the generic runner contract independent of SingularityBot-specific flags.
5. Implement and test trusted artifact resolution with SHA-256 verification before runner launch.
6. Publish machine-readable deterministic test results and bounded artifacts for CiAi. The currently verified CI workflow is `.github/workflows/ci.yml`, job `build-and-check`, with lanes `Run SC2 probe preflight tests`, `Build core`, `Build ServerApp adapter`, and `Run contract checks`. It uploads `server-sc2-contract-check-results` containing `contract-check-results.json` with 14-day retention, including on failure when the report exists. It does not publish TRX. The contract-check project is currently a `net8.0` console executable (`OutputType=Exe`) invoked with `dotnet run`, not an SDK test project; adding `--logger trx` to this command would not create valid VSTest results. If TRX becomes necessary for CiAi, first introduce a real test-runner project or a deliberate, schema-documented report adapter, then prove failure-path artifact publication. CiAi owns artifact provenance normalization and the CI verdict/handoff.
7. Run a real SingularityBot runner integration and at least one independent runner through the generic contract. A setup probe that does not launch the runner is not this proof.

## Verification and authorization boundaries

The current development CI verifies Python probe tests, .NET builds, and contract checks. It does not launch SC2 and does not prove live protocol behavior. A green workflow is code/contract evidence only.

Issue [#1](https://github.com/TrentBest/TheSingularityWorkshop.ServerSC2/issues/1) tracks host-authoritative terminal results and replay evidence. CiAi owns CI-provider evidence normalization and verdict/handoff; HeadlessAi consumes the bounded report; the host retains lifecycle, budgets, and authorization.

No merge, package publication, release, deployment, or branch deletion is authorized by this work. No live SC2 support claim should be made until the corresponding live evidence exists.
