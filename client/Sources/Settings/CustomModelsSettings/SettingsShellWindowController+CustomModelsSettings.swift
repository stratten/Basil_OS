import Foundation
import AppKit
import Combine

extension SettingsShellWindowController {
    func wireCustomModelsSettingsWebView(_ webView: ReactCustomModelsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in
                await self?.loadCustomModelsAndSendInit()
            }
        }
        webView.onRequestCreateModel = { [weak self] requestId, payload in
            self?.handleCustomModelsCreate(requestId: requestId, payload: payload)
        }
        webView.onRequestUpdateModel = { [weak self] requestId, modelId, payload in
            self?.handleCustomModelsUpdate(requestId: requestId, modelId: modelId, payload: payload)
        }
        webView.onRequestDeleteModel = { [weak self] requestId, modelId, deleteFiles, clearHFCache in
            self?.handleCustomModelsDelete(requestId: requestId, modelId: modelId, deleteFiles: deleteFiles, clearHFCache: clearHFCache)
        }
        webView.onRequestDownloadModel = { [weak self] requestId, modelId, filename in
            self?.handleCustomModelsDownload(requestId: requestId, modelId: modelId, filename: filename)
        }
        webView.onRequestTestConnection = { [weak self] requestId, payload in
            self?.handleCustomModelsTestConnection(requestId: requestId, payload: payload)
        }
        webView.onRequestProbeHFRepo = { [weak self] requestId, url in
            self?.handleCustomModelsProbeHFRepo(requestId: requestId, url: url)
        }
        webView.onRequestFetchGGUFMetadata = { [weak self] requestId, repoId, filename in
            self?.handleCustomModelsFetchGGUFMetadata(requestId: requestId, repoId: repoId, filename: filename)
        }
        webView.onRequestFetchLocalGGUFMetadata = { [weak self] requestId, filePath in
            self?.handleCustomModelsFetchLocalGGUFMetadata(requestId: requestId, filePath: filePath)
        }
        webView.onRequestPickLocalFile = { [weak self] requestId in
            self?.handleCustomModelsPickLocalFile(requestId: requestId)
        }
        subscribeToCustomModelsDownloadProgress()
    }

    private func loadCustomModelsAndSendInit() async {
        customModelsLoadGeneration += 1
        let generation = customModelsLoadGeneration
        await customModelsViewModel.loadModels()
        guard generation == customModelsLoadGeneration else { return }
        guard customModelsViewModel.lastError == nil else {
            customModelsWebView?.sendLoadError(message: customModelsViewModel.lastError ?? "Failed to load custom models.")
            return
        }
        customModelsWebView?.sendInit(viewModel: customModelsViewModel)
    }

    private func handleCustomModelsCreate(requestId: String, payload: [String: Any]) {
        guard
            let modelId = payload["modelId"] as? String, !modelId.isEmpty,
            let displayName = payload["displayName"] as? String,
            let handler = payload["handler"] as? String,
            let contextWindow = (payload["contextWindow"] as? NSNumber)?.intValue,
            let maxOutputTokens = (payload["maxOutputTokens"] as? NSNumber)?.intValue,
            let requiresAuth = payload["requiresAuth"] as? Bool,
            let features = payload["features"] as? [String]
        else {
            customModelsWebView?.sendIntentResult(requestId: requestId, status: "error", message: "Malformed create-model request.")
            return
        }
        let baseUrl = payload["baseUrl"] as? String
        let modelIdentifier = payload["modelIdentifier"] as? String
        let modelPath = payload["modelPath"] as? String
        let downloadUrl = payload["downloadUrl"] as? String
        let apiKey = payload["apiKey"] as? String
        let toolRendering = payload["toolRendering"] as? String
        let toolCallFormat = payload["toolCallFormat"] as? String
        let serverType = payload["serverType"] as? String
        let description = payload["description"] as? String
        let fileSize = (payload["fileSize"] as? NSNumber)?.intValue
        let fileSizeHuman = payload["fileSizeHuman"] as? String

        Task { @MainActor in
            let vm = customModelsViewModel
            vm.lastError = nil
            let success = await vm.createModel(
                modelId: modelId, displayName: displayName, handler: handler, baseUrl: baseUrl,
                modelIdentifier: modelIdentifier, modelPath: modelPath, downloadUrl: downloadUrl,
                contextWindow: contextWindow, maxOutputTokens: maxOutputTokens, requiresAuth: requiresAuth,
                apiKey: apiKey, features: features, toolRendering: toolRendering, toolCallFormat: toolCallFormat,
                serverType: serverType, description: description, fileSize: fileSize, fileSizeHuman: fileSizeHuman
            )
            // Judge success from the create call's own result, captured before
            // the refresh reload below -- a reload failure must not overwrite a
            // real success with a false "error" toast.
            let actionError = vm.lastError
            await vm.loadModels()
            customModelsWebView?.sendSnapshot(viewModel: vm)
            if success && actionError == nil {
                customModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                customModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error", message: actionError ?? "Failed to create the model."
                )
            }
        }
    }

    private func handleCustomModelsUpdate(requestId: String, modelId: String, payload: [String: Any]) {
        guard
            let displayName = payload["displayName"] as? String,
            let contextWindow = (payload["contextWindow"] as? NSNumber)?.intValue,
            let maxOutputTokens = (payload["maxOutputTokens"] as? NSNumber)?.intValue,
            let requiresAuth = payload["requiresAuth"] as? Bool,
            let features = payload["features"] as? [String]
        else {
            customModelsWebView?.sendIntentResult(requestId: requestId, status: "error", message: "Malformed update-model request.")
            return
        }
        let handler = payload["handler"] as? String
        let baseUrl = payload["baseUrl"] as? String
        let modelIdentifier = payload["modelIdentifier"] as? String
        let modelPath = payload["modelPath"] as? String
        let downloadUrl = payload["downloadUrl"] as? String
        let apiKey = payload["apiKey"] as? String
        let toolRendering = payload["toolRendering"] as? String
        let toolCallFormat = payload["toolCallFormat"] as? String
        let serverType = payload["serverType"] as? String
        let description = payload["description"] as? String

        Task { @MainActor in
            let vm = customModelsViewModel
            vm.lastError = nil
            let success = await vm.updateModel(
                modelId: modelId, displayName: displayName, handler: handler, baseUrl: baseUrl, modelIdentifier: modelIdentifier,
                modelPath: modelPath, downloadUrl: downloadUrl, contextWindow: contextWindow,
                maxOutputTokens: maxOutputTokens, requiresAuth: requiresAuth, apiKey: apiKey, features: features,
                toolRendering: toolRendering, toolCallFormat: toolCallFormat, serverType: serverType,
                description: description
            )
            // Judge success from the update call's own result, captured before
            // the refresh reload below -- a reload failure must not overwrite a
            // real success with a false "error" toast.
            let actionError = vm.lastError
            await vm.loadModels()
            customModelsWebView?.sendSnapshot(viewModel: vm)
            if success && actionError == nil {
                customModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                customModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error", message: actionError ?? "Failed to update the model."
                )
            }
        }
    }

    private func handleCustomModelsDelete(requestId: String, modelId: String, deleteFiles: Bool, clearHFCache: Bool) {
        Task { @MainActor in
            let vm = customModelsViewModel
            vm.lastError = nil
            await vm.deleteModel(modelId, deleteFiles: deleteFiles, clearHFCache: clearHFCache)
            // Judge success from the delete call's own result, captured before
            // the refresh reload below -- a reload failure must not overwrite a
            // real success with a false "error" toast. `stillPresent` still
            // needs the post-reload list, since deletion is only confirmed by
            // the model's absence from the freshly reloaded canonical list.
            let actionError = vm.lastError
            await vm.loadModels()
            customModelsWebView?.sendSnapshot(viewModel: vm)
            let stillPresent = vm.customModels.contains { $0.modelId == modelId }
            if !stillPresent && actionError == nil {
                customModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                customModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error", message: actionError ?? "Failed to delete the model."
                )
            }
        }
    }

    private func handleCustomModelsDownload(requestId: String, modelId: String, filename: String) {
        Task { @MainActor in
            let vm = customModelsViewModel
            vm.lastError = nil
            let success = await vm.downloadModel(modelId: modelId, filename: filename)
            let actionError = vm.lastError
            await vm.loadModels()
            customModelsWebView?.sendSnapshot(viewModel: vm)
            if success {
                customModelsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                customModelsWebView?.sendIntentResult(
                    requestId: requestId, status: "error", message: actionError ?? vm.lastError ?? "Download failed."
                )
            }
        }
    }

    private func handleCustomModelsTestConnection(requestId: String, payload: [String: Any]) {
        guard
            let handler = payload["handler"] as? String,
            let baseUrl = payload["baseUrl"] as? String,
            let modelIdentifier = payload["modelIdentifier"] as? String
        else {
            customModelsWebView?.sendConnectionTestResult(requestId: requestId, success: false, message: "Malformed connection-test request.")
            return
        }
        let apiKey = payload["apiKey"] as? String
        Task { @MainActor in
            let result = await customModelsViewModel.testConnectionDirect(
                handler: handler, baseUrl: baseUrl, modelIdentifier: modelIdentifier, apiKey: apiKey
            )
            customModelsWebView?.sendConnectionTestResult(requestId: requestId, success: result.success, message: result.message)
        }
    }

    private func handleCustomModelsProbeHFRepo(requestId: String, url: String) {
        Task { @MainActor in
            do {
                let result = try await customModelsViewModel.probeHFRepo(url: url)
                customModelsWebView?.sendHFProbeResult(requestId: requestId, response: result)
            } catch {
                let errorResponse = HFProbeResponse(
                    repoId: "", ggufFiles: [], safetensorFiles: [], modelMetadata: nil, error: error.localizedDescription
                )
                customModelsWebView?.sendHFProbeResult(requestId: requestId, response: errorResponse)
            }
        }
    }

    private func handleCustomModelsFetchGGUFMetadata(requestId: String, repoId: String, filename: String) {
        Task { @MainActor in
            let response = await customModelsViewModel.fetchGGUFMetadata(repoId: repoId, filename: filename)
            customModelsWebView?.sendGGUFMetadataResult(requestId: requestId, response: response)
        }
    }

    private func handleCustomModelsFetchLocalGGUFMetadata(requestId: String, filePath: String) {
        Task { @MainActor in
            let response = await customModelsViewModel.fetchLocalGGUFMetadata(filePath: filePath)
            customModelsWebView?.sendGGUFMetadataResult(requestId: requestId, response: response)
        }
    }

    private func handleCustomModelsPickLocalFile(requestId: String) {
        guard let window else {
            customModelsWebView?.sendLocalFilePickError(requestId: requestId, message: "Settings window is not available.")
            return
        }
        let panel = NSOpenPanel()
        panel.applyBasilThemedAppearance()
        panel.title = "Select Model File"
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.allowedContentTypes = [.init(filenameExtension: "gguf")!]
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self else { return }
            guard response == .OK, let url = panel.url else { return }
            let fileManager = FileManager.default
            guard fileManager.fileExists(atPath: url.path) else {
                self.customModelsWebView?.sendLocalFilePickError(requestId: requestId, message: "Selected file does not exist.")
                return
            }
            guard fileManager.isReadableFile(atPath: url.path) else {
                self.customModelsWebView?.sendLocalFilePickError(requestId: requestId, message: "Selected file is not readable. Check file permissions.")
                return
            }
            guard url.pathExtension.lowercased() == "gguf" else {
                self.customModelsWebView?.sendLocalFilePickError(requestId: requestId, message: "Selected file is not a GGUF file.")
                return
            }
            self.customModelsWebView?.sendLocalFilePicked(requestId: requestId, path: url.path)
        }
    }

    private func subscribeToCustomModelsDownloadProgress() {
        customModelsDownloadCancellable = customModelsViewModel.objectWillChange
            .receive(on: DispatchQueue.main)
            .debounce(for: .milliseconds(16), scheduler: DispatchQueue.main)
            .sink { [weak self] _ in
                DispatchQueue.main.async {
                    self?.emitCustomModelsDownloadProgress()
                }
            }
    }

    private func emitCustomModelsDownloadProgress() {
        let update = CustomModelsPayloadBuilder.changedDownloadProgress(
            previous: customModelsDownloadProgressSnapshot,
            downloadProgressMap: customModelsViewModel.downloadProgressMap,
            downloadStatus: customModelsViewModel.downloadStatus
        )
        customModelsDownloadProgressSnapshot = update.snapshot
        for (modelId, progress) in update.changes {
            customModelsWebView?.sendDownloadProgress(
                modelId: modelId,
                progress: progress.progress,
                status: progress.status
            )
        }
    }
}
