import Foundation
import AppKit
import SwiftUI

@MainActor
final class AmbientSuggestionSettingsViewModel: ObservableObject {
    @Published var enabled = false
    @Published var frequencySeconds = 120.0
    @Published var evaluationModel = ""
    @Published var mode = "suggestion_only"
    @Published var enabledCapabilities: Set<String> = ["assistant_session"]
    @Published var autoExecuteCapabilities: Set<String> = []
    @Published var minimumConfidence = 0.75
    @Published var cooldownMinutes = 30.0
    @Published var excludedAppNamesText = ""
    @Published var isLoading = false
    @Published var isSaving = false
    @Published var statusMessage: String?
    @Published var availableModels: [ActivityCaptureModelInfo] = []

    private let apiClient = APIClient.shared
    private var loadedSettings: AmbientSuggestionSettingsData?
    private var isApplyingRemoteSettings = false
    private let logContext = "AmbientSuggestionSettings"

    var localModels: [ActivityCaptureModelInfo] {
        availableModels.filter { $0.isLocal }
    }

    var apiModels: [ActivityCaptureModelInfo] {
        availableModels.filter { !$0.isLocal }
    }

    var selectedEvaluationModelIsUnavailable: Bool {
        !evaluationModel.isEmpty && !availableModels.contains { $0.id == evaluationModel }
    }

