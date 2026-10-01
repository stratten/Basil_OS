import AppKit
@preconcurrency import WebKit

extension SettingsShellWindowController {
    func wireActivityCaptureSettingsWebView(_ webView: ReactActivityCaptureSettingsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadActivityCaptureSettingsAndSendInit() }
        }
        webView.onRequestUpdateEnabled = { [weak self] requestId, enabled in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.updateAutomaticCaptureEnabled(enabled) }
        }
        webView.onRequestUpdateFrequencySeconds = { [weak self] requestId, seconds in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.updateCaptureFrequencyInSeconds(seconds) }
        }
        webView.onRequestUpdateIdleThresholdSeconds = { [weak self] requestId, seconds in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.updateIdleThresholdSeconds(seconds) }
        }
        webView.onRequestUpdatePostWakeGraceSeconds = { [weak self] requestId, seconds in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.updatePostWakeGraceSeconds(seconds) }
        }
        webView.onRequestAddExcludedBundleId = { [weak self] requestId, bundleId in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.addExcludedBundleId(bundleId) }
        }
        webView.onRequestRemoveExcludedBundleId = { [weak self] requestId, bundleId in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.removeExcludedBundleId(bundleId) }
        }
        webView.onRequestAvailableApps = { [weak self] in
            guard let self, let webView = self.activityCaptureWebView else { return }
            webView.sendAvailableApps()
        }
        webView.onRequestSearchApps = { [weak self] requestId, query in
            guard let self, let webView = self.activityCaptureWebView else { return }
            webView.sendAppSearchResults(requestId: requestId, apps: ActivityCaptureSettingsPayloadBuilder.makeAppSearchResultsPayload(query: query))
        }
        webView.onRequestUpdateProcessingModel = { [weak self] requestId, modelId in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.updateProcessingModel(modelId) }
        }
        webView.onRequestUpdateProcessingMode = { [weak self] requestId, mode in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in
                await vm.updateProcessingMode(ActivityCaptureProcessingMode(rawValue: mode) ?? .realtime)
            }
        }
        webView.onRequestUpdateScheduledProcessingTime = { [weak self] requestId, time in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in
                await vm.updateScheduledProcessingTime(Self.dateFromTimeString(time))
            }
        }
        webView.onRequestUpdateProcessingMaxRecords = { [weak self] requestId, value in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.updateProcessingMaxRecords(value) }
        }
        webView.onRequestUpdateAutoCleanupEnabled = { [weak self] requestId, enabled in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.updateAutoCleanupEnabled(enabled) }
        }
        webView.onRequestUpdateRetentionDays = { [weak self] requestId, days in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.updateRetentionDays(days) }
        }
        webView.onRequestUpdateCleanupTime = { [weak self] requestId, hour, minute in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in
                await vm.updateCleanupTime(Self.dateFromHourMinute(hour: hour, minute: minute))
            }
        }
        webView.onRequestUpdateMaxStorageMb = { [weak self] requestId, mb in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.updateMaxStorageMb(mb) }
        }
        webView.onRequestTestCapture = { [weak self] requestId in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.performTestCapture() }
        }
        webView.onRequestProcessBacklog = { [weak self] requestId in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.processBacklog() }
        }
        webView.onRequestCancelProcessing = { [weak self] requestId in
            self?.performActivityCaptureUpdate(requestId: requestId) { vm in await vm.cancelProcessingBacklog() }
        }
        webView.onRequestClearBacklog = { [weak self] requestId in
            Task { @MainActor in await self?.presentClearActivityCaptureBacklogConfirmation(requestId: requestId) }
        }
        webView.onRequestClearAllCaptures = { [weak self] requestId in
            Task { @MainActor in await self?.presentClearAllCapturesConfirmation(requestId: requestId) }
        }
        webView.onRequestStatus = { [weak self] in
            guard let self, let webView = self.activityCaptureWebView else { return }
            webView.sendStatus(viewModel: self.activityCaptureViewModel)
        }
        webView.onRequestProcessingProgress = { [weak self] requestId in
            guard let self, let webView = self.activityCaptureWebView else { return }
            webView.sendProgress(viewModel: self.activityCaptureViewModel, requestId: requestId)
        }
    }

    private func loadActivityCaptureSettingsAndSendInit() async {
        activityCaptureLoadGeneration += 1
        let generation = activityCaptureLoadGeneration
        activityCaptureViewModel.onViewAppear()
        await activityCaptureViewModel.loadAllSettings()
        guard generation == activityCaptureLoadGeneration else { return }
        activityCaptureWebView?.sendInit(viewModel: activityCaptureViewModel)
    }

    private func performActivityCaptureUpdate(
        requestId: String,
        apply: @escaping (ActivityCaptureSettingsViewModel) async -> Void
    ) {
        Task { @MainActor in
            guard let webView = activityCaptureWebView else { return }
            let vm = activityCaptureViewModel
            vm.statusMessage = nil
            await apply(vm)
            let failed = vm.statusMessage?.contains("Error") == true
            webView.sendSnapshot(viewModel: vm)
            webView.sendStatus(viewModel: vm)
            webView.sendProgress(viewModel: vm, requestId: nil)
            webView.sendIntentResult(requestId: requestId, status: failed ? "error" : "success", message: vm.statusMessage)
        }
    }

    private func presentClearActivityCaptureBacklogConfirmation(requestId: String) async {
        guard let webView = activityCaptureWebView else { return }
        let alert = Self.makeClearActivityCaptureBacklogConfirmationAlert()
        guard alert.runModal() == .alertSecondButtonReturn else {
            webView.sendIntentResult(requestId: requestId, status: "canceled", message: nil)
            return
        }
        performActivityCaptureUpdate(requestId: requestId) { vm in await vm.clearBacklog() }
    }

    private func presentClearAllCapturesConfirmation(requestId: String) async {
        guard let webView = activityCaptureWebView else { return }
        let alert = Self.makeClearAllCapturesConfirmationAlert()
        guard alert.runModal() == .alertSecondButtonReturn else {
            webView.sendIntentResult(requestId: requestId, status: "canceled", message: nil)
            return
        }
        performActivityCaptureUpdate(requestId: requestId) { vm in await vm.clearAllCaptures() }
    }

    private static func dateFromTimeString(_ timeString: String) -> Date {
        let components = timeString.split(separator: ":")
        let calendar = Calendar.current
        let now = Date()
        guard components.count == 2, let hour = Int(components[0]), let minute = Int(components[1]) else {
            return now
        }
        return calendar.date(bySettingHour: hour, minute: minute, second: 0, of: now) ?? now
    }

    private static func dateFromHourMinute(hour: Int, minute: Int) -> Date {
        let calendar = Calendar.current
        return calendar.date(bySettingHour: hour, minute: minute, second: 0, of: Date()) ?? Date()
    }

    private static func makeClearActivityCaptureBacklogConfirmationAlert() -> NSAlert {
        let alert = NSAlert()
        alert.messageText = "Clear Backlog"
        alert.informativeText = "Are you sure you want to clear all pending and failed captures? This action cannot be undone."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Cancel")
        let clearButton = alert.addButton(withTitle: "Clear Backlog")
        clearButton.hasDestructiveAction = true
        return alert
    }

    private static func makeClearAllCapturesConfirmationAlert() -> NSAlert {
        let alert = NSAlert()
        alert.messageText = "Clear All Captures"
        alert.informativeText = "Are you sure you want to clear all captures? This deletes every stored capture file and cannot be undone."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Cancel")
        let clearButton = alert.addButton(withTitle: "Clear All Captures")
        clearButton.hasDestructiveAction = true
        return alert
    }
}
