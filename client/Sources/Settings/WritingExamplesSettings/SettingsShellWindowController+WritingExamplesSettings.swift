import AppKit
@preconcurrency import WebKit

extension SettingsShellWindowController {
    func wireWritingExamplesSettingsWebView(_ writingExamplesWebView: ReactWritingExamplesSettingsWebView) {
        writingExamplesWebView.onReady = { [weak self] in
            Task { @MainActor in
                await self?.loadWritingExamplesAndSendInit()
            }
        }
        writingExamplesWebView.onSetContextFilter = { [weak self] filter in
            Task { @MainActor in
                await self?.handleWritingExamplesFilterChange(filter)
            }
        }
        writingExamplesWebView.onRequestDeleteSample = { [weak self] requestId, id in
            Task { @MainActor in
                await self?.presentDeleteSampleConfirmation(requestId: requestId, id: id)
            }
        }
        writingExamplesWebView.onRequestDeleteAllSamples = { [weak self] requestId, filter in
            Task { @MainActor in
                await self?.presentDeleteAllSamplesConfirmation(requestId: requestId, filter: filter)
            }
        }
        writingExamplesWebView.onRequestUpdateSample = { [weak self] requestId, id, content, contextType, recipient in
            Task { @MainActor in
                await self?.updateWritingSample(
                    requestId: requestId,
                    id: id,
                    content: content,
                    contextType: contextType,
                    recipient: recipient
                )
            }
        }
        writingExamplesWebView.onRequestAddSample = { [weak self] requestId, content, contextType, recipient in
            Task { @MainActor in
                await self?.addWritingSample(
                    requestId: requestId,
                    content: content,
                    contextType: contextType,
                    recipient: recipient
                )
            }
        }
        writingExamplesWebView.onAnalyzeStyle = { [weak self] requestId, filter in
            Task { @MainActor in
                await self?.analyzeWritingStyle(requestId: requestId, filter: filter)
            }
        }
        writingExamplesWebView.onCopySampleToClipboard = { content in
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(content, forType: .string)
        }
    }

    private func loadWritingExamplesAndSendInit() async {
        guard let writingExamplesWebView else { return }
        writingExamplesCurrentFilter = .all
        writingExamplesFilterGeneration += 1
        let generation = writingExamplesFilterGeneration
        do {
            let (samples, style) = try await fetchWritingExamplesSamplesAndStyle(for: .all)
            guard generation == writingExamplesFilterGeneration else { return }
            writingExamplesSamplesCache = samples
            writingExamplesStyleCache = style
            writingExamplesWebView.sendInit(activeFilter: .all, samples: samples, styleProfile: style, isLoadingSamples: false)
        } catch {
            guard generation == writingExamplesFilterGeneration else { return }
            writingExamplesWebView.sendLoadError(message: "Failed to load Writing Examples settings.")
        }
    }

    private func handleWritingExamplesFilterChange(_ filter: ReactWritingExamplesFilter) async {
        guard let writingExamplesWebView else { return }
        writingExamplesCurrentFilter = filter
        writingExamplesFilterGeneration += 1
        let generation = writingExamplesFilterGeneration
        writingExamplesWebView.sendSnapshot(
            activeFilter: filter,
            samples: writingExamplesSamplesCache,
            styleProfile: nil,
            isLoadingSamples: true
        )
        do {
            let (samples, style) = try await fetchWritingExamplesSamplesAndStyle(for: filter)
            guard generation == writingExamplesFilterGeneration else { return }
            writingExamplesSamplesCache = samples
            writingExamplesStyleCache = style
            writingExamplesWebView.sendSnapshot(activeFilter: filter, samples: samples, styleProfile: style, isLoadingSamples: false)
        } catch {
            guard generation == writingExamplesFilterGeneration else { return }
            writingExamplesWebView.sendLoadError(message: "Failed to load writing samples for the selected filter.")
        }
    }

    private func fetchWritingExamplesSamplesAndStyle(for filter: ReactWritingExamplesFilter) async throws -> (samples: [WritingSample], style: CommunicationStyleProfile?) {
        let response = try await APIClient.shared.listWritingSamples(contextType: filter.apiValue, limit: 100, offset: 0)
        guard let apiValue = filter.apiValue else {
            return (response.samples, nil)
        }
        let style = try? await APIClient.shared.getCommunicationStyle(contextType: apiValue)
        return (response.samples, style)
    }

