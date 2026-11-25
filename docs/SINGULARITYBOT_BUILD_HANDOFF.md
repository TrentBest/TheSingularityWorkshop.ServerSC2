# SingularityBot build handoff

## Purpose

ServerSC2 launches the bot build pinned by an admitted ServerApp BotBuildReference. A build reference is not an executable path. The host resolves it through a trusted, immutable package store; the participant never chooses a filesystem path, executable, command line, or definition.

For SingularityBot, the package contains both the compatible SingularityBot.Runner payload and the exact portable BotDefinition JSON exported by Studio. ServerSC2 launches the resolved Runner with its existing --definition=<absolute-host-resolved-path> option. The Runner performs strict BotDefinition.Parse and semantic validation before it opens the SC2 connection. A Runner that rejects the definition cannot report the protocol-level join acknowledgement, so the host cannot return Ready.

## Content-addressed package layout

The configured host-owned package store uses this layout:

    {store-root}/
      {BotIdentityId}/
        {BuildId}/
          {ContentSha256}/
            bot-build.json
            SingularityBot.Runner.exe
            SingularityBot.dll
            ...all other runner dependencies...
            bot-definition.json

BotIdentityId and BuildId are restricted to safe single path segments. ContentSha256 is the SHA-256 of a canonical payload index, not the hash of a mutable directory or an arbitrary client-supplied path.

bot-build.json is strict JSON (unknown properties are rejected) with this version-1 shape:

    {
      "schemaVersion": 1,
      "contentSha256": "<64-hex SHA-256>",
      "runnerExecutablePath": "SingularityBot.Runner.exe",
      "botDefinitionPath": "bot-definition.json",
      "files": [
        { "path": "SingularityBot.Runner.exe", "sha256": "<64-hex SHA-256>" },
        { "path": "SingularityBot.dll", "sha256": "<64-hex SHA-256>" },
        { "path": "bot-definition.json", "sha256": "<64-hex SHA-256>" }
      ]
    }

The files collection lists every payload file required by the build, including all runtime dependencies and the definition. Paths use normalized / separators, are relative to the package root, and cannot contain empty, . or .. segments. The manifest itself is excluded from the payload list to avoid a self-referential digest.

To compute ContentSha256:

1. Verify each listed file's SHA-256 against its manifest entry.
2. Validate runnerExecutablePath and botDefinitionPath as normalized relative paths, and require both paths to appear in the files collection.
3. Begin the canonical UTF-8 payload index with these exact lines, including LF line endings:
   - runnerExecutablePath
   - the exact runnerExecutablePath value
   - botDefinitionPath
   - the exact botDefinitionPath value
4. Sort file entries by path using ordinal comparison. For each entry append: path, LF, lowercase hexadecimal sha256, LF.
5. SHA-256 the resulting UTF-8 byte sequence; encode the result as 64 hexadecimal characters.

The resulting digest must equal both bot-build.json contentSha256 and the admitted BotBuildReference.ContentSha256. Including the two role paths in the digest prevents a manifest from changing which payload is executed as the Runner or loaded as the BotDefinition without changing the build identity. ServerSC2 independently verifies the Runner and definition file hashes before launch.

The package store must be writable only by the trusted build-registration pipeline. A matching digest proves payload integrity; admission and the trusted registry establish which bot identity/build is authorized to use that payload. Never expose the package-store root as a client write location.

## Launch sequence

1. ServerApp admits an immutable assignment and pins each participant's bot identity, build ID, and content digest.
2. ServerSC2 resolves each participant's exact package from the host-owned store.
3. It parses the strict package manifest, validates every listed path, verifies every file hash, recomputes the canonical package digest, and verifies the exact Runner and BotDefinition payloads.
4. It completes this resolution for every participant before starting any SC2 or Runner process. A missing or altered package fails startup without partially launching the match.
5. For each participant, ServerSC2 starts the trusted Runner with fixed host-owned ladder arguments and --definition=<resolved-definition-path>. Participant A alone receives the host-owned --CreateGame --Map <trusted-map-path> arguments.
6. The Runner parses and semantically validates the BotDefinition before connecting to SC2. ServerSC2 returns Ready only after both participants report distinct protocol-level player IDs.
7. Runner stdout result markers remain diagnostic only. Match completion still requires separately validated observer terminal results and replay evidence.

## Trust boundaries

- No client-supplied path or arbitrary runner argument is accepted.
- No arbitrary assembly, script, reflection name, method, shell command, or executable expression is loaded from BotDefinition.
- BotDefinition schema and domain validation remain owned by SingularityBot.
- ServerApp owns build registration, immutable admission, and the authoritative build reference.
- ServerSC2 owns trusted package resolution, process launch, readiness, and SC2 evidence.
- The current process runtime is the 1v1 participant-host path. The separate neutral-observer topology and live SC2 proof remain independent gates; this package handoff does not claim those gates are complete.

## Implementation status

The ISc2BotRunnerResolver contract now returns a complete Sc2BotRunnerArtifact, not just an executable path. FileSystemSc2BotRunnerResolver implements the content-addressed layout above. Sc2ProcessSessionRuntime validates all packages before process creation and passes the exact definition path through the Runner's existing CLI contract.

A trusted build-registration/publishing pipeline must produce this package layout and manifest before the ladder can launch a registered build. No NuGet publication, release, Pages deployment, or live SC2 match is implied by this contract.
