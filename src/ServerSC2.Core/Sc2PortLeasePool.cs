namespace ServerSC2.Core;

/// <summary>
/// A process-local lease for one match's participant listener ports and a sized
/// SC2 multiplayer port block. This is not an OS-level socket reservation.
/// </summary>
public sealed class Sc2PortLease : IDisposable
{
    private Action<Guid>? _release;

    internal Sc2PortLease(
        Guid leaseId,
        IReadOnlyList<int> participantGamePorts,
        int startPort,
        int multiplayerPortCount,
        Action<Guid> release)
    {
        LeaseId = leaseId;
        ParticipantGamePorts = Array.AsReadOnly(participantGamePorts.ToArray());
        StartPort = startPort;
        MultiplayerPortCount = multiplayerPortCount;
        _release = release;
    }

    public Guid LeaseId { get; }
    public IReadOnlyList<int> ParticipantGamePorts { get; }
    public int StartPort { get; }
    public int MultiplayerPortCount { get; }

    // Compatibility accessors for the existing two-participant runtime.
    public int HostGamePort => ParticipantGamePorts[0];
    public int JoinerGamePort => ParticipantGamePorts[1];

    public void Dispose() => Interlocked.Exchange(ref _release, null)?.Invoke(LeaseId);
}

/// <summary>
/// Atomically allocates a variable number of participant listener ports and a
/// multiplayer block sized for the profile's maximum match format. Leases are
/// process-local; they do not reserve operating-system sockets.
/// </summary>
public sealed class Sc2PortLeasePool
{
    private readonly object _gate = new();
    private readonly Sc2ServerProfile _profile;
    private readonly Dictionary<Guid, int> _leases = new();

    public Sc2PortLeasePool(Sc2ServerProfile profile)
    {
        ArgumentNullException.ThrowIfNull(profile);
        var errors = profile.Validate();
        if (errors.Count != 0)
            throw new ArgumentException($"The SC2 server profile is invalid: {string.Join(", ", errors)}", nameof(profile));
        _profile = profile;
    }

    public int ActiveLeaseCount
    {
        get { lock (_gate) return _leases.Count; }
    }

    public bool TryAcquire(out Sc2PortLease? lease) =>
        TryAcquire(_profile.MaximumParticipantsPerMatch, out lease);

    public bool TryAcquire(int participantCount, out Sc2PortLease? lease)
    {
        if (participantCount is < 2 || participantCount > _profile.MaximumParticipantsPerMatch)
        {
            lease = null;
            return false;
        }

        lock (_gate)
        {
            if (_leases.Count >= _profile.MaximumConcurrentMatches)
            {
                lease = null;
                return false;
            }

            var usedSlots = _leases.Values.ToHashSet();
            for (var slot = 0; slot < _profile.MaximumConcurrentMatches; slot++)
            {
                if (usedSlots.Contains(slot))
                    continue;

                var firstGamePort = checked(_profile.GamePortFirst + slot * _profile.MaximumParticipantsPerMatch);
                var gamePorts = Enumerable.Range(firstGamePort, participantCount).ToArray();
                var startPort = checked(_profile.StartPortFirst + slot * _profile.MultiplayerPortStride);
                var leaseId = Guid.NewGuid();

                _leases.Add(leaseId, slot);
                lease = new Sc2PortLease(
                    leaseId, gamePorts, startPort, _profile.MultiplayerPortCount, Release);
                return true;
            }

            lease = null;
            return false;
        }
    }

    private void Release(Guid leaseId)
    {
        lock (_gate)
            _leases.Remove(leaseId);
    }
}
