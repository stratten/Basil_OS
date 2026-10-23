import Foundation

extension TranscriptionWidgetViewModel {
    /// Refresh the list of selectable transcription models and the
    /// canonical current selection.
    ///
    /// Errors are intentionally swallowed -- the picker is a secondary
    /// affordance and we never want a transient API hiccup to crash or
    /// disable the widget itself. On failure the lists stay at their
    /// last-known values (empty on first call).
    func loadAvailableTranscriptionModels() async {
        let result = await TranscriptionModelOption.loadAll()
        self.availableTranscriptionModels = result.allOptions
        if !result.currentModelId.isEmpty {
            self.currentTranscriptionModelId = result.currentModelId
        }
        #if DEBUG
        DevLogger.shared.info(
            "Loaded \(result.allOptions.count) transcription models; current = '\(self.currentTranscriptionModelId)'",
            context: "TranscriptionWidget"
        )
        #endif
    }

    /// Atomically swap the active transcription model.
    ///
    /// Calls `POST /settings/transcription/model/swap` which (a) writes
    /// the preference, (b) unloads the current in-memory model, and
    /// (c) loads the new one. While the call is in flight we publish
    /// `isSwappingTranscriptionModel = true` so the picker can render a
    /// spinner in place of its label.
    ///
    /// Guards:
    /// - No-op if `id` already matches `currentTranscriptionModelId`.
    ///
    /// Allowed during recording. The audio is still being buffered in
    /// `AudioCaptureService` and has not been submitted for
    /// transcription, so swapping the model here just changes which
    /// model will run on the eventual stop. The chevron remains
    /// interactable mid-record on purpose.
    ///
    /// On failure the published `currentTranscriptionModelId` is left
    /// at its prior value so the picker reflects what is actually
    /// loaded server-side (the backend route also reverts the
    /// preference on load failure).
    func swapTranscriptionModel(to id: String) async {
        let trimmed = id.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        guard trimmed != currentTranscriptionModelId else { return }

        let previousId = currentTranscriptionModelId
        isSwappingTranscriptionModel = true
        // Optimistically reflect the new selection; we'll revert if the
        // backend swap fails. This makes the checkmark animation feel
        // immediate instead of waiting on the round trip.
        currentTranscriptionModelId = trimmed
        defer { isSwappingTranscriptionModel = false }

        do {
            let response = try await APIClient.shared.swapTranscriptionModel(trimmed)
            // Trust the server's canonical id -- handles cases where the
            // user passed a display name that the backend normalized.
            currentTranscriptionModelId = response.modelId
            if response.activationStatus == "pending" {
                self.error = "The selected model will activate after the current transcription finishes."
            }
            #if DEBUG
            DevLogger.shared.info(
                "Swapped transcription model to '\(response.modelId)' (loaded=\(response.loaded), activation=\(response.activationStatus ?? "active"), kind=\(response.serviceKind), \(response.elapsedMs)ms, no_op=\(response.noOp))",
                context: "TranscriptionWidget"
            )
            #endif
        } catch {
            currentTranscriptionModelId = previousId
            self.error = "Failed to switch transcription model: \(error.localizedDescription)"
            #if DEBUG
            DevLogger.shared.error(
                "Transcription model swap failed: \(error)",
                context: "TranscriptionWidget"
            )
            #endif
        }
    }
}