    private func refreshWritingExamplesAfterMutation(requestId: String) async {
        guard let writingExamplesWebView else { return }
        let filter = writingExamplesCurrentFilter
        let generation = writingExamplesFilterGeneration
        do {
            let (samples, style) = try await fetchWritingExamplesSamplesAndStyle(for: filter)
            if generation == writingExamplesFilterGeneration {
                writingExamplesSamplesCache = samples
                writingExamplesStyleCache = style
                writingExamplesWebView.sendSnapshot(activeFilter: filter, samples: samples, styleProfile: style, isLoadingSamples: false)
            }
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        } catch {
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "success", message: "Sample saved, but the list could not be refreshed.")
        }
    }

    private func updateWritingSample(
        requestId: String,
        id: String,
        content: String,
        contextType: String,
        recipient: String
    ) async {
        guard let writingExamplesWebView else { return }
        guard !contextType.isEmpty, contextType != ReactWritingExamplesFilter.all.rawValue else {
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Choose a writing context.")
            return
        }
        let trimmedRecipient = recipient.trimmingCharacters(in: .whitespacesAndNewlines)
        do {
            try await APIClient.shared.updateWritingSample(
                id: id,
                content: content,
                contextType: contextType,
                recipient: trimmedRecipient.isEmpty ? nil : trimmedRecipient
            )
        } catch {
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to update sample.")
            return
        }
        await refreshWritingExamplesAfterMutation(requestId: requestId)
    }

    private func addWritingSample(
        requestId: String,
        content: String,
        contextType: String,
        recipient: String?
    ) async {
        guard let writingExamplesWebView else { return }
        guard let filter = ReactWritingExamplesFilter(rawValue: contextType), filter != .all else {
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Choose a writing context.")
            return
        }
        do {
            try await APIClient.shared.addWritingSample(content: content, contextType: filter.rawValue, recipient: recipient)
        } catch {
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to add sample.")
            return
        }
        await refreshWritingExamplesAfterMutation(requestId: requestId)
    }

    private func presentDeleteSampleConfirmation(requestId: String, id: String) async {
        guard let writingExamplesWebView else { return }
        let alert = Self.makeDeleteSampleConfirmationAlert()
        guard alert.runModal() == .alertSecondButtonReturn else {
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "cancelled", message: nil)
            return
        }
        do {
            try await APIClient.shared.deleteWritingSample(id: id)
            writingExamplesSamplesCache.removeAll { $0.id == id }
            writingExamplesWebView.sendSnapshot(
                activeFilter: writingExamplesCurrentFilter,
                samples: writingExamplesSamplesCache,
                styleProfile: writingExamplesStyleCache,
                isLoadingSamples: false
            )
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        } catch {
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to delete sample.")
        }
    }

    private func presentDeleteAllSamplesConfirmation(requestId: String, filter: ReactWritingExamplesFilter) async {
        guard let writingExamplesWebView else { return }
        guard filter == writingExamplesCurrentFilter else {
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Writing samples changed before deletion could begin.")
            return
        }
        let alert = Self.makeDeleteAllSamplesConfirmationAlert(filter: filter)
        guard alert.runModal() == .alertSecondButtonReturn else {
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "cancelled", message: nil)
            return
        }
        do {
            _ = try await APIClient.shared.deleteAllWritingSamples(contextType: filter.apiValue)
            writingExamplesSamplesCache = []
            writingExamplesWebView.sendSnapshot(
                activeFilter: filter,
                samples: [],
                styleProfile: writingExamplesStyleCache,
                isLoadingSamples: false
            )
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        } catch {
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to delete all samples.")
        }
    }

    private func analyzeWritingStyle(requestId: String, filter: ReactWritingExamplesFilter) async {
        guard let writingExamplesWebView else { return }
        guard filter == writingExamplesCurrentFilter else {
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Writing samples changed before analysis could begin.")
            return
        }
        guard let apiValue = filter.apiValue else {
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Cannot analyze style for all contexts.")
            return
        }
        do {
            let profile = try await APIClient.shared.analyzeStyle(contextType: apiValue, forceReanalysis: true)
            writingExamplesStyleCache = profile
            writingExamplesWebView.sendSnapshot(
                activeFilter: filter,
                samples: writingExamplesSamplesCache,
                styleProfile: profile,
                isLoadingSamples: false
            )
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        } catch {
            writingExamplesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to analyze style.")
        }
    }

    private static func filterDisplayName(_ filter: ReactWritingExamplesFilter) -> String {
        switch filter {
        case .all: return "All"
        case .emailReply: return "Email Reply"
        case .emailCompose: return "Email Compose"
        case .socialMedia: return "Social Media"
        case .document: return "Document"
        }
    }

    static func makeDeleteSampleConfirmationAlert() -> NSAlert {
        let alert = NSAlert()
        alert.messageText = "Delete Writing Sample"
        alert.informativeText = "Are you sure you want to delete this writing sample? This action cannot be undone."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Cancel")
        let deleteButton = alert.addButton(withTitle: "Delete")
        deleteButton.hasDestructiveAction = true
        return alert
    }

    static func makeDeleteAllSamplesConfirmationAlert(filter: ReactWritingExamplesFilter) -> NSAlert {
        let alert = NSAlert()
        alert.messageText = "Delete All Writing Samples"
        let label = filterDisplayName(filter)
        alert.informativeText = filter == .all
            ? "Are you sure you want to delete all writing samples? This action cannot be undone."
            : "Are you sure you want to delete all \(label) samples? This action cannot be undone."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Cancel")
        let deleteButton = alert.addButton(withTitle: "Delete All")
        deleteButton.hasDestructiveAction = true
        return alert
    }
}
