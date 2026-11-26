using System.Text;
using ServerSC2.Core;

namespace ServerSC2.ContractChecks;

public static class Sc2BotAuthoringProposalContractChecks
{
    public static void Run()
    {
        ProposalPinsExactBuildAndContracts();
        DocumentBytesAreSnapshotted();
        IntegrityDigestBindsEveryPinAndPayload();
        InvalidDocumentsAndPinsAreRejected();
    }

    private static void ProposalPinsExactBuildAndContracts()
    {
        var proposal = CreateProposal();
        Assert(proposal.BotIdentityId == "bot-alpha", "Bot identity was not preserved.");
        Assert(proposal.BotBuildId == "build-42", "Exact build ID was not preserved.");
        Assert(proposal.BotDefinition.ContractId == "singularitybot.bot-definition", "BotDefinition contract was not pinned.");
        Assert(proposal.MatchDefinition.ContractId == "singularitybot.match-definition", "MatchDefinition contract was not pinned.");
        Assert(proposal.Catalogue.RuntimeCompatibilityVersion == "runner-3", "Runner compatibility was not pinned.");
        Assert(proposal.IntegritySha256.Length == 64, "Proposal integrity digest is not SHA-256.");
    }

    private static void DocumentBytesAreSnapshotted()
    {
        var source = Encoding.UTF8.GetBytes("{\"schemaVersion\":1,\"name\":\"before\"}");
        var document = new Sc2AuthoringDocument("example.definition", "1", source);
        var originalDigest = document.Sha256;
        source[0] = (byte)'[';
        var exposedCopy = document.JsonUtf8.ToArray();
        exposedCopy[0] = (byte)'[';
        Assert(document.Sha256 == originalDigest, "Caller mutation changed the document digest.");
        Assert(document.JsonUtf8.Span[0] == (byte)'{', "Caller mutation changed the stored document bytes.");
    }

    private static void IntegrityDigestBindsEveryPinAndPayload()
    {
        var baseline = CreateProposal();
        var changedBuild = new Sc2BotAuthoringProposal(
            baseline.ProposalId, baseline.BotIdentityId, baseline.BotBuildId, new string('B', 64),
            baseline.Catalogue, baseline.BotDefinition, baseline.MatchDefinition);
        var changedCatalogue = new Sc2BotAuthoringProposal(
            baseline.ProposalId, baseline.BotIdentityId, baseline.BotBuildId, baseline.BotBuildSha256,
            baseline.Catalogue with { CatalogueVersion = "catalogue-2" },
            baseline.BotDefinition, baseline.MatchDefinition);
        var changedDefinition = new Sc2BotAuthoringProposal(
            baseline.ProposalId, baseline.BotIdentityId, baseline.BotBuildId, baseline.BotBuildSha256,
            baseline.Catalogue,
            new Sc2AuthoringDocument("singularitybot.bot-definition", "1", Encoding.UTF8.GetBytes("{\"name\":\"other\"}")),
            baseline.MatchDefinition);
        Assert(baseline.IntegritySha256 != changedBuild.IntegritySha256, "Build digest was not bound.");
        Assert(baseline.IntegritySha256 != changedCatalogue.IntegritySha256, "Catalogue version was not bound.");
        Assert(baseline.IntegritySha256 != changedDefinition.IntegritySha256, "Definition bytes were not bound.");
    }

    private static void InvalidDocumentsAndPinsAreRejected()
    {
        AssertThrows<ArgumentException>(() => new Sc2AuthoringDocument("contract", "1", Encoding.UTF8.GetBytes("[]")));
        AssertThrows<System.Text.Json.JsonException>(() => new Sc2AuthoringDocument("contract", "1", Encoding.UTF8.GetBytes("{")));
        AssertThrows<ArgumentException>(() => new Sc2BotAuthoringProposal(
            "proposal", "bot", "build", "not-a-digest",
            CreateProposal().Catalogue, CreateProposal().BotDefinition, CreateProposal().MatchDefinition));
        var sameContract = new Sc2AuthoringDocument("singularitybot.bot-definition", "1", Encoding.UTF8.GetBytes("{\"match\":true}"));
        AssertThrows<ArgumentException>(() => new Sc2BotAuthoringProposal(
            "proposal", "bot", "build", new string('A', 64),
            CreateProposal().Catalogue, CreateProposal().BotDefinition, sameContract));
    }

    private static Sc2BotAuthoringProposal CreateProposal()
    {
        var catalogue = new Sc2AuthoringCataloguePin(
            "singularitybot.authoring", "catalogue-1", new string('C', 64),
            "singularitybot.runner-compatibility", "runner-3");
        var definition = new Sc2AuthoringDocument(
            "singularitybot.bot-definition", "1",
            Encoding.UTF8.GetBytes("{\"schemaVersion\":1,\"identity\":{\"id\":\"bot-alpha\"}}"));
        var match = new Sc2AuthoringDocument(
            "singularitybot.match-definition", "1",
            Encoding.UTF8.GetBytes("{\"schemaVersion\":1,\"map\":\"AbyssalReefLE\"}"));
        return new Sc2BotAuthoringProposal(
            "proposal-7", "bot-alpha", "build-42", new string('A', 64),
            catalogue, definition, match);
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static void AssertThrows<TException>(Action action) where TException : Exception
    {
        try { action(); }
        catch (TException) { return; }
        throw new InvalidOperationException($"Expected {typeof(TException).Name}.");
    }
}
