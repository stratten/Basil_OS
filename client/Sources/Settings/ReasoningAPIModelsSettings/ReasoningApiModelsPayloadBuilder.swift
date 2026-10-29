import Foundation

enum ReasoningApiModelsPayloadBuilder {
    static func makeProviderSummaries(providers: [APIProviderInfo]) -> [[String: Any]] {
        providers.map { provider in
            [
                "id": provider.id,
                "name": provider.name,
                "enabled": provider.isEnabled,
                "usingOwnApiKey": provider.localUsingOwnApiKey,
                "hasKey": provider.hasKey,
                "models": provider.models.map { model in
                    [
                        "id": model.id,
                        "name": model.name,
                        "description": model.description ?? "",
                        "capabilities": model.capabilities.map { $0.rawValue },
                        "supportsExtendedThinking": model.supportsExtendedThinking,
                        "enabled": model.isEnabled,
                    ] as [String: Any]
                },
            ]
        }
    }
}
