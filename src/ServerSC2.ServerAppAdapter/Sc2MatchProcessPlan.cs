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

        if (request.Participants is null || request.Participants.Count is < 2 or > 64)
            throw new InvalidOperationException("An observer-hosted SC2 match requires between 2 and 64 participants.");
        if (request.Participants.Any(p => string.IsNullOrWhiteSpace(p.ParticipantId) ||
            string.IsNullOrWhiteSpace(p.TeamId) || p.BotBuild is null ||
            string.IsNullOrWhiteSpace(p.BotBuild.BuildId) ||
            string.IsNullOrWhiteSpace(p.BotBuild.ContentSha256) ||
            p.GamePort is < 1 or > 65535))
            throw new InvalidOperationException("Every participant requires an identity, team, immutable build, and valid listener port.");
        if (request.Participants.Select(p => p.ParticipantId).Distinct(StringComparer.Ordinal).Count() != request.Participants.Count)
            throw new InvalidOperationException("SC2 participant IDs must be unique.");
        if (request.Participants.Select(p => p.GamePort).Distinct().Count() != request.Participants.Count)
            throw new InvalidOperationException("Every participant SC2 client requires a distinct listener port.");
        if (request.Participants.Any(p => p.IsGameHost))
            throw new InvalidOperationException("Participant clients cannot own CreateGame authority in observer-hosted topology.");
        if (request.StartPort is < 1 or > 65535)
            throw new InvalidOperationException("The match-level StartPort is invalid.");

        var clients = new List<Sc2ClientProcessPlan>(request.Participants.Count + 1)
        {
            new(Sc2ProcessRole.Observer, 0, null, null, true)
        };

        for (var index = 0; index < request.Participants.Count; index++)
        {
            var participant = request.Participants[index];
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
            Array.AsReadOnly(request.Participants.ToArray()));
    }
}
