using System.Runtime.CompilerServices;
using System.Security.Cryptography;

namespace ServerSC2.ContractChecks;

/// <summary>
/// Executes package-integrity contract checks when the contract-check executable loads.
/// Keeping these checks in a separate file avoids coupling the production package contract
/// to the console harness's large set of SC2 evidence checks.
/// </summary>
internal static class Sc2BotRunnerArtifactContractChecks
{
    [ModuleInitializer]
    internal static void Run()
    {
        var root = Path.Combine(Path.GetTempPath(), "ServerSC2.BotArtifactChecks", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var runnerPath = Path.Combine(root, "SingularityBot.Runner.exe");
            var definitionPath = Path.Combine(root, "bot-definition.json");
            File.WriteAllText(runnerPath, "runner-payload");
            File.WriteAllText(definitionPath, "{\"schemaVersion\":1}");

            var runnerHash = Hash(runnerPath);
            var definitionHash = Hash(definitionPath);
            var packageHash = new string('a', 64);
            var build = new ServerApp.Core.BotBuildReference("bot-1", "build-1", packageHash);
            var artifact = new ServerSC2.ServerAppAdapter.Sc2BotRunnerArtifact(
                root, runnerPath, definitionPath, packageHash, runnerHash, definitionHash);
            artifact.ValidateFor(build);

            ExpectRejected(() => artifact.ValidateFor(build with { ContentSha256 = new string('b', 64) }),
                "package digest mismatch");
            ExpectRejected(() => (artifact with { BotDefinitionSha256 = new string('c', 64) }).ValidateFor(build),
                "definition payload hash mismatch");
            ExpectRejected(() => (artifact with { RunnerExecutableSha256 = "not-a-hash" }).ValidateFor(build),
                "invalid runner hash");
            ExpectRejected(() => (artifact with { BotDefinitionPath = Path.Combine(root, "..", "outside.json") }).ValidateFor(build),
                "definition path escape");

            Console.WriteLine("PASS immutable bot package and BotDefinition integrity checks");
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }

    private static string Hash(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream));
    }

    private static void ExpectRejected(Action action, string scenario)
    {
        try
        {
            action();
            throw new InvalidOperationException($"Expected artifact validation to reject {scenario}.");
        }
        catch (InvalidOperationException exception) when (
            exception.Message.Contains("immutable", StringComparison.OrdinalIgnoreCase) ||
            exception.Message.Contains("resolved", StringComparison.OrdinalIgnoreCase) ||
            exception.Message.Contains("package", StringComparison.OrdinalIgnoreCase))
        {
            // The contract rejected the invalid package as required.
        }
    }
}
