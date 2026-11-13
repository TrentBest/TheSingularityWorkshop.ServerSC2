namespace ServerSC2.Core;

/// <summary>Trusted deployment configuration for one SC2 host role.</summary>
public sealed record Sc2ServerProfile(
    string ProfileId,
    string AdapterVersion,
    string GameVersion,
    string MapId,
    int GamePortFirst,
    int GamePortLast,
    int StartPortFirst,
    int StartPortLast,
    int MaximumConcurrentMatches)
{
    private const int MultiplayerPortSpan = 5;
    private const int MultiplayerPortStride = MultiplayerPortSpan + 1;

    public IReadOnlyList<string> Validate()
    {
        var errors = new List<string>();
        if (string.IsNullOrWhiteSpace(ProfileId)) errors.Add("profile.id.required");
        if (string.IsNullOrWhiteSpace(AdapterVersion)) errors.Add("profile.adapter-version.required");
        if (string.IsNullOrWhiteSpace(GameVersion)) errors.Add("profile.game-version.required");
        if (string.IsNullOrWhiteSpace(MapId)) errors.Add("profile.map.required");

        ValidateRange(GamePortFirst, GamePortLast, "game", errors);
        ValidateRange(StartPortFirst, StartPortLast, "start", errors);

        if (StartPortLast is >= 1 and <= 65535 && StartPortLast > 65535 - MultiplayerPortSpan)
            errors.Add("profile.start-port-footprint.exceeds-range");

        if (GamePortFirst is >= 1 and <= 65535 &&
            StartPortFirst is >= 1 and <= 65535 &&
            StartPortLast is >= StartPortFirst and <= 65535)
        {
            var multiplayerFirst = StartPortFirst + 1;
            var multiplayerLast = Math.Min(65535, StartPortLast + MultiplayerPortSpan);
            if (GamePortFirst <= multiplayerLast && multiplayerFirst <= GamePortLast)
                errors.Add("profile.port-ranges.overlap");
        }

        if (MaximumConcurrentMatches <= 0)
            errors.Add("profile.concurrency.invalid");
        else
        {
            var gameCapacity = (long)GamePortLast - GamePortFirst + 1;
            var startCapacity = StartPortFirst <= StartPortLast
                ? ((long)StartPortLast - StartPortFirst) / MultiplayerPortStride + 1
                : 0;
            if (gameCapacity < (long)MaximumConcurrentMatches * 2)
                errors.Add("profile.game-port-capacity.insufficient");
            if (startCapacity < MaximumConcurrentMatches)
                errors.Add("profile.start-port-capacity.insufficient");
        }

        return Array.AsReadOnly(errors.ToArray());
    }

    private static void ValidateRange(int first, int last, string name, ICollection<string> errors)
    {
        if (first is < 1 or > 65535 || last is < 1 or > 65535 || first > last)
            errors.Add($"profile.{name}-port-range.invalid");
    }
}