import Combine
import Foundation

extension SettingsShellWindowController {
    func wireTranscriptionHistoryWebView(_ webView: ReactTranscriptionHistoryWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadTranscriptionHistoryAndSendInit() }
        }
        webView.onRequestSetTimeFrame = { [weak self] requestId, timeFrameId in
            self?.performTranscriptionHistoryTimeFrameChange(requestId: requestId, timeFrameId: timeFrameId)
        }
        webView.onRequestSetSearchText = { [weak self] requestId, text in
            self?.performTranscriptionHistorySearch(requestId: requestId, text: text)
        }
        webView.onRequestPlayAudio = { [weak self] requestId, transcriptionId in
            self?.performTranscriptionHistoryRowAction(requestId: requestId, transcriptionId: transcriptionId) { vm, record in
                await vm.playAudio(for: record)
            }
        }
        webView.onRequestStopAudio = { [weak self] requestId in
            guard let self, let webView = self.transcriptionHistoryWebView else { return }
            self.transcriptionHistoryViewModel.stopAudio()
            webView.sendSnapshot(viewModel: self.transcriptionHistoryViewModel)
            webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        }
        webView.onRequestRetranscribe = { [weak self] requestId, transcriptionId, modelId in
            self?.performTranscriptionHistoryRowAction(requestId: requestId, transcriptionId: transcriptionId) { vm, record in
                await vm.retranscribe(record, modelId: modelId)
            }
        }
        webView.onRequestDeleteTranscription = { [weak self] requestId, transcriptionId in
            self?.performTranscriptionHistoryRowAction(requestId: requestId, transcriptionId: transcriptionId) { vm, record in
                await vm.deleteTranscription(record)
            }
        }
        webView.onMalformedIntent = { type in
            #if DEBUG
            DevLogger.shared.error("[TRANSCRIPTION_HISTORY] Malformed intent: \(type)", context: "SettingsShellWindowController")
            #endif
        }

        transcriptionHistoryObserverCancellable = transcriptionHistoryViewModel.objectWillChange
            .debounce(for: .milliseconds(150), scheduler: DispatchQueue.main)
            .sink { [weak self] _ in
                guard let self, let webView = self.transcriptionHistoryWebView else { return }
                webView.sendSnapshot(viewModel: self.transcriptionHistoryViewModel)
            }
    }

    private func loadTranscriptionHistoryAndSendInit() async {
        transcriptionHistoryLoadGeneration += 1
        let generation = transcriptionHistoryLoadGeneration
        let vm = transcriptionHistoryViewModel
        await vm.loadTranscriptions(days: vm.selectedTimeFrame.days)
        guard generation == transcriptionHistoryLoadGeneration else { return }
        guard let webView = transcriptionHistoryWebView else { return }
        webView.sendInit(viewModel: vm)
    }

    private static func timeFrame(for id: String) -> TranscriptionHistoryViewModel.TimeFrame? {
        switch id {
        case "day": return .day
        case "week": return .week
        case "month": return .month
        case "all": return .all
        default: return nil
        }
    }

    private func performTranscriptionHistoryTimeFrameChange(requestId: String, timeFrameId: String) {
        Task { @MainActor in
            guard let webView = transcriptionHistoryWebView else { return }
            guard let timeFrame = Self.timeFrame(for: timeFrameId) else {
                webView.sendIntentResult(requestId: requestId, status: "error", message: "Unrecognized time frame.")
                return
            }
            let vm = transcriptionHistoryViewModel
            vm.selectedTimeFrame = timeFrame
            await vm.loadTranscriptions(days: timeFrame.days)
            webView.sendSnapshot(viewModel: vm)
            webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        }
    }

    private func performTranscriptionHistorySearch(requestId: String, text: String) {
        Task { @MainActor in
            guard let webView = transcriptionHistoryWebView else { return }
            let vm = transcriptionHistoryViewModel
            vm.searchText = text
            // Reuses the ViewModel's own 300ms debounce (`performSearch`),
            // exactly like the native search field's `onTextChange`
            // callback -- see TranscriptionSearchField in
            // TranscriptionHistoryView.swift.
            vm.performSearch()
            webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        }
    }

    private func performTranscriptionHistoryRowAction(
        requestId: String,
        transcriptionId: String,
        apply: @escaping (TranscriptionHistoryViewModel, TranscriptionRecord) async -> Bool
    ) {
        Task { @MainActor in
            guard let webView = transcriptionHistoryWebView else { return }
            let vm = transcriptionHistoryViewModel
            guard let record = vm.transcriptions.first(where: { $0.id == transcriptionId }) else {
                webView.sendIntentResult(requestId: requestId, status: "error", message: "This transcription is no longer available.")
                return
            }
            let succeeded = await apply(vm, record)
            webView.sendSnapshot(viewModel: vm)
            webView.sendIntentResult(
                requestId: requestId,
                status: succeeded ? "success" : "error",
                message: succeeded ? nil : (vm.error ?? "The action failed.")
            )
        }
    }
}
