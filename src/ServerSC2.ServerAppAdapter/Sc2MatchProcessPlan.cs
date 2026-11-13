namespace ServerSC2.ServerAppAdapter;

/// <summary>SC2 process roles in the neutral-observer match topology.</summary>
public enum Sc2ProcessRole
{
    Observer,
    Participant
}

/// <summary>
/// One SC2 client in a match process plan. The observer is not a participant and has no bot
/// runner. Participant clients are paired with exactly one admitted bot runner.
/// </summary>
public sealed record Sc2ClientProcessPlan(
    Sc2ProcessRole Role,
    int ClientOrdinal,
    string? ParticipantId,
    int? GamePort,
    bool HasCreateGameAuthority);

/// <summary>
/// A validated, data-driven process topology for one match. This is a launch plan only:
/// it does not claim that the SC2 observer/client port topology has been proven live.
/// </summary>
public sealed record Sc2MatchProcessPlan(
    string MatchId,
    string SessionId,
    int StartPort,
    IReadOnlyList<Sc2ClientProcessPlan> Sc2Clients,
    IReadOnlyList<Sc2ParticipantLaunch> BotRunners)
{
    public static Sc2MatchProcessPlan Create(Sc2SessionLaunchRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.MatchId);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.SessionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.AdapterVersion);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.GameVersion);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.MapId);

        if (request.Participants is null)
            throw new InvalidOperationException("An observer-hosted SC2 match requires a participant collection.");

        // Snapshot caller-owned input before validating or constructing the launch plan.
        // A mutable collection must not be able to change topology after admission.
        var participants = request.Participants.ToArray();
        if (participants.Length is < 2 or > 64)
            throw new InvalidOperationException("An observer-hosted SC2 match requires between 2 and 64 participants.");
        if (participants.Any(p => p is null))
            throw new InvalidOperationException("An observer-hosted SC2 match cannot contain a null participant.");
        if (participants.Any(p => string.IsNullOrWhiteSpace(p.ParticipantId) ||
            string.IsNullOrWhiteSpace(p.TeamId) || p.BotBuild is null ||
            string.IsNullOrWhiteSpace(p.BotBuild.BuildId) ||
            p.BotBuild.ContentSha256 is null ||
            p.BotBuild.ContentSha256.Length != 64 ||
            !p.BotBuild.ContentSha256.All(Uri.IsHexDigit) ||
            p.GamePort is < 1 or > 65535))
            throw new InvalidOperationException("Every participant requires an identity, team, SHA-256 build reference, and valid listener port.");
        if (participants.Select(p => p.ParticipantId).Distinct(StringComparer.Ordinal).Count() != participants.Length)
            throw new InvalidOperationException("SC2 participant IDs must be unique.");
        if (participants.Select(p => p.GamePort).Distinct().Count() != participants.Length)
            throw new InvalidOperationException("Every participant SC2 client requires a distinct listener port.");
        if (participants.Any(p => p.IsGameHost))
            throw new InvalidOperationException("Participant clients cannot own CreateGame authority in observer-hosted topology.");

        // One observer plus N player clients each consume two ports, with one shared port.
        var multiplayerPortCount = (2 * (participants.Length + 1)) + 1;
        if (request.StartPort < 1 || request.StartPort > 65535 - multiplayerPortCount + 1)
            throw new InvalidOperationException("The match-level StartPort cannot reserve the observer and participant multiplayer port block.");

        var multiplayerPortLast = request.StartPort + multiplayerPortCount - 1;
        if (participants.Any(p => p.GamePort >= request.StartPort && p.GamePort <= multiplayerPortLast))
            throw new InvalidOperationException("Participant listener ports cannot overlap the match multiplayer port block.");

        var clients = new List<Sc2ClientProcessPlan>(participants.Length + 1)
        {
            new(Sc2ProcessRole.Observer, 0, null, null, true)
        };

        for (var index = 0; index < participants.Length; index++)
        {
            var participant = participants[index];
            clients.Add(new Sc2ClientProcessPlan(
                Sc2ProcessRole.Participant,
                index + 1,
                participant.ParticipantId,
                participant.GamePort,
                false));
        }

        return new Sc2MatchProcessPlan(
            request.MatchId,
            request.SessionId,
            request.StartPort,
            Array.AsReadOnly(clients.ToArray()),
            Array.AsReadOnly(participants));
    }
}
