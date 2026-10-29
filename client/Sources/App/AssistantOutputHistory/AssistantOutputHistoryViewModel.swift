import SwiftUI
import Combine

/// ViewModel managing AssistantSession history state — load, search, select, delete, resume.
class AssistantOutputHistoryViewModel: ObservableObject {

    // MARK: - Published State

    @Published var outputs: [AssistantOutputHistoryListItem] = []
    @Published var selectedOutput: AssistantOutputHistoryDetail? = nil
    @Published var selectedId: Int? = nil
    @Published var searchText: String = ""
    /// Filter sidebar entries by how the instruction was entered.
    /// `nil` = all, `"voice"` = mic input, `"text"` = typed input.
    @Published var inputModalityFilter: String? = nil
    @Published var isLoading: Bool = false
    @Published var isLoadingDetail: Bool = false
    @Published var errorMessage: String? = nil

    // Edit mode state
    @Published var isEditMode: Bool = false
    @Published var editableContent: String = ""

    // Save as sample state
    @Published var isSavingSample: Bool = false
    @Published var sampleSaved: Bool = false

    // MARK: - Private

    private var searchTask: Task<Void, Never>? = nil

    // MARK: - Load History

    @MainActor
    func loadHistory() async {
        isLoading = true
        errorMessage = nil

        do {
            let response: AssistantOutputHistoryResponse
            if searchText.isEmpty {
                response = try await APIClient.shared.listAssistantOutputHistory(
                    inputModality: inputModalityFilter,
                    limit: 50
                )
            } else {
                response = try await APIClient.shared.searchAssistantOutputHistory(
                    query: searchText,
                    inputModality: inputModalityFilter,
                    limit: 50
                )
            }

            outputs = response.outputs
            isLoading = false

            #if DEBUG
            DevLogger.shared.info("✅ Loaded \(response.outputs.count) AssistantSession outputs (modality: \(inputModalityFilter ?? "all"))", context: "AssistantOutputHistoryVM")
            #endif
        } catch {
            errorMessage = searchText.isEmpty ? "Failed to load history" : "Search failed"
            isLoading = false

            #if DEBUG
            DevLogger.shared.error("❌ Failed to load AssistantSession history: \(error)", context: "AssistantOutputHistoryVM")
            #endif
        }
    }

    // MARK: - Search (debounced)

