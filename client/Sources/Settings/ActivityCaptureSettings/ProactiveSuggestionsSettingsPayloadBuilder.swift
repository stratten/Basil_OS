import Foundation

@MainActor
enum ProactiveSuggestionsSettingsPayloadBuilder {
    static func makeSettingsPayload(viewModel: AmbientSuggestionSettingsViewModel) -> [String: Any] {
        [
            "enabled": viewModel.enabled,
            "mode": viewModel.mode,
            "frequencySeconds": viewModel.frequencySeconds,
            "evaluationModel": viewModel.evaluationModel,
            "selectedEvaluationModelIsUnavailable": viewModel.selectedEvaluationModelIsUnavailable,
            "minimumConfidence": viewModel.minimumConfidence,
            "cooldownMinutes": viewModel.cooldownMinutes,
            "enabledCapabilities": Array(viewModel.enabledCapabilities).sorted(),
            "autoExecuteCapabilities": Array(viewModel.autoExecuteCapabilities).sorted(),
            "excludedAppNames": viewModel.excludedAppNames,
            "localModels": viewModel.localModels.map(makeModelPayload),
            "apiModels": viewModel.apiModels.map(makeModelPayload),
        ]
    }

    static func makeModelPayload(_ model: ActivityCaptureModelInfo) -> [String: Any] {
        [
            "id": model.id,
            "displayName": model.displayName,
            "provider": model.provider,
            "isLocal": model.isLocal,
        ]
    }
}
