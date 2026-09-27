import Foundation

extension SettingsShellWindowController {
    func wireTranscriptionSettingsWebView(_ webView: ReactTranscriptionSettingsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadTranscriptionSettingsAndSendInit() }
        }
        webView.onRequestUpdateSelectedModel = { [weak self] requestId, modelId in
            self?.performTranscriptionSettingsUpdate(requestId: requestId) { vm in await vm.updateSelectedModel(modelId) }
        }
        webView.onRequestUpdateUnloadDelay = { [weak self] requestId, seconds in
            self?.performTranscriptionSettingsUpdate(requestId: requestId) { vm in
                guard let delay = TranscriptionModelUnloadDelay(rawValue: seconds) else { return false }
                return await vm.updateUnloadDelay(delay)
            }
        }
        webView.onRequestUpdateAutoPaste = { [weak self] requestId, enabled in
            self?.performTranscriptionSettingsUpdate(requestId: requestId) { vm in await vm.updateAutoPaste(enabled) }
        }
        webView.onRequestUpdateAutoCloseOnPaste = { [weak self] requestId, enabled in
            self?.performTranscriptionSettingsUpdate(requestId: requestId) { vm in await vm.updateAutoCloseOnPaste(enabled) }
        }
        webView.onRequestUpdateMeetingDetectionStartup = { [weak self] requestId, enabled in
            self?.performTranscriptionSettingsUpdate(requestId: requestId) { vm in await vm.updateMeetingDetectionStartup(enabled) }
        }
        webView.onRequestUpdatePushToTalk = { [weak self] requestId, enabled in
            self?.performTranscriptionSettingsUpdate(requestId: requestId) { vm in await vm.updatePushToTalk(enabled) }
        }
        webView.onRequestUpdatePushToTalkThreshold = { [weak self] requestId, thresholdMs in
            self?.performTranscriptionSettingsUpdate(requestId: requestId) { vm in
                let clamped = min(5000, max(500, thresholdMs))
                return await vm.updatePushToTalkThreshold(clamped)
            }
        }
        webView.onRequestUpdateTextReplacements = { [weak self] requestId, rules in
            self?.performTranscriptionSettingsUpdate(requestId: requestId) { vm in
                await vm.updateTextReplacements(rules)
            }
        }
        webView.onMalformedIntent = { type in
            #if DEBUG
            DevLogger.shared.error("[TRANSCRIPTION_SETTINGS] Malformed intent: \(type)", context: "SettingsShellWindowController")
            #endif
        }
    }

    private func loadTranscriptionSettingsAndSendInit() async {
        transcriptionSettingsLoadGeneration += 1
        let generation = transcriptionSettingsLoadGeneration
        let vm = transcriptionSettingsViewModel
        let didLoad = await vm.loadSettings()
        await vm.loadModels()
        guard generation == transcriptionSettingsLoadGeneration else { return }
        guard let webView = transcriptionSettingsWebView else { return }
        if !didLoad {
            webView.sendLoadError(message: "Failed to load Transcription settings.")
            return
        }
        webView.sendInit(viewModel: vm)
    }

    private func performTranscriptionSettingsUpdate(
        requestId: String,
        apply: @escaping (TranscriptionSettingsViewModel) async -> Bool
    ) {
        Task { @MainActor in
            guard let webView = transcriptionSettingsWebView else { return }
            let vm = transcriptionSettingsViewModel
            let succeeded = await apply(vm)
            webView.sendSnapshot(viewModel: vm)
            webView.sendIntentResult(
                requestId: requestId,
                status: succeeded ? "success" : "error",
                message: succeeded ? nil : "Failed to save the setting."
            )
        }
    }
}
