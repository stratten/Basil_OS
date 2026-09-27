import Foundation

extension SettingsShellWindowController {
    func wireTranscriptionApiModelsSettingsWebView(_ webView: ReactTranscriptionAPIModelsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in
                await self?.loadTranscriptionApiModelsAndSendInit()
            }
        }
        webView.onRequestToggleMaster = { [weak self] requestId, enabled in
            self?.handleTranscriptionApiModelsToggleMaster(requestId: requestId, enabled: enabled)
        }
        webView.onRequestToggleProvider = { [weak self] requestId, enabled in
            self?.handleTranscriptionApiModelsToggleProvider(requestId: requestId, enabled: enabled)
        }
        webView.onRequestToggleModel = { [weak self] requestId, modelId, enabled in
            self?.handleTranscriptionApiModelsToggleModel(requestId: requestId, modelId: modelId, enabled: enabled)
        }
        webView.onRequestSaveApiKey = { [weak self] requestId, key in
            self?.handleTranscriptionApiModelsSaveApiKey(requestId: requestId, key: key)
        }
    }

    private func loadTranscriptionApiModelsAndSendInit() async {
        transcriptionApiModelsLoadGeneration += 1
        let generation = transcriptionApiModelsLoadGeneration
        await transcriptionApiModelsViewModel.loadModels()
        guard generation == transcriptionApiModelsLoadGeneration else { return }
        guard transcriptionApiModelsViewModel.error == nil else {
            transcriptionApiModelsWebView?.sendLoadError(
                message: transcriptionApiModelsViewModel.error ?? "Failed to load transcription API models."
            )
            return
        }
        transcriptionApiModelsWebView?.sendInit(viewModel: transcriptionApiModelsViewModel)
    }

    private func handleTranscriptionApiModelsToggleMaster(requestId: String, enabled: Bool) {
        Task { @MainActor in
            let vm = transcriptionApiModelsViewModel
            await vm.toggleMaster(enabled: enabled)
            transcriptionApiModelsWebView?.sendSnapshot(viewModel: vm)
            if vm.useApiTranscriptionModels == enabled {
                transcriptionApiModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                transcriptionApiModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error",
                    message: vm.error ?? "Failed to update API transcription models."
                )
            }
        }
    }

    private func handleTranscriptionApiModelsToggleProvider(requestId: String, enabled: Bool) {
        Task { @MainActor in
            let vm = transcriptionApiModelsViewModel
            vm.openaiTranscriptionEnabled = enabled
            await vm.toggleProvider(provider: "openai", enabled: enabled)
            transcriptionApiModelsWebView?.sendSnapshot(viewModel: vm)
            if vm.openaiTranscriptionEnabled == enabled {
                transcriptionApiModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                transcriptionApiModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error",
                    message: vm.error ?? "Failed to update the OpenAI transcription provider."
                )
            }
        }
    }

    private func handleTranscriptionApiModelsToggleModel(requestId: String, modelId: String, enabled: Bool) {
        Task { @MainActor in
            let vm = transcriptionApiModelsViewModel
            await vm.toggleModel(provider: "openai", modelId: modelId, enabled: enabled)
            transcriptionApiModelsWebView?.sendSnapshot(viewModel: vm)
            let isNowEnabled = vm.models.contains(where: { $0.id == modelId })
            if isNowEnabled == enabled {
                transcriptionApiModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                transcriptionApiModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error", message: vm.error ?? "Failed to update the model."
                )
            }
        }
    }

    private func handleTranscriptionApiModelsSaveApiKey(requestId: String, key: String) {
        guard !key.isEmpty else {
            transcriptionApiModelsWebView?.sendIntentResult(
                requestId: requestId, status: "error", message: "API key cannot be empty."
            )
            return
        }
        Task { @MainActor in
            let vm = transcriptionApiModelsViewModel
            vm.apiKeys["openai"] = key
            await vm.saveApiKey(provider: "openai")
            vm.apiKeys["openai"] = ""
            transcriptionApiModelsWebView?.sendSnapshot(viewModel: vm)
            let result = vm.keyValidationResults["openai"]
            if result?.isValid == true {
                transcriptionApiModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: result?.message)
            } else {
                transcriptionApiModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error", message: result?.message ?? "Failed to save API key."
                )
            }
        }
    }
}
