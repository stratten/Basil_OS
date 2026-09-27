import Foundation

extension SettingsShellWindowController {
    func wireBrowserAutomationSettingsWebView(_ webView: ReactBrowserAutomationSettingsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadBrowserAutomationSettingsAndSendInit() }
        }
        webView.onRequestUpdateSensitiveFillPolicy = { [weak self] requestId, policy in
            self?.performBrowserAutomationUpdate(requestId: requestId, apply: { await $0.updateSensitiveFillPolicy(policy) }, isSuccessful: { $0.sensitiveFillPolicy == policy }, failureMessage: "Failed to update the sensitive fill policy.")
        }
        webView.onRequestUpdateForegroundControlPolicy = { [weak self] requestId, policy in
            self?.performBrowserAutomationUpdate(requestId: requestId, apply: { await $0.updateForegroundControlPolicy(policy) }, isSuccessful: { $0.foregroundControlPolicy == policy }, failureMessage: "Failed to update the foreground control policy.")
        }
        webView.onRequestUpdateDefaultSessionMode = { [weak self] requestId, sessionMode in
            self?.performBrowserAutomationUpdate(requestId: requestId, apply: { await $0.updateDefaultSessionMode(sessionMode) }, isSuccessful: { $0.defaultSessionMode == sessionMode }, failureMessage: "Failed to update the default browser session.")
        }
        webView.onRequestUpdatePreferredUserBrowser = { [weak self] requestId, browser in
            self?.performBrowserAutomationUpdate(requestId: requestId, apply: { await $0.updatePreferredUserBrowser(browser) }, isSuccessful: { $0.preferredUserBrowser == browser }, failureMessage: "Failed to update the preferred browser.")
        }
        webView.onRequestUpdateShowActionHighlights = { [weak self] requestId, enabled in
            self?.performBrowserAutomationUpdate(requestId: requestId, apply: { await $0.updateShowActionHighlights(enabled) }, isSuccessful: { $0.showActionHighlights == enabled }, failureMessage: "Failed to update action highlights.")
        }
        webView.onRequestUpdateRecordBrowserActionTrace = { [weak self] requestId, enabled in
            self?.performBrowserAutomationUpdate(requestId: requestId, apply: { await $0.updateRecordBrowserActionTrace(enabled) }, isSuccessful: { $0.recordBrowserActionTrace == enabled }, failureMessage: "Failed to update action trace recording.")
        }
        webView.onRequestUpdateAllowVisualFallback = { [weak self] requestId, enabled in
            self?.performBrowserAutomationUpdate(requestId: requestId, apply: { await $0.updateAllowVisualFallback(enabled) }, isSuccessful: { $0.allowVisualFallback == enabled }, failureMessage: "Failed to update visual fallback.")
        }
        webView.onRequestRemoveRememberedDomain = { [weak self] requestId, domain in
            self?.performBrowserAutomationAction(requestId: requestId, apply: { await $0.removeRememberedDomain(domain) }, failureMessage: "Failed to remove the domain.")
        }
        webView.onRequestClearAutomationBrowserProfile = { [weak self] requestId in
            self?.performBrowserAutomationAction(requestId: requestId, apply: { await $0.clearBasilAutomationBrowserProfile() }, failureMessage: "Failed to clear the automation browser profile.")
        }
    }

    private func loadBrowserAutomationSettingsAndSendInit() async {
        browserAutomationLoadGeneration += 1
        let generation = browserAutomationLoadGeneration
        await browserAutomationViewModel.loadSettings()
        guard generation == browserAutomationLoadGeneration else { return }
        guard browserAutomationViewModel.errorMessage == nil, browserAutomationViewModel.settings != nil else {
            browserAutomationWebView?.sendLoadError(message: browserAutomationViewModel.errorMessage ?? "Failed to load browser automation settings.")
            return
        }
        browserAutomationWebView?.sendInit(viewModel: browserAutomationViewModel)
    }

    private func performBrowserAutomationUpdate(
        requestId: String,
        apply: @escaping (BrowserAutomationSettingsViewModel) async -> Void,
        isSuccessful: @escaping (BrowserAutomationSettings) -> Bool,
        failureMessage: String
    ) {
        Task { @MainActor in
            let vm = browserAutomationViewModel
            vm.errorMessage = nil
            await apply(vm)
            // Judge success from the action's own result, captured before the
            // refresh reload below -- a reload that fails for unrelated reasons
            // (e.g. a transient network blip) must not overwrite a real success
            // with a false "error" toast.
            let actionError = vm.errorMessage
            let actionSucceeded = actionError == nil && vm.settings.map(isSuccessful) == true
            await vm.loadSettings()
            browserAutomationWebView?.sendSnapshot(viewModel: vm)
            if actionSucceeded {
                browserAutomationWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                browserAutomationWebView?.sendIntentResult(requestId: requestId, status: "error", message: actionError ?? failureMessage)
            }
        }
    }

    private func performBrowserAutomationAction(
        requestId: String,
        apply: @escaping (BrowserAutomationSettingsViewModel) async -> Void,
        failureMessage: String
    ) {
        Task { @MainActor in
            let vm = browserAutomationViewModel
            vm.errorMessage = nil
            await apply(vm)
            // Same reasoning as performBrowserAutomationUpdate: capture the
            // action's own error before the refresh reload can mask it.
            let actionError = vm.errorMessage
            await vm.loadSettings()
            browserAutomationWebView?.sendSnapshot(viewModel: vm)
            if actionError == nil {
                browserAutomationWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                browserAutomationWebView?.sendIntentResult(requestId: requestId, status: "error", message: actionError ?? failureMessage)
            }
        }
    }
}
