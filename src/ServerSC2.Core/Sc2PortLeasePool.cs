namespace ServerSC2.Core;

/// <summary>
/// A process-local lease for two SC2 listener ports and one shared multiplayer port block.
/// StartPort is a match-level base; ports StartPort+1 through StartPort+5 belong to this match.
/// </summary>
public sealed class Sc2PortLease : IDisposable
{
    private Action<Guid>? _release;

    internal Sc2PortLease(
        Guid leaseId,
        int hostGamePort,
        int joinerGamePort,
        int startPort,
        Action<Guid> release)
    {
        LeaseId = leaseId;
        HostGamePort = hostGamePort;
        JoinerGamePort = joinerGamePort;
        StartPort = startPort;
        _release = release;
    }

    public Guid LeaseId { get; }
    public int HostGamePort { get; }
    public int JoinerGamePort { get; }
    public int StartPort { get; }

    public void Dispose() => Interlocked.Exchange(ref _release, null)?.Invoke(LeaseId);
}

/// <summary>
/// Atomically allocates two distinct listener ports and a shared five-port multiplayer block
/// for each match. This protects concurrent sessions within this host process; it is not an
/// OS-level socket reservation.
/// </summary>
public sealed class Sc2PortLeasePool
{
    private const int MultiplayerPortStride = 6;

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

    public bool TryAcquire(out Sc2PortLease? lease)
    {
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

                var leaseId = Guid.NewGuid();
                var hostGamePort = checked(_profile.GamePortFirst + slot * 2);
                var joinerGamePort = checked(hostGamePort + 1);
                var startPort = checked(_profile.StartPortFirst + slot * MultiplayerPortStride);

                _leases.Add(leaseId, slot);
                lease = new Sc2PortLease(leaseId, hostGamePort, joinerGamePort, startPort, Release);
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