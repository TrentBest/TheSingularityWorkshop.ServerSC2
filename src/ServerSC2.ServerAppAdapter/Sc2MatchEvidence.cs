namespace ServerSC2.ServerAppAdapter;

/// <summary>Immutable host-owned identity admitted before SC2 process launch.</summary>
public sealed record Sc2ExpectedParticipant(
    string ParticipantId,
    string TeamId,
    string BuildId,
    string BuildSha256);

/// <summary>One participant result captured from the observer's terminal SC2 observation.</summary>
public sealed record Sc2ParticipantResultEvidence(
    string ParticipantId,
    uint Sc2PlayerId,
    string Result);

/// <summary>One player/result entry reported by SC2 replay metadata.</summary>
public sealed record Sc2ReplayPlayerResult(
    uint Sc2PlayerId,
    string Result);

/// <summary>Replay artifact identity and metadata returned by SC2 from the captured replay bytes.</summary>
public sealed record Sc2ReplayEvidence(
    string ArtifactId,
    string Location,
    long SizeBytes,
    string Sha256,
    string VerifiedSha256,
    string MapName,
    string GameVersion,
    string DataVersion,
    uint DataBuild,
    uint BaseBuild,
    IReadOnlyList<Sc2ReplayPlayerResult> PlayerResults);

/// <summary>
/// Versioned evidence envelope. Producers must populate this only after observing SC2 Status.Ended,
/// persisting bounded replay bytes, hashing the persisted bytes, and querying ReplayInfo from those bytes.
/// </summary>
public sealed record Sc2MatchEvidence(
    int SchemaVersion,
    string MatchId,
    string SessionId,
    string AdapterVersion,
    string GameVersion,
    string MapId,
    string MapName,
    string Outcome,
    DateTimeOffset CapturedAtUtc,
    DateTimeOffset TerminalObservedAtUtc,
    IReadOnlyList<Sc2ExpectedParticipant> ExpectedParticipants,
    IReadOnlyList<Sc2ParticipantResultEvidence> TerminalResults,
    Sc2ReplayEvidence Replay);

/// <summary>Immutable validation result. Only the validator can create a passing instance.</summary>
public sealed class Sc2MatchEvidenceValidation
{
    internal Sc2MatchEvidenceValidation(IReadOnlyList<string> diagnostics)
    {
        Diagnostics = Array.AsReadOnly(diagnostics.ToArray());
    }

    public IReadOnlyList<string> Diagnostics { get; }
    public bool IsValid => Diagnostics.Count == 0;
}

/// <summary>
/// Validates the observer terminal observation and replay metadata against the immutable
/// ServerApp assignment. All diagnostics are stable machine-readable codes.
/// </summary>
public static class Sc2MatchEvidenceValidator
{
    public const long DefaultMaximumReplayBytes = 512L * 1024 * 1024;

