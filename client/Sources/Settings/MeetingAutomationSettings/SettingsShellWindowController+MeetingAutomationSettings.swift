import Foundation

extension SettingsShellWindowController {
    func wireMeetingAutomationSettingsWebView(_ webView: ReactMeetingAutomationSettingsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadMeetingAutomationSettingsAndSendInit() }
        }
        webView.onRequestUpdateAutoRetranscribeOnStop = { [weak self] requestId, enabled in
            self?.performMeetingAutomationUpdate(requestId: requestId) { vm in await vm.updateAutoRetranscribeOnStop(enabled) }
        }
        webView.onRequestUpdateAutoRetranscribeDuringRecording = { [weak self] requestId, enabled in
            self?.performMeetingAutomationUpdate(requestId: requestId) { vm in await vm.updateAutoRetranscribeDuringRecording(enabled) }
        }
        webView.onRequestUpdateRetranscribeWindowMinutes = { [weak self] requestId, minutes in
            self?.performMeetingAutomationUpdate(requestId: requestId) { vm in await vm.updateRetranscribeWindowMinutes(Int(minutes)) }
        }
        webView.onRequestUpdateAutoAnalyzeOnComplete = { [weak self] requestId, enabled in
            self?.performMeetingAutomationUpdate(requestId: requestId) { vm in await vm.updateAutoAnalyzeOnComplete(enabled) }
        }
        webView.onRequestUpdateAutoAnalyzeMode = { [weak self] requestId, mode, isOn in
            self?.performMeetingAutomationUpdate(requestId: requestId) { vm in await vm.updateAutoAnalyzeMode(mode, isOn: isOn) }
        }
        webView.onRequestUpdateAutoAnalyzeCustomInstructions = { [weak self] requestId, text in
            self?.performMeetingAutomationUpdate(requestId: requestId) { vm in await vm.updateAutoAnalyzeCustomInstructions(text) }
        }
        webView.onRequestUpdateAutoAnalyzeTiming = { [weak self] requestId, timing in
            self?.performMeetingAutomationUpdate(requestId: requestId) { vm in await vm.updateAutoAnalyzeTiming(timing) }
        }
        webView.onRequestUpdateLiveTranscriptionByDefault = { [weak self] requestId, enabled in
            self?.performMeetingAutomationUpdate(requestId: requestId) { vm in await vm.updateLiveTranscriptionByDefault(enabled) }
        }
        webView.onMalformedIntent = { type in
            #if DEBUG
            DevLogger.shared.error("[MEETING_AUTOMATION_SETTINGS] Malformed intent: \(type)", context: "SettingsShellWindowController")
            #endif
        }
    }

    private func loadMeetingAutomationSettingsAndSendInit() async {
        meetingAutomationLoadGeneration += 1
        let generation = meetingAutomationLoadGeneration
        let vm = transcriptionAutomationViewModel
        let didLoad = await vm.loadSettings()
        guard generation == meetingAutomationLoadGeneration else { return }
        guard let webView = meetingAutomationWebView else { return }
        if !didLoad {
            webView.sendLoadError(message: "Failed to load Meeting Automation settings.")
            return
        }
        webView.sendInit(viewModel: vm)
    }

    private func performMeetingAutomationUpdate(
        requestId: String,
        apply: @escaping (TranscriptionSettingsViewModel) async -> Bool
    ) {
        Task { @MainActor in
            guard let webView = meetingAutomationWebView else { return }
            let vm = transcriptionAutomationViewModel
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