    func triggerSearch() {
        searchTask?.cancel()
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 300_000_000) // 300ms debounce
            if !Task.isCancelled {
                await loadHistory()
            }
        }
    }

    // MARK: - Select AssistantSession Output

    @MainActor
    func selectOutput(id: Int) async {
        selectedId = id
        isLoadingDetail = true
        isEditMode = false
        editableContent = ""
        sampleSaved = false
        isSavingSample = false

        do {
            let detail = try await APIClient.shared.getAssistantOutputDetail(id: id)
            selectedOutput = detail
            isLoadingDetail = false

            #if DEBUG
            DevLogger.shared.info("✅ Loaded AssistantSession output detail: id=\(id) type=\(detail.outputType)", context: "AssistantOutputHistoryVM")
            #endif
        } catch {
            isLoadingDetail = false

            #if DEBUG
            DevLogger.shared.error("❌ Failed to load AssistantSession output detail \(id): \(error)", context: "AssistantOutputHistoryVM")
            #endif
        }
    }

    // MARK: - Delete

    @MainActor
    func deleteOutput(id: Int) async {
        do {
            let _ = try await APIClient.shared.deleteAssistantOutput(id: id)
            outputs.removeAll { $0.id == id }

            if selectedId == id {
                selectedId = nil
                selectedOutput = nil
            }

            #if DEBUG
            DevLogger.shared.info("✅ Deleted AssistantSession output \(id)", context: "AssistantOutputHistoryVM")
            #endif
        } catch {
            errorMessage = "Failed to delete output"

            #if DEBUG
            DevLogger.shared.error("❌ Failed to delete AssistantSession output \(id): \(error)", context: "AssistantOutputHistoryVM")
            #endif
        }
    }

    // MARK: - Modality Filter Toggle

    @MainActor
    func setInputModalityFilter(_ filter: String?) async {
        inputModalityFilter = filter
        await loadHistory()
    }

    // MARK: - Edit Mode

    func enterEditMode(outputText: String) {
        isEditMode = true
        editableContent = outputText
    }

    func cancelEditMode() {
        isEditMode = false
        editableContent = ""
    }

    @MainActor
    func applyEdits() {
        guard let detail = selectedOutput else { return }
        selectedOutput = AssistantOutputHistoryDetail(
            id: detail.id,
            outputType: detail.outputType,
            inputModality: detail.inputModality,
            outputText: editableContent,
            contextText: detail.contextText,
            explanationText: detail.explanationText,
            modelName: detail.modelName,
            timestamp: detail.timestamp,
            status: detail.status,
            refinementCount: detail.refinementCount,
            refinements: detail.refinements,
            appName: detail.appName,
            windowTitle: detail.windowTitle,
            screenCapturePath: detail.screenCapturePath,
            textSelection: detail.textSelection,
            userRequest: detail.userRequest,
            processingTimeMs: detail.processingTimeMs,
            wasInserted: detail.wasInserted,
            userRating: detail.userRating,
            userFeedback: detail.userFeedback
        )
        isEditMode = false

        #if DEBUG
        DevLogger.shared.info("Applied edits to AssistantSession output detail", context: "AssistantOutputHistoryVM")
        #endif
    }

    // MARK: - Save as Sample

    @MainActor
    func saveAsSample() async {
        let contentToSave = isEditMode && !editableContent.isEmpty ? editableContent : selectedOutput?.outputText ?? ""

        guard !contentToSave.isEmpty else {
            #if DEBUG
            DevLogger.shared.error("No content available to save as sample", context: "AssistantOutputHistoryVM")
            #endif
            return
        }

        guard !sampleSaved else { return }

        isSavingSample = true

        do {
            var payload: [String: Any] = ["content": contentToSave]
            if let appName = selectedOutput?.appName {
                payload["metadata"] = ["app_name": appName]
            }

            let jsonData = try JSONSerialization.data(withJSONObject: payload)
            let responseData = try await APIClient.shared.post("/user/writing-samples", body: jsonData)

            struct SaveSampleResponse: Codable {
                let status: String
                let sample_id: String?
                let error: String?
            }

            let response = try JSONDecoder().decode(SaveSampleResponse.self, from: responseData)

            if response.status == "saved" {
                sampleSaved = true
                #if DEBUG
                DevLogger.shared.info("Saved AssistantSession output as writing sample (ID: \(response.sample_id ?? "unknown"))", context: "AssistantOutputHistoryVM")
                #endif
            }
            isSavingSample = false
        } catch {
            isSavingSample = false
            #if DEBUG
            DevLogger.shared.error("Failed to save as sample: \(error)", context: "AssistantOutputHistoryVM")
            #endif
        }
    }

    // MARK: - Resume Refinement

    /// Open the unified AssistantSession widget pre-populated from a history row.
    ///
    /// Hits `POST /assistant-sessions/rehydrate-from-history/{id}` so the
    /// backend creates a fresh `AssistantSessionService` session keyed by a
    /// new `session_id`. The widget opens in `.completed` state with that
    /// `session_id` wired in, so the existing Refine controls (which post
    /// to `/assistant-sessions/{session_id}/refine`) work immediately
    /// against the rehydrated session.
    ///
    /// Pre-AssistantSession history rows persisted with `output_type != "assistant_session"`
    /// (the legacy "regular" / Enhanced Suggestion path) are intentionally
    /// not rehydratable post-consolidation -- the widget, manager, and
    /// resume route they depended on were removed in Phase 1. Those rows
    /// surface a user-visible "not supported" error rather than silently
    /// failing or attempting to call a deleted code path.
    ///
    /// **Bug fix (Phase D2):** Previously gated on `type == "voice"`, but
    /// the schema migration in Phase A rewrote all `'voice'` rows to
    /// `'assistant_session'`, so the gate would never pass for any row visible in
    /// the sidebar today. Now gates on `outputType == "assistant_session"`, which
    /// matches current data and accepts both voice- and text-entered
    /// rows.
    @MainActor
    func resumeRefinement(id: Int, outputType: String, input: AssistantSessionRefinementInput) async {
        guard outputType == "assistant_session" else {
            errorMessage = "Legacy outputs can no longer be resumed."

            #if DEBUG
            DevLogger.shared.warning(
                "⚠️ Refusing to rehydrate legacy AssistantSession output \(id) (output_type=\(outputType)) -- non-assistant_session rows are unsupported post-consolidation",
                context: "AssistantOutputHistoryVM"
            )
            #endif
            return
        }

        do {
            let resume = try await APIClient.shared.rehydrateAssistantSession(id: id)
            AssistantSessionWindowController.show(rehydratedFrom: resume, input: input)

            #if DEBUG
            DevLogger.shared.info(
                "▶️ Rehydrated AssistantSession \(id) into session \(resume.sessionId)",
                context: "AssistantOutputHistoryVM"
            )
            #endif
        } catch {
            errorMessage = "Failed to resume output"

            #if DEBUG
            DevLogger.shared.error("❌ Failed to resume AssistantSession output \(id): \(error)", context: "AssistantOutputHistoryVM")
            #endif
        }
    }
}
