import Foundation
import Combine

extension SettingsShellWindowController {
    func wireModelsSettingsWebView(_ modelsWebView: ReactModelsSettingsWebView) {
        modelsWebView.onReady = { [weak self] in
            Task { @MainActor in
                await self?.loadModelsAndSendInit()
            }
        }
        modelsWebView.onRequestDownloadModel = { [weak self] requestId, modelId in
            self?.handleModelsDownloadRequest(requestId: requestId, modelId: modelId)
        }
        modelsWebView.onRequestCancelDownload = { [weak self] requestId, modelId in
            self?.handleModelsCancelRequest(requestId: requestId, modelId: modelId)
        }
        modelsWebView.onRequestDeleteModel = { [weak self] requestId, modelId in
            self?.handleModelsDeleteRequest(requestId: requestId, modelId: modelId)
        }
        modelsWebView.onRequestUpdateVisionFallback = { [weak self] requestId, enabled in
            self?.handleModelsVisionFallbackRequest(requestId: requestId, enabled: enabled)
        }
        modelsWebView.onRequestUpdateReasoningFallback = { [weak self] requestId, enabled, modelId in
            self?.handleModelsReasoningFallbackRequest(requestId: requestId, enabled: enabled, modelId: modelId)
        }
    }

    func tearDownModelsSettings() {
        modelsChangeCancellable?.cancel()
        modelsChangeCancellable = nil
        for (_, task) in modelsLogStreamTasks { task.cancel() }
        modelsLogStreamTasks.removeAll()
        modelsViewModel.cleanup()
    }

    private func loadModelsAndSendInit() async {
        modelsLoadGeneration += 1
        let generation = modelsLoadGeneration
        await modelsViewModel.loadModels()
        guard generation == modelsLoadGeneration else { return }
        guard modelsViewModel.loadError == nil else {
            modelsWebView?.sendLoadError(message: "Failed to load model settings.")
            return
        }
        subscribeToModelsViewModelIfNeeded()
        modelsWebView?.sendInit(viewModel: modelsViewModel)
    }

    private func subscribeToModelsViewModelIfNeeded() {
        guard modelsChangeCancellable == nil else { return }
        modelsChangeCancellable = modelsViewModel.objectWillChange
            .debounce(for: .milliseconds(200), scheduler: DispatchQueue.main)
            .sink { [weak self] _ in
                DispatchQueue.main.async {
                    self?.handleModelsViewModelChanged()
                }
            }
    }

    private func handleModelsViewModelChanged() {
        guard let modelsWebView else { return }
        reconcileModelsLogStreams()
        modelsWebView.sendSnapshot(viewModel: modelsViewModel)
    }

    private func reconcileModelsLogStreams() {
        let activeIds = modelsViewModel.activeDownloads
        let previouslyStreamed = Set(modelsLogStreamTasks.keys)

        for modelId in activeIds.subtracting(previouslyStreamed) {
            startModelsLogStream(modelId: modelId)
        }
        for modelId in previouslyStreamed.subtracting(activeIds) {
            modelsLogStreamTasks[modelId]?.cancel()
            modelsLogStreamTasks.removeValue(forKey: modelId)
        }
    }

    private func startModelsLogStream(modelId: String) {
        guard let model = currentModel(id: modelId) else { return }
        modelsLogStreamTasks[modelId] = Task { [weak self] in
            for await message in APIClient.shared.streamModelLogs(model.modelType, model.variantId) {
                if Task.isCancelled { break }
                guard let self, self.modelsViewModel.activeDownloads.contains(modelId) else { break }
                let cleanMessage = message.hasPrefix("data: ") ? String(message.dropFirst(6)) : message
                self.modelsWebView?.sendDownloadLogLine(modelId: modelId, message: cleanMessage)
            }
            _ = await MainActor.run { [weak self] in
                self?.modelsLogStreamTasks.removeValue(forKey: modelId)
            }
        }
    }

    private func currentModel(id: String) -> ModelDownloadInfo? {
        modelsViewModel.modelGroups.values.flatMap { $0 }.first(where: { $0.id == id })
    }

    private func handleModelsDownloadRequest(requestId: String, modelId: String) {
        guard let model = currentModel(id: modelId) else {
            modelsWebView?.sendIntentResult(requestId: requestId, status: "error", message: "This model is no longer available.")
            return
        }
        Task { @MainActor in
            await modelsViewModel.downloadModel(model)
            modelsWebView?.sendSnapshot(viewModel: modelsViewModel)
            if modelsViewModel.activeDownloads.contains(modelId) {
                modelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                let message: String
                if case .error(let errorMessage)? = currentModel(id: modelId)?.status {
                    message = errorMessage
                } else {
                    message = "Failed to start download."
                }
                modelsWebView?.sendIntentResult(requestId: requestId, status: "error", message: message)
            }
        }
    }

    private func handleModelsCancelRequest(requestId: String, modelId: String) {
        guard let model = currentModel(id: modelId) else {
            modelsWebView?.sendIntentResult(requestId: requestId, status: "error", message: "This model is no longer available.")
            return
        }
        Task { @MainActor in
            await modelsViewModel.cancelDownload(model)
            modelsWebView?.sendSnapshot(viewModel: modelsViewModel)
            modelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
        }
    }

    private func handleModelsDeleteRequest(requestId: String, modelId: String) {
        guard let model = currentModel(id: modelId) else {
            modelsWebView?.sendIntentResult(requestId: requestId, status: "error", message: "This model is no longer available.")
            return
        }
        guard let window else {
            modelsWebView?.sendIntentResult(requestId: requestId, status: "error", message: "Settings window is unavailable.")
            return
        }
        let alert = ModelsSettingsAlertFactory.makeDeleteModelConfirmationAlert(modelName: model.name, modelSize: model.size)
        alert.beginSheetModal(for: window) { [weak self] response in
            guard let self else { return }
            guard response == .alertFirstButtonReturn else {
                self.modelsWebView?.sendIntentResult(requestId: requestId, status: "canceled", message: nil)
                return
            }
            Task { @MainActor in
                await self.modelsViewModel.deleteModel(model)
                self.modelsWebView?.sendSnapshot(viewModel: self.modelsViewModel)
                if case .error(let errorMessage)? = self.currentModel(id: modelId)?.status {
                    self.modelsWebView?.sendIntentResult(requestId: requestId, status: "error", message: errorMessage)
                } else {
                    self.modelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
                }
            }
        }
    }

    private func handleModelsVisionFallbackRequest(requestId: String, enabled: Bool) {
        Task { @MainActor in
            await modelsViewModel.updateLocalVisionFallback(enabled: enabled)
            modelsWebView?.sendSnapshot(viewModel: modelsViewModel)
            modelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
        }
    }

    private func handleModelsReasoningFallbackRequest(requestId: String, enabled: Bool, modelId: String) {
        Task { @MainActor in
            await modelsViewModel.updateReasoningFallback(enabled: enabled, modelId: modelId)
            modelsWebView?.sendSnapshot(viewModel: modelsViewModel)
            modelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
        }
    }
}
