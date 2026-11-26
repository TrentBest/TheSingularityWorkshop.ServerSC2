using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace ServerSC2.Core;

/// <summary>
/// Pins the trusted authoring catalogue and runtime compatibility contract used to
/// interpret a submitted declarative proposal. These values are identifiers, not authority.
/// The host must resolve them against its own trusted registries before launch.
/// </summary>
public sealed record Sc2AuthoringCataloguePin(
    string CatalogueId,
    string CatalogueVersion,
    string CatalogueSha256,
    string RuntimeCompatibilityId,
    string RuntimeCompatibilityVersion);

/// <summary>
/// Opaque, immutable JSON document owned by the upstream SingularityBot domain contract.
/// ServerSC2 preserves the exact UTF-8 bytes; it does not define or reinterpret BotDefinition
/// or MatchDefinition properties.
/// </summary>
public sealed class Sc2AuthoringDocument
{
    private readonly byte[] _jsonUtf8;

    public Sc2AuthoringDocument(string contractId, string contractVersion, ReadOnlySpan<byte> jsonUtf8)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(contractId);
        ArgumentException.ThrowIfNullOrWhiteSpace(contractVersion);
        if (jsonUtf8.IsEmpty)
            throw new ArgumentException("An authoring document cannot be empty.", nameof(jsonUtf8));

        // Reject malformed UTF-8 and non-object JSON while preserving the original bytes.
        _ = new UTF8Encoding(false, true).GetString(jsonUtf8);
        using var parsed = JsonDocument.Parse(jsonUtf8);
        if (parsed.RootElement.ValueKind != JsonValueKind.Object)
            throw new ArgumentException("An authoring document must be a JSON object.", nameof(jsonUtf8));

        ContractId = contractId;
        ContractVersion = contractVersion;
        _jsonUtf8 = jsonUtf8.ToArray();
        Sha256 = Convert.ToHexString(SHA256.HashData(_jsonUtf8));
    }

    public string ContractId { get; }
    public string ContractVersion { get; }
    public string Sha256 { get; }
    public ReadOnlyMemory<byte> JsonUtf8 => new(_jsonUtf8.ToArray());
}

/// <summary>
/// Immutable transport envelope for one SC2 authoring proposal. The envelope pins exact
/// bot build, BotDefinition and MatchDefinition contracts, catalogue, and runtime compatibility.
/// It intentionally contains no client-supplied validation receipt or launch authority.
/// </summary>
public sealed class Sc2BotAuthoringProposal
{
    public Sc2BotAuthoringProposal(
        string proposalId,
        string botIdentityId,
        string botBuildId,
        string botBuildSha256,
        Sc2AuthoringCataloguePin catalogue,
        Sc2AuthoringDocument botDefinition,
        Sc2AuthoringDocument matchDefinition)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(proposalId);
        ArgumentException.ThrowIfNullOrWhiteSpace(botIdentityId);
        ArgumentException.ThrowIfNullOrWhiteSpace(botBuildId);
        ArgumentNullException.ThrowIfNull(catalogue);
        ArgumentNullException.ThrowIfNull(botDefinition);
        ArgumentNullException.ThrowIfNull(matchDefinition);

        if (!IsSha256(botBuildSha256))
            throw new ArgumentException("The immutable bot build digest must be a 64-character SHA-256 value.", nameof(botBuildSha256));
        if (string.IsNullOrWhiteSpace(catalogue.CatalogueId) ||
            string.IsNullOrWhiteSpace(catalogue.CatalogueVersion) ||
            !IsSha256(catalogue.CatalogueSha256) ||
            string.IsNullOrWhiteSpace(catalogue.RuntimeCompatibilityId) ||
            string.IsNullOrWhiteSpace(catalogue.RuntimeCompatibilityVersion))
            throw new ArgumentException("The trusted catalogue and runtime compatibility pins are incomplete or invalid.", nameof(catalogue));
        if (string.Equals(botDefinition.ContractId, matchDefinition.ContractId, StringComparison.Ordinal) &&
            string.Equals(botDefinition.ContractVersion, matchDefinition.ContractVersion, StringComparison.Ordinal))
            throw new ArgumentException("BotDefinition and MatchDefinition must use distinct domain contract identities.");

        ProposalId = proposalId;
        BotIdentityId = botIdentityId;
        BotBuildId = botBuildId;
        BotBuildSha256 = botBuildSha256.ToUpperInvariant();
        Catalogue = catalogue with { CatalogueSha256 = catalogue.CatalogueSha256.ToUpperInvariant() };
        BotDefinition = botDefinition;
        MatchDefinition = matchDefinition;
        IntegritySha256 = ComputeIntegritySha256();
    }

    public string ProposalId { get; }
    public string BotIdentityId { get; }
    public string BotBuildId { get; }
    public string BotBuildSha256 { get; }
    public Sc2AuthoringCataloguePin Catalogue { get; }
    public Sc2AuthoringDocument BotDefinition { get; }
    public Sc2AuthoringDocument MatchDefinition { get; }

    /// <summary>
    /// Digest over all identity/version pins and exact document bytes. Recompute this
    /// server-side after deserialization; never trust a digest supplied by a browser.
    /// </summary>
    public string IntegritySha256 { get; }

    private string ComputeIntegritySha256()
    {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        Append(hash, ProposalId);
        Append(hash, BotIdentityId);
        Append(hash, BotBuildId);
        Append(hash, BotBuildSha256);
        Append(hash, Catalogue.CatalogueId);
        Append(hash, Catalogue.CatalogueVersion);
        Append(hash, Catalogue.CatalogueSha256);
        Append(hash, Catalogue.RuntimeCompatibilityId);
        Append(hash, Catalogue.RuntimeCompatibilityVersion);
        Append(hash, BotDefinition.ContractId);
        Append(hash, BotDefinition.ContractVersion);
        Append(hash, BotDefinition.Sha256);
        Append(hash, BotDefinition.JsonUtf8.Span);
        Append(hash, MatchDefinition.ContractId);
        Append(hash, MatchDefinition.ContractVersion);
        Append(hash, MatchDefinition.Sha256);
        Append(hash, MatchDefinition.JsonUtf8.Span);
        return Convert.ToHexString(hash.GetHashAndReset());
    }

    private static void Append(IncrementalHash hash, string value) =>
        Append(hash, Encoding.UTF8.GetBytes(value));

    private static void Append(IncrementalHash hash, ReadOnlySpan<byte> value)
    {
        Span<byte> length = stackalloc byte[sizeof(int)];
        BinaryPrimitives.WriteInt32BigEndian(length, value.Length);
        hash.AppendData(length);
        hash.AppendData(value);
    }

    private static bool IsSha256(string? value) =>
        value is { Length: 64 } && value.All(Uri.IsHexDigit);
}