    var excludedAppNames: [String] {
        excludedAppNamesText
            .split(separator: "\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    func load() async {
        DevLogger.shared.info("Loading Proactive Suggestions settings", context: logContext)
        isLoading = true
        defer { isLoading = false }

        await loadAvailableModels()
        await loadSettings()

        if evaluationModel.isEmpty, let firstModel = localModels.first ?? availableModels.first {
            evaluationModel = firstModel.id
        }
    }

    func save() async {
        let update = AmbientSuggestionSettingsUpdate(
            enabled: enabled,
            frequencySeconds: frequencySeconds,
            evaluationModel: evaluationModel,
            mode: mode,
            enabledCapabilities: Array(enabledCapabilities).sorted(),
            autoExecuteCapabilities: Array(autoExecuteCapabilities).sorted(),
            minimumConfidence: minimumConfidence,
            cooldownMinutes: cooldownMinutes,
            excludedAppNames: excludedAppNames,
            panelPosition: loadedSettings?.panelPosition,
            panelSize: loadedSettings?.panelSize,
            panelVisibleOnLaunch: loadedSettings?.panelVisibleOnLaunch
        )

        await updateAmbientSuggestionSettings(
            update,
            successMessage: "Proactive Suggestions settings saved.",
            failureMessage: "Error saving Proactive Suggestions settings"
        )
    }

    func setCapability(_ capability: String, enabled isEnabled: Bool) {
        if isEnabled {
            enabledCapabilities.insert(capability)
        } else {
            enabledCapabilities.remove(capability)
            autoExecuteCapabilities.remove(capability)
        }
    }

    func updateAmbientSuggestionsEnabled(_ isEnabled: Bool) async {
        let previousValue = loadedSettings?.enabled ?? !isEnabled
        await updateAmbientSuggestionSettings(
            AmbientSuggestionSettingsUpdate(enabled: isEnabled),
            successMessage: isEnabled ? "Proactive Suggestions enabled." : "Proactive Suggestions disabled.",
            failureMessage: "Error updating Proactive Suggestions enabled state"
        ) {
            self.enabled = previousValue
        }
    }

    func updateAmbientSuggestionFrequencySeconds(_ seconds: Double) async {
        let clampedSeconds = min(max(seconds, 1.0), 3600.0)
        frequencySeconds = clampedSeconds
        await updateAmbientSuggestionSettings(
            AmbientSuggestionSettingsUpdate(frequencySeconds: clampedSeconds),
            successMessage: "Proactive Suggestions frequency updated.",
            failureMessage: "Error updating Proactive Suggestions frequency"
        )
    }

    func updateAmbientSuggestionEvaluationModel(_ modelId: String) async {
        await updateAmbientSuggestionSettings(
            AmbientSuggestionSettingsUpdate(evaluationModel: modelId),
            successMessage: "Proactive Suggestions evaluator model updated.",
            failureMessage: "Error updating Proactive Suggestions evaluator model"
        )
    }

    func updateAmbientSuggestionMode(_ mode: String) async {
        await updateAmbientSuggestionSettings(
            AmbientSuggestionSettingsUpdate(mode: mode),
            successMessage: "Proactive Suggestions mode updated.",
            failureMessage: "Error updating Proactive Suggestions mode"
        )
    }

    func updateAmbientSuggestionMinimumConfidence(_ confidence: Double) async {
        let clampedConfidence = min(max(confidence, 0.0), 1.0)
        minimumConfidence = clampedConfidence
        await updateAmbientSuggestionSettings(
            AmbientSuggestionSettingsUpdate(minimumConfidence: clampedConfidence),
            successMessage: "Proactive Suggestions confidence threshold updated.",
            failureMessage: "Error updating Proactive Suggestions confidence threshold"
        )
    }

    func updateAmbientSuggestionCooldownMinutes(_ minutes: Double) async {
        await updateAmbientSuggestionSettings(
            AmbientSuggestionSettingsUpdate(cooldownMinutes: minutes),
            successMessage: "Proactive Suggestions cooldown updated.",
            failureMessage: "Error updating Proactive Suggestions cooldown"
        )
    }

    func updateAmbientSuggestionEnabledCapability(_ capability: String, enabled isEnabled: Bool) async {
        setCapability(capability, enabled: isEnabled)
        await updateAmbientSuggestionSettings(
            AmbientSuggestionSettingsUpdate(enabledCapabilities: Array(enabledCapabilities).sorted()),
            successMessage: "Proactive Suggestions enabled capabilities updated.",
            failureMessage: "Error updating Proactive Suggestions enabled capabilities"
        )
    }

    func updateAmbientSuggestionAutoExecuteCapability(_ capability: String, enabled isEnabled: Bool) async {
        setAutoExecuteCapability(capability, enabled: isEnabled)
        await updateAmbientSuggestionSettings(
            AmbientSuggestionSettingsUpdate(
                enabledCapabilities: Array(enabledCapabilities).sorted(),
                autoExecuteCapabilities: Array(autoExecuteCapabilities).sorted()
            ),
            successMessage: "Proactive Suggestions auto-execute capabilities updated.",
            failureMessage: "Error updating Proactive Suggestions auto-execute capabilities"
        )
    }

    func updateAmbientSuggestionExcludedAppNames() async {
        await updateAmbientSuggestionSettings(
            AmbientSuggestionSettingsUpdate(excludedAppNames: excludedAppNames),
            successMessage: "Proactive Suggestions exclusions updated.",
            failureMessage: "Error updating Proactive Suggestions exclusions"
        )
    }

    func setAutoExecuteCapability(_ capability: String, enabled isEnabled: Bool) {
        if isEnabled {
            enabledCapabilities.insert(capability)
            autoExecuteCapabilities.insert(capability)
        } else {
            autoExecuteCapabilities.remove(capability)
        }
    }

    private func loadSettings() async {
        do {
            let settings = try await apiClient.getAmbientSuggestionSettings()
            apply(settings)
            DevLogger.shared.info(
                "Loaded Proactive Suggestions settings: enabled=\(settings.enabled), evaluator=\(settings.evaluationModel), frequencySeconds=\(settings.frequencySeconds)",
                context: logContext
            )
            if selectedEvaluationModelIsUnavailable {
                statusMessage = "Selected evaluator model is not currently available: \(settings.evaluationModel)"
                DevLogger.shared.warning(statusMessage ?? "", context: logContext)
            }
        } catch {
            statusMessage = "Error loading Proactive Suggestions settings: \(error.localizedDescription)"
            DevLogger.shared.error(statusMessage ?? "", context: logContext)
        }
    }

    private func apply(_ settings: AmbientSuggestionSettingsData) {
        isApplyingRemoteSettings = true
        defer { isApplyingRemoteSettings = false }
        loadedSettings = settings
        enabled = settings.enabled
        frequencySeconds = settings.frequencySeconds
        evaluationModel = settings.evaluationModel
        mode = settings.mode
        enabledCapabilities = Set(settings.enabledCapabilities)
        autoExecuteCapabilities = Set(settings.autoExecuteCapabilities)
        minimumConfidence = settings.minimumConfidence
        cooldownMinutes = settings.cooldownMinutes
        excludedAppNamesText = settings.excludedAppNames.joined(separator: "\n")
    }

    private func loadAvailableModels() async {
        do {
            var models: [ActivityCaptureModelInfo] = []
            let localModelsData = try await apiClient.get("/models/installed")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase

            struct ModelVariant: Codable {
                let modelId: String
                let name: String
                let capabilities: [String]?
                let valid: Bool?
            }

            struct ModelType: Codable {
                let variants: [String: ModelVariant]
            }

            let localModelsResponse = try decoder.decode([String: ModelType].self, from: localModelsData)
            for (modelType, modelTypeInfo) in localModelsResponse {
                for (_, variant) in modelTypeInfo.variants {
                    if variant.valid == true,
                       let capabilities = variant.capabilities,
                       capabilities.contains("reasoning") {
                        models.append(ActivityCaptureModelInfo(
                            id: variant.modelId,
                            displayName: variant.name,
                            provider: modelType,
                            isLocal: true
                        ))
                    }
                }
            }

            let apiModelsData = try await apiClient.get("/settings/api_models/reasoning")
            struct APIModelResponse: Codable {
                let id: String
                let displayName: String
                let provider: String
            }

            struct APIModelsResponseData: Codable {
                let models: [APIModelResponse]
                let apiModelsEnabled: Bool
            }

            let apiModelsResponse = try decoder.decode(APIModelsResponseData.self, from: apiModelsData)
            if apiModelsResponse.apiModelsEnabled {
                for model in apiModelsResponse.models {
                    models.append(ActivityCaptureModelInfo(
                        id: model.id,
                        displayName: model.displayName,
                        provider: model.provider,
                        isLocal: false
                    ))
                }
            }

            availableModels = models.sorted {
                if $0.isLocal != $1.isLocal {
                    return $0.isLocal
                }
                return $0.displayName < $1.displayName
            }
            DevLogger.shared.info("Loaded \(availableModels.count) Ambient evaluator models", context: logContext)
        } catch {
            statusMessage = "Error loading Ambient evaluator models: \(error.localizedDescription)"
            DevLogger.shared.error(statusMessage ?? "", context: logContext)
        }
    }

    private func updateAmbientSuggestionSettings(
        _ update: AmbientSuggestionSettingsUpdate,
        successMessage: String,
        failureMessage: String,
        revert: (() -> Void)? = nil
    ) async {
        guard !isLoading, !isApplyingRemoteSettings else {
            return
        }

        isSaving = true
        defer { isSaving = false }

        do {
            DevLogger.shared.info("Updating Proactive Suggestions settings", context: logContext)
            let settings = try await apiClient.updateAmbientSuggestionSettings(update)
            apply(settings)
            statusMessage = successMessage
            DevLogger.shared.info(successMessage, context: logContext)
            NotificationCenter.default.post(name: .ambientSuggestionsSettingsChanged, object: nil)
            if let appDelegate = NSApplication.shared.delegate as? AppDelegate {
                await appDelegate.statusBarManager?.refreshAmbientSuggestionState()
            }
        } catch {
            if let revert {
                isApplyingRemoteSettings = true
                revert()
                isApplyingRemoteSettings = false
            } else if let loadedSettings {
                apply(loadedSettings)
            }
            statusMessage = "\(failureMessage): \(error.localizedDescription)"
            DevLogger.shared.error(statusMessage ?? failureMessage, context: logContext)
        }
    }
}

extension Notification.Name {
    static let ambientSuggestionsSettingsChanged = Notification.Name("AmbientSuggestionsSettingsChanged")
}