    public static Sc2MatchEvidenceValidation Validate(
        Sc2MatchEvidence evidence,
        string expectedMatchId,
        string expectedSessionId,
        string expectedAdapterVersion,
        string expectedGameVersion,
        string expectedMapId,
        string expectedMapName,
        IReadOnlyList<Sc2ExpectedParticipant> expectedParticipants,
        long maximumReplayBytes = DefaultMaximumReplayBytes)
    {
        ArgumentNullException.ThrowIfNull(evidence);
        ArgumentNullException.ThrowIfNull(expectedParticipants);
        var errors = new List<string>();

        static bool IsSha256(string? value) =>
            value is { Length: 64 } && value.All(Uri.IsHexDigit);

        if (evidence.SchemaVersion != 1) errors.Add("evidence.schema-version.unsupported");
        if (!string.Equals(evidence.MatchId, expectedMatchId, StringComparison.Ordinal)) errors.Add("evidence.match-id.mismatch");
        if (!string.Equals(evidence.SessionId, expectedSessionId, StringComparison.Ordinal)) errors.Add("evidence.session-id.mismatch");
        if (!string.Equals(evidence.AdapterVersion, expectedAdapterVersion, StringComparison.Ordinal)) errors.Add("evidence.adapter-version.mismatch");
        if (!string.Equals(evidence.GameVersion, expectedGameVersion, StringComparison.Ordinal)) errors.Add("evidence.game-version.mismatch");
        if (!string.Equals(evidence.MapId, expectedMapId, StringComparison.Ordinal)) errors.Add("evidence.map-id.mismatch");
        if (!string.Equals(evidence.MapName, expectedMapName, StringComparison.Ordinal)) errors.Add("evidence.map-name.mismatch");
        if (!string.Equals(evidence.Outcome, "completed", StringComparison.Ordinal)) errors.Add("evidence.outcome.invalid");
        if (evidence.CapturedAtUtc.Offset != TimeSpan.Zero || evidence.TerminalObservedAtUtc.Offset != TimeSpan.Zero ||
            evidence.TerminalObservedAtUtc < evidence.CapturedAtUtc)
            errors.Add("evidence.timestamp.invalid");

        var expected = expectedParticipants.ToArray();
        var actual = evidence.ExpectedParticipants?.ToArray() ?? [];
        if (expected.Length < 2 || actual.Length != expected.Length ||
            expected.Select(p => p.ParticipantId).Distinct(StringComparer.Ordinal).Count() != expected.Length ||
            actual.Select(p => p.ParticipantId).Distinct(StringComparer.Ordinal).Count() != actual.Length)
        {
            errors.Add("evidence.assignment.participants.invalid");
        }
        else
        {
            foreach (var participant in expected)
            {
                if (string.IsNullOrWhiteSpace(participant.ParticipantId) ||
                    string.IsNullOrWhiteSpace(participant.TeamId) ||
                    string.IsNullOrWhiteSpace(participant.BuildId) ||
                    !IsSha256(participant.BuildSha256))
                {
                    errors.Add("evidence.assignment.participant.invalid");
                    continue;
                }

                var recorded = actual.SingleOrDefault(p =>
                    string.Equals(p.ParticipantId, participant.ParticipantId, StringComparison.Ordinal));
                if (recorded is null ||
                    !string.Equals(recorded.TeamId, participant.TeamId, StringComparison.Ordinal) ||
                    !string.Equals(recorded.BuildId, participant.BuildId, StringComparison.Ordinal) ||
                    !string.Equals(recorded.BuildSha256, participant.BuildSha256, StringComparison.OrdinalIgnoreCase))
                    errors.Add("evidence.assignment.participant-mismatch");
            }
        }

        var terminal = evidence.TerminalResults?.ToArray() ?? [];
        var replay = evidence.Replay;
        if (terminal.Length != expected.Length ||
            terminal.Any(p => p.Sc2PlayerId == 0) ||
            terminal.Select(p => p.Sc2PlayerId).Distinct().Count() != terminal.Length ||
            terminal.Select(p => p.ParticipantId).Distinct(StringComparer.Ordinal).Count() != terminal.Length)
            errors.Add("evidence.terminal-results.identity-invalid");

        var allowedResults = new HashSet<string>(["Victory", "Defeat", "Tie"], StringComparer.Ordinal);
        if (terminal.Any(p => !allowedResults.Contains(p.Result)))
            errors.Add("evidence.terminal-results.value-invalid");

        if (replay is null)
        {
            errors.Add("evidence.replay.missing");
        }
        else
        {
            if (string.IsNullOrWhiteSpace(replay.ArtifactId) || string.IsNullOrWhiteSpace(replay.Location))
                errors.Add("evidence.replay.identity-missing");
            if (replay.SizeBytes <= 0 || replay.SizeBytes > maximumReplayBytes || maximumReplayBytes <= 0)
                errors.Add("evidence.replay.size-invalid");
            if (!IsSha256(replay.Sha256) || !IsSha256(replay.VerifiedSha256) ||
                !string.Equals(replay.Sha256, replay.VerifiedSha256, StringComparison.OrdinalIgnoreCase))
                errors.Add("evidence.replay.digest-invalid");
            if (!string.Equals(replay.MapName, expectedMapName, StringComparison.Ordinal))
                errors.Add("evidence.replay.map-mismatch");
            if (!string.Equals(replay.GameVersion, expectedGameVersion, StringComparison.Ordinal))
                errors.Add("evidence.replay.game-version-mismatch");
            if (string.IsNullOrWhiteSpace(replay.DataVersion) || replay.DataBuild == 0 || replay.BaseBuild == 0)
                errors.Add("evidence.replay.build-metadata-missing");

            var replayResults = replay.PlayerResults?.ToArray() ?? [];
            if (replayResults.Length != terminal.Length ||
                replayResults.Any(p => p.Sc2PlayerId == 0) ||
                replayResults.Select(p => p.Sc2PlayerId).Distinct().Count() != replayResults.Length ||
                replayResults.Any(p => !allowedResults.Contains(p.Result)))
            {
                errors.Add("evidence.replay.player-results.invalid");
            }
            else
            {
                foreach (var result in terminal)
                {
                    var replayResult = replayResults.SingleOrDefault(p => p.Sc2PlayerId == result.Sc2PlayerId);
                    if (replayResult is null || !string.Equals(replayResult.Result, result.Result, StringComparison.Ordinal))
                        errors.Add("evidence.replay.player-results.mismatch");
                }
            }
        }

        if (terminal.Length == expected.Length && terminal.All(p => !string.IsNullOrWhiteSpace(p.ParticipantId)))
        {
            foreach (var participant in expected)
            {
                if (terminal.Count(p => string.Equals(p.ParticipantId, participant.ParticipantId, StringComparison.Ordinal)) != 1)
                    errors.Add("evidence.terminal-results.assignment-mismatch");
            }
        }

        return new Sc2MatchEvidenceValidation(errors.Distinct(StringComparer.Ordinal).ToArray());
    }
}
