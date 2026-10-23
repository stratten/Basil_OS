import SwiftUI
import Combine
import Foundation

// MARK: - Model Selection (typed-input modality)
//
// Recovered verbatim from `EnhancedSuggestionInputViewModel.loadModels()`
// / `selectModel(_:)`. Same upstream API surface (`ModelServiceInfo.
// loadAvailableModels()` / `loadModelSettings()` / `getRecommendedModelId(...)`)
// so the only change vs. the ES implementation is the host type.
//
// Speak modality intentionally does NOT call this yet: a hover-revealed
// minimal selector for the recording UI is a separate, later effort.
// Until then, `selectedModelId` is populated only when the typed slot
// has rendered and `loadModelsIfNeeded()` has fired from its `.onAppear`.
extension AssistantSessionViewModel {

    /// Loads reasoning models + the user's recommended default into the
    /// picker state. Idempotent: callers may invoke this on every typed
    /// slot mount; the no-op short-circuit avoids redundant network
    /// round-trips when the user toggles Speak ↔ Type repeatedly.
    @MainActor
    func loadModelsIfNeeded() async {
        guard availableModels.isEmpty && !isLoadingModels else { return }
        await loadModels()
    }

    @MainActor
    func loadModels() async {
        isLoadingModels = true

        #if DEBUG
        DevLogger.shared.info("🔍 Loading available reasoning models for typed-input slot", context: "AssistantSession.Models")
        #endif

        // Use the shared model loading functionality (same source ES used).
        self.availableModels = await ModelServiceInfo.loadAvailableModels()

        // Split models into local and API for UI organization.
        self.localModels = self.availableModels.filter { !$0.isApiModel }
        self.apiModels = self.availableModels.filter { $0.isApiModel }

        // Try to load model settings to get the API preference and
        // recommended model. Mirrors ES: on failure we deliberately
        // leave `selectedModelId == nil` rather than guessing -- the
        // backend will fall back to its configured default model when
        // `model_id` is omitted from the request.
        do {
            let settings = try await ModelServiceInfo.loadModelSettings()
            self.useApiModels = settings.useApiModels

            self.selectedModelId = ModelServiceInfo.getRecommendedModelId(
                settings: settings,
                availableModels: self.availableModels
            )

            #if DEBUG
            DevLogger.shared.info("✅ Selected model: \(self.selectedModelId ?? "none")", context: "AssistantSession.Models")
            #endif
        } catch {
            self.selectedModelId = nil

            #if DEBUG
            DevLogger.shared.error("❌ Failed to load model settings: \(error.localizedDescription)", context: "AssistantSession.Models")
            DevLogger.shared.error("❌ NO FALLBACK USED - No model will be selected; backend default will apply", context: "AssistantSession.Models")
            #endif
        }

        isLoadingModels = false
    }

    @MainActor
    func selectModel(_ modelId: String) {
        self.selectedModelId = modelId

        #if DEBUG
        DevLogger.shared.info("🔄 Selected reasoning model: \(modelId)", context: "AssistantSession.Models")
        #endif
    }
}
