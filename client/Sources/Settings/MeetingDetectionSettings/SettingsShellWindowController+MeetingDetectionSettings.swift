import AppKit
@preconcurrency import WebKit

extension SettingsShellWindowController {
    func wireMeetingDetectionSettingsWebView(_ webView: ReactMeetingDetectionSettingsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadMeetingDetectionSettingsAndSendInit() }
        }
        webView.onRequestUpdateEnabled = { [weak self] requestId, enabled in
            self?.performMeetingDetectionUpdate(requestId: requestId) { vm in await vm.updateEnabled(enabled) }
        }
        webView.onRequestUpdateMode = { [weak self] requestId, mode in
            self?.performMeetingDetectionUpdate(requestId: requestId) { vm in await vm.updateMode(mode) }
        }
        webView.onRequestUpdatePollSeconds = { [weak self] requestId, seconds in
            self?.performMeetingDetectionUpdate(requestId: requestId) { vm in await vm.updatePollSeconds(seconds) }
        }
        webView.onRequestUpdateCooldownMinutes = { [weak self] requestId, minutes in
            self?.performMeetingDetectionUpdate(requestId: requestId) { vm in await vm.updateCooldownMinutes(minutes) }
        }
        webView.onRequestUpdateUseCalendarEnrichment = { [weak self] requestId, enabled in
            self?.performMeetingDetectionUpdate(requestId: requestId) { vm in await vm.updateUseCalendarEnrichment(enabled) }
        }
        webView.onRequestUpdateRequireCalendarMatch = { [weak self] requestId, enabled in
            self?.performMeetingDetectionUpdate(requestId: requestId) { vm in await vm.updateRequireCalendarMatch(enabled) }
        }
        webView.onRequestUpdateAutoEnd = { [weak self] requestId, enabled in
            self?.performMeetingDetectionUpdate(requestId: requestId) { vm in await vm.updateAutoEnd(enabled) }
        }
        webView.onRequestUpdateInactivityTimeoutMinutes = { [weak self] requestId, minutes in
            self?.performMeetingDetectionUpdate(requestId: requestId) { vm in await vm.updateInactivityTimeout(minutes) }
        }
        webView.onRequestUpdateExcludedAppNames = { [weak self] requestId, names in
            self?.performMeetingDetectionUpdate(requestId: requestId) { vm in
                vm.excludedAppNamesText = names.joined(separator: "\n")
                await vm.updateExcludedAppNames()
            }
        }
        webView.onRequestAddExcludedBundleId = { [weak self] requestId, bundleId in
            self?.performMeetingDetectionUpdate(requestId: requestId) { vm in await vm.addExcludedBundleId(bundleId) }
        }
        webView.onRequestRemoveExcludedBundleId = { [weak self] requestId, bundleId in
            self?.performMeetingDetectionUpdate(requestId: requestId) { vm in await vm.removeExcludedBundleId(bundleId) }
        }
        webView.onRequestAvailableApps = { [weak self] in
            self?.meetingDetectionWebView?.sendAvailableApps()
        }
        webView.onRequestSearchApps = { [weak self] requestId, query in
            guard let self, let webView = self.meetingDetectionWebView else { return }
            webView.sendAppSearchResults(requestId: requestId, apps: MeetingDetectionSettingsPayloadBuilder.makeAppSearchResultsPayload(query: query))
        }
    }

    private func loadMeetingDetectionSettingsAndSendInit() async {
        meetingDetectionLoadGeneration += 1
        let generation = meetingDetectionLoadGeneration
        let vm = meetingDetectionViewModel
        vm.statusMessage = nil
        await vm.load()
        guard generation == meetingDetectionLoadGeneration else { return }
        guard let webView = meetingDetectionWebView else { return }
        if vm.statusMessage?.contains("Error") == true {
            webView.sendLoadError(message: vm.statusMessage ?? "Failed to load Meeting/Call Detection settings.")
            return
        }
        webView.sendInit(viewModel: vm)
    }

    private func performMeetingDetectionUpdate(
        requestId: String,
        apply: @escaping (MeetingDetectionSettingsViewModel) async -> Void
    ) {
        Task { @MainActor in
            guard let webView = meetingDetectionWebView else { return }
            let vm = meetingDetectionViewModel
            vm.statusMessage = nil
            await apply(vm)
            let failed = vm.statusMessage?.contains("Error") == true
            webView.sendSnapshot(viewModel: vm)
            webView.sendIntentResult(requestId: requestId, status: failed ? "error" : "success", message: vm.statusMessage)
        }
    }
}
