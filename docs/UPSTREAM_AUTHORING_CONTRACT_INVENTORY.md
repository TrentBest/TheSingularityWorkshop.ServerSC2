# Upstream SingularityBot authoring contract inventory

**Inspected branch:** `development`  
**Inspected head:** `57a75d33ac37739211084b465bf3be317777663b`  
**Inspection date:** 2026-11-26  
**Purpose:** record the exact upstream contract surface ServerSC2 can consume without duplicating bot-domain semantics.

This is a source inventory, not a claim that the complete authoring GUI or hosted match workflow is ready.

## Confirmed upstream foundations

| Contract | Current source | What ServerSC2 can rely on |
|---|---|---|
| Bot definition | `src/SingularityBot/Behavior/BotDefinition.cs` | Typed v1 definition, strict JSON parsing (unknown members rejected), and deterministic semantic validation |
| Definition catalogue | `src/SingularityBot/Behavior/BotDefinitionCatalog.cs` | Compiled trusted definitions and registered mode selection; no client-selected executable loading |
| Command composition | `src/SingularityBot/Behavior/CommandLayerComposition.cs` | Standalone v1 ordered declarative layers, stable slots, maximum five enabled layers, and adjacent emits/accepts checks |
| Setting metadata | `src/SingularityBot/Behavior/CommandLayerSettingSchema.cs` | Typed descriptors, bounded nested schemas, JSON-literal defaults/conditions, lifecycle mutability, validation, and immutable snapshots |
| Definition JSON schema | `schemas/singularitybot-definition-v1.schema.json` | Strict JSON Schema document, but currently not fully aligned with the typed model |
| Existing editor | `src/SingularityBot.Studio` | Native WPF authoring client with guided production-plan and strategic-goal editors; not the browser Experience |

The project targets .NET 10.

## Integration blockers that remain real

1. **No MatchDefinition contract found.** The current source tree contains match snapshot schemas, but no canonical authorable MatchDefinition type/schema was identified. ServerSC2 must not invent its shape and label it upstream-compatible.
2. **Composition is not embedded in BotDefinition.** `CommandLayerComposition` exists as a standalone type, but the inspected BotDefinition does not carry it as a round-trippable property. A submitted BotDefinition therefore cannot yet represent the complete composed authoring artifact.
3. **Catalogue publication is incomplete.** The existence of descriptor and registry types is not proof that the full trusted catalogue is exposed as a versioned, immutable discovery snapshot suitable for a remote client.
4. **Setting schema population/rendering is incomplete.** The setting descriptor contract exists, but the existing implementations still need complete registered schemas, and the Studio/browser clients need to render them dynamically. Do not infer complete control coverage from the descriptor type alone.
5. **Definition JSON schema disagrees with typed validation.** The inspected JSON schema constrains `race` to `Terran`, while typed validation accepts Terran, Protoss, and Zerg. Actual gameplay availability is narrower than type-level acceptance; trusted mode/race availability must decide what is selectable. Do not use the JSON schema alone as the executable availability authority.
6. **Presentation profile discovery is not established.** A presentation-profile identifier exists in command-layer selection, but a complete trusted presentation catalogue and compatibility resolution were not established by this inspection.

## Safe ServerSC2 implementation boundary

ServerSC2 may implement its own authenticated proposal/session API, immutable persistence, host-owned build resolution, request-size limits, audit records, and launch orchestration. These are host responsibilities.

For domain interpretation, ServerSC2 must wait for and consume upstream versioned contracts and authoritative validators. It may preserve opaque document bytes and pin contract/catalogue/runtime identities, but must not:
- create a competing BotDefinition or MatchDefinition model;
- publish a local shadow catalogue or setting list;
- treat browser validation as authoritative;
- accept arbitrary implementation IDs as executable code;
- treat registered/logging-only race modes as gameplay-capable; or
- launch from a stale or caller-supplied validation result.

The current `Sc2BotAuthoringProposal` is correctly limited to an opaque transport envelope. Its MatchDefinition pin is a forward-compatible transport slot, not evidence that an upstream MatchDefinition contract exists.

## Next upstream coordination slice

The owning SingularityBot workstream should publish one coherent, versioned remote authoring contract containing:
- canonical BotDefinition and MatchDefinition schemas/types;
- composition embedded in or explicitly linked from BotDefinition;
- a trusted catalogue snapshot with digest/version and race/mode availability;
- implementation descriptors, presentation descriptors, and complete per-setting schemas;
- authoritative parse/semantic validation APIs and structured diagnostics;
- runtime/build compatibility metadata.

Until then, ServerSC2 should continue only with independently testable host infrastructure and keep the authoring GUI integration gate closed.
