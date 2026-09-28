import Foundation

extension SettingsShellWindowController {
    func wireReasoningApiModelsSettingsWebView(_ webView: ReactReasoningAPIModelsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in
                await self?.loadReasoningApiModelsAndSendInit()
            }
        }
        webView.onRequestToggleMaster = { [weak self] requestId, enabled in
            self?.handleReasoningApiModelsToggleMaster(requestId: requestId, enabled: enabled)
        }
        webView.onRequestToggleProvider = { [weak self] requestId, providerId, enabled in
            self?.handleReasoningApiModelsToggleProvider(requestId: requestId, providerId: providerId, enabled: enabled)
        }
        webView.onRequestToggleProviderKeySource = { [weak self] requestId, providerId, useOwnKey in
            self?.handleReasoningApiModelsToggleKeySource(requestId: requestId, providerId: providerId, useOwnKey: useOwnKey)
        }
        webView.onRequestToggleModel = { [weak self] requestId, providerId, modelId, enabled in
            self?.handleReasoningApiModelsToggleModel(requestId: requestId, providerId: providerId, modelId: modelId, enabled: enabled)
        }
        webView.onRequestSaveApiKey = { [weak self] requestId, providerId, key in
            self?.handleReasoningApiModelsSaveApiKey(requestId: requestId, providerId: providerId, key: key)
        }
        webView.onRequestRemoveApiKey = { [weak self] requestId, providerId in
            self?.handleReasoningApiModelsRemoveApiKey(requestId: requestId, providerId: providerId)
        }
    }

    private func loadReasoningApiModelsAndSendInit() async {
        reasoningApiModelsLoadGeneration += 1
        let generation = reasoningApiModelsLoadGeneration
        await reasoningApiModelsViewModel.loadApiModels()
        guard generation == reasoningApiModelsLoadGeneration else { return }
        guard reasoningApiModelsViewModel.error == nil else {
            reasoningApiModelsWebView?.sendLoadError(
                message: reasoningApiModelsViewModel.error ?? "Failed to load reasoning API models."
            )
            return
        }
        reasoningApiModelsWebView?.sendInit(viewModel: reasoningApiModelsViewModel)
    }

    private func handleReasoningApiModelsToggleMaster(requestId: String, enabled: Bool) {
        Task { @MainActor in
            let vm = reasoningApiModelsViewModel
            vm.error = nil
            vm.apiSettings.useApiModels = enabled
            await vm.updateApiModelsMasterToggle(enabled: enabled)
            // Judge success from the toggle call's own error, captured before
            // the refresh reload below -- a reload failure must not overwrite a
            // real success with a false "error" toast.
            let actionError = vm.error
            await vm.loadApiModels()
            reasoningApiModelsWebView?.sendSnapshot(viewModel: vm)
            if actionError == nil && vm.apiSettings.useApiModels == enabled {
                reasoningApiModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                reasoningApiModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error",
                    message: actionError ?? vm.error ?? "Failed to update API models."
                )
            }
        }
    }

    private func handleReasoningApiModelsToggleProvider(requestId: String, providerId: String, enabled: Bool) {
        Task { @MainActor in
            let vm = reasoningApiModelsViewModel
            vm.error = nil
            if let index = vm.apiProviders.firstIndex(where: { $0.id == providerId }) {
                vm.apiProviders[index].isEnabled = enabled
            }
            await vm.updateProviderEnabled(provider: providerId, enabled: enabled)
            // Judge success from the toggle call's own error, captured before
            // the refresh reload below -- a reload failure must not overwrite a
            // real success with a false "error" toast.
            let actionError = vm.error
            await vm.loadApiModels()
            reasoningApiModelsWebView?.sendSnapshot(viewModel: vm)
            let isNowEnabled = vm.apiProviders.first(where: { $0.id == providerId })?.isEnabled == enabled
            if actionError == nil && isNowEnabled {
                reasoningApiModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                reasoningApiModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error",
                    message: actionError ?? vm.error ?? "Failed to update the provider."
                )
            }
        }
    }

    private func handleReasoningApiModelsToggleKeySource(requestId: String, providerId: String, useOwnKey: Bool) {
        guard useOwnKey == false else {
            reasoningApiModelsWebView?.sendIntentResult(
                requestId: requestId, status: "error",
                message: "Key source can only be enabled by saving an API key."
            )
            return
        }
        Task { @MainActor in
            let vm = reasoningApiModelsViewModel
            vm.error = nil
            if let index = vm.apiProviders.firstIndex(where: { $0.id == providerId }) {
                vm.apiProviders[index].localUsingOwnApiKey = false
            }
            await vm.updateProviderApiKeySource(provider: providerId, useOwnKey: false)
            // Judge success from the toggle call's own error, captured before
            // the refresh reload below -- a reload failure must not overwrite a
            // real success with a false "error" toast.
            let actionError = vm.error
            await vm.loadApiModels()
            reasoningApiModelsWebView?.sendSnapshot(viewModel: vm)
            let isOff = vm.apiProviders.first(where: { $0.id == providerId })?.localUsingOwnApiKey == false
            if actionError == nil && isOff {
                reasoningApiModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                reasoningApiModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error",
                    message: actionError ?? vm.error ?? "Failed to update the API key source."
                )
            }
        }
    }

    private func handleReasoningApiModelsToggleModel(requestId: String, providerId: String, modelId: String, enabled: Bool) {
        Task { @MainActor in
            let vm = reasoningApiModelsViewModel
            vm.error = nil
            if let providerIndex = vm.apiProviders.firstIndex(where: { $0.id == providerId }),
               let modelIndex = vm.apiProviders[providerIndex].models.firstIndex(where: { $0.id == modelId }) {
                vm.apiProviders[providerIndex].models[modelIndex].isEnabled = enabled
            }
            await vm.updateModelEnabled(provider: providerId, modelId: modelId, enabled: enabled)
            // Judge success from the toggle call's own error, captured before
            // the refresh reload below -- a reload failure must not overwrite a
            // real success with a false "error" toast.
            let actionError = vm.error
            await vm.loadApiModels()
            reasoningApiModelsWebView?.sendSnapshot(viewModel: vm)
            let isNowEnabled = vm.apiProviders
                .first(where: { $0.id == providerId })?
                .models.first(where: { $0.id == modelId })?
                .isEnabled == enabled
            if actionError == nil && isNowEnabled {
                reasoningApiModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                reasoningApiModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error", message: actionError ?? vm.error ?? "Failed to update the model."
                )
            }
        }
    }

    private func handleReasoningApiModelsSaveApiKey(requestId: String, providerId: String, key: String) {
        guard !key.isEmpty else {
            reasoningApiModelsWebView?.sendIntentResult(
                requestId: requestId, status: "error", message: "API key cannot be empty."
            )
            return
        }
        Task { @MainActor in
            let vm = reasoningApiModelsViewModel
            vm.error = nil
            guard var providerInfo = vm.apiProviders.first(where: { $0.id == providerId }) else {
                reasoningApiModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error", message: "Unknown provider."
                )
                return
            }
            providerInfo.localUsingOwnApiKey = true
            if let index = vm.apiProviders.firstIndex(where: { $0.id == providerId }) {
                vm.apiProviders[index].localUsingOwnApiKey = true
            }
            let result = await APIModelManager.shared.saveApiKey(provider: providerId, key: key, providerInfo: providerInfo)
            // Judge success from the save call's own error, captured before the
            // refresh reload below -- a reload failure must not overwrite a real
            // success with a false "error" toast.
            let actionError = vm.error
            await vm.loadApiModels()
            reasoningApiModelsWebView?.sendSnapshot(viewModel: vm)
            if result.isValid && result.error == nil && actionError == nil {
                reasoningApiModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: result.message)
            } else {
                reasoningApiModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error",
                    message: result.error ?? actionError ?? result.message ?? "Failed to save API key."
                )
            }
        }
    }

    private func handleReasoningApiModelsRemoveApiKey(requestId: String, providerId: String) {
        Task { @MainActor in
            let vm = reasoningApiModelsViewModel
            vm.error = nil
            // The Gemini provider accepts a key saved under either credential name.
            let credentialNames = providerId == "gemini" ? ["google", "gemini"] : [providerId]
            var removeError: String?
            for credentialName in credentialNames {
                do {
                    try await APIClient.shared.deleteApiKey(provider: credentialName)
                } catch {
                    removeError = error.localizedDescription
                }
            }
            if removeError == nil, let index = vm.apiProviders.firstIndex(where: { $0.id == providerId }) {
                vm.apiProviders[index].localUsingOwnApiKey = false
            }
            await vm.loadApiModels()
            reasoningApiModelsWebView?.sendSnapshot(viewModel: vm)
            let stillHasKey = vm.apiProviders.first(where: { $0.id == providerId })?.hasKey == true
            if removeError == nil && !stillHasKey {
                reasoningApiModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                reasoningApiModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error",
                    message: removeError ?? "The API key could not be removed."
                )
            }
        }
    }
}
