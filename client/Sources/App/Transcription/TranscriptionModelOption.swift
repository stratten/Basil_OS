import Foundation

/// A single transcription model the user can select in any picker UI.
///
/// Originally lived inline in `TranscriptionSettingsViewModel.swift`.
/// Promoted to its own file so the in-widget transcription model picker
/// (`TranscriptionModelPickerMenu`) can share the same type as the
/// Settings tab without each surface re-implementing model loading.
///
/// Field shape is intentionally identical to the prior inline
/// definition so all existing call sites continue to compile unchanged.
struct TranscriptionModelOption: Identifiable, Hashable {
    /// Backend identifier. May be a cloud model id ("whisper-1"), a
    /// Parakeet model id, or a HuggingFace Whisper display name -- the
    /// backend swap endpoint accepts any of these forms.
    let id: String

    /// Human-readable label shown in pickers.
    let displayName: String

    /// True for cloud (API) models, false for locally-installed models.
    let isApiModel: Bool

    /// Cloud provider (e.g. "openai") for API models. Nil for local.
    let provider: String?
}

extension TranscriptionModelOption {
    /// Result of a unified model load: the available options grouped by
    /// kind, plus the canonical currently-selected model id read from
    /// `/settings/models`. Surfaces consume this to render a picker.
    struct LoadResult {
        let apiModels: [TranscriptionModelOption]
        let localModels: [TranscriptionModelOption]
        let currentModelId: String

        /// Convenience accessor for surfaces that just want a flat,
        /// stable-ordered list (local first, then API). Mirrors the
        /// section ordering used by the Settings tab.
        var allOptions: [TranscriptionModelOption] {
            localModels + apiModels
        }
    }

    /// Load the union of installed local transcription models and
    /// enabled API transcription models, plus the currently-selected
    /// model id.
    ///
    /// This consolidates load logic that today is duplicated across
    /// `TranscriptionSettingsViewModel.loadModels()` and
    /// `LiveTranscriptionViewModel.loadAvailableModels()`. New code
    /// (the in-widget picker) calls this directly; existing call sites
    /// stay on their inline implementations until a follow-up cleanup.
    ///
    /// Errors from individual sub-fetches are tolerated -- e.g. if API
    /// model fetch fails, local models are still returned. A failure
    /// in the current-id fetch falls back to the empty string so the
    /// UI can still render the list (just without a checkmark).
    static func loadAll() async -> LoadResult {
        let api = APIClient.shared
        var localOptions: [TranscriptionModelOption] = []
        var apiOptions: [TranscriptionModelOption] = []
        var currentId = ""

        // Local models
        do {
            let data = try await api.get("/models/installed")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase

            struct ModelVariant: Codable {
                let name: String
                let capabilities: [String]?
                let valid: Bool?
            }
            struct ModelType: Codable {
                let variants: [String: ModelVariant]
            }

            let response = try decoder.decode([String: ModelType].self, from: data)
            for (_, modelType) in response {
                for (_, variant) in modelType.variants {
                    if variant.valid == true,
                       let capabilities = variant.capabilities,
                       capabilities.contains("transcription") {
                        localOptions.append(
                            TranscriptionModelOption(
                                id: variant.name,
                                displayName: variant.name,
                                isApiModel: false,
                                provider: nil
                            )
                        )
                    }
                }
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error(
                "TranscriptionModelOption.loadAll: failed to load local models: \(error)",
                context: "TranscriptionModelPicker"
            )
            #endif
        }

        // API models
        do {
            let response = try await api.getApiTranscriptionModels()
            if response.apiTranscriptionModelsEnabled {
                for model in response.models {
                    apiOptions.append(
                        TranscriptionModelOption(
                            id: model.id,
                            displayName: model.displayName,
                            isApiModel: true,
                            provider: model.provider
                        )
                    )
                }
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error(
                "TranscriptionModelOption.loadAll: failed to load API models: \(error)",
                context: "TranscriptionModelPicker"
            )
            #endif
        }

        // Canonical current id
        do {
            currentId = try await api.getCurrentTranscriptionModel()
        } catch {
            #if DEBUG
            DevLogger.shared.error(
                "TranscriptionModelOption.loadAll: failed to fetch current model id: \(error)",
                context: "TranscriptionModelPicker"
            )
            #endif
        }

        return LoadResult(
            apiModels: apiOptions,
            localModels: localOptions.sorted { $0.displayName < $1.displayName },
            currentModelId: currentId
        )
    }
}
