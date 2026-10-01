import Foundation

extension ModelDownloadViewModel {
    // A more efficient model progress updater that minimizes UI updates
    func updateModelProgressEfficient(_ modelId: String, progress: Double) {
        DevLogger.shared.info("[TRACE] Enter updateModelProgressEfficient", context: "MainThreadTrace")
        
        // Ensure we're on the main thread
        assert(Thread.isMainThread, "updateModelProgressEfficient must be called on main thread")
        
        #if DEBUG
        DevLogger.shared.info("Efficient model progress update: \(modelId) = \(Int(progress * 100))%", context: "ModelManagement")
        #endif
        
        // Find the model directly with minimal logging
        var updated = false
        
        // Get the components only once
        let components = modelId.split(separator: "-")
        let modelType = components.count >= 1 ? String(components[0]) : ""
        let variant = components.count >= 2 ? String(components[1]) : ""
        
        // Skip heavy diagnostics in production/normal operation
        #if DEBUG
        DevLogger.shared.info("Looking for model: \(modelId) (type: \(modelType), variant: \(variant))", context: "ModelDiagnostic")
        #endif
        
        // First check for an exact match in the correct group
        if var models = modelGroups[modelType] {
            if let index = models.firstIndex(where: { $0.id == modelId || $0.variantId == variant }) {
                let model = models[index]
                
                #if DEBUG
                DevLogger.shared.info("Found model \(model.id) in correct group \(modelType)", context: "ModelManagement")
                #endif
                
                // Only update if in downloading state
                if case .downloading = model.status {
                    var updatedModel = model
                    updatedModel.status = .downloading(progress: progress)
                    models[index] = updatedModel
                    modelGroups[modelType] = models
                    updated = true
                    
                    #if DEBUG
                    DevLogger.shared.info("Updated model status to \(Int(progress * 100))%", context: "ModelManagement")
                    #endif
                }
            }
        }
        
        // If not found or not updated with exact match, then do a more thorough search
        if !updated {
            // Try a more flexible match only if exact match failed
            forLoop: for group in modelGroups.keys {
                guard var models = modelGroups[group] else { continue }
                
                for (index, model) in models.enumerated() {
                    // Check for ID match
                    if model.id == modelId {
                        if case .downloading = model.status {
                            var updatedModel = model
                            updatedModel.status = .downloading(progress: progress)
                            models[index] = updatedModel
                            modelGroups[group] = models
                            updated = true
                            break forLoop
                        }
                    }
                    // Check for variant match
                    else if model.modelType == modelType && 
                            (model.variantId == variant || 
                             model.variantId.replacingOccurrences(of: ".", with: "_") == variant.replacingOccurrences(of: ".", with: "_")) {
                        if case .downloading = model.status {
                            var updatedModel = model
                            updatedModel.status = .downloading(progress: progress)
                            models[index] = updatedModel
                            modelGroups[group] = models
                            updated = true
                            break forLoop
                        }
                    }
                }
            }
        }
        
        // Only send objectWillChange if an actual update happened
        if updated {
            // Trigger UI refresh exactly once
            objectWillChange.send()
            
            #if DEBUG
            DevLogger.shared.info("Sent objectWillChange for progress update", context: "ModelManagement")
            #endif
        } else {
            #if DEBUG
            DevLogger.shared.warning("No models found to update for \(modelId)", context: "ModelManagement")
            #endif
        }
        DevLogger.shared.info("[TRACE] Exit updateModelProgressEfficient", context: "MainThreadTrace")
    }
    
    @MainActor
    func handleProgressUpdateUI(modelId: String, progress: Double, model: ModelDownloadInfo) async {
        // If the task was canceled, stop processing further progress updates.
        // This check is important here as this func is async and might run after cancellation.
        if Task.isCancelled {
            Self.logger.info("handleProgressUpdateUI: Task for \(modelId) canceled. Stopping UI updates.")
            return
        }

        // Check if this is completion FIRST, before setting any progress
        if progress >= 1.0 {
            Self.logger.info("handleProgressUpdateUI: Download for \(modelId) reached 100%. Clearing progress UI IMMEDIATELY.")

            // FIRST: Clear local progress indicators immediately so progress bar disappears
            self.downloadProgress.removeValue(forKey: modelId)
            self.downloadProgressMetadata.removeValue(forKey: modelId)
            self.activeDownloads.remove(modelId)
            self.objectWillChange.send() // Force immediate UI update to remove progress bar
            
            Self.logger.info("handleProgressUpdateUI: Progress UI cleared. Now refreshing models list...")
            
            // THEN: Refresh models from backend (this can be slow)
            await self.loadModels()
            
            Self.logger.info("handleProgressUpdateUI: Models list refreshed.")
        } else {
            // For non-completion progress, update normally
            self.downloadProgress[modelId] = progress
            self.updateModelProgressEfficient(modelId, progress: progress)
        }
    }

    @MainActor
    func handlePostLoopCleanupUI(modelId: String) async {
        Self.logger.info("Streaming for \(modelId) finished (loop ended, not 100%, not canceled). Progress: \(self.downloadProgress[modelId] ?? -1). Refreshing models and cleaning up.")
        await self.loadModels() // Refresh to get final status
        self.downloadProgress.removeValue(forKey: modelId)
        self.downloadProgressMetadata.removeValue(forKey: modelId)
        self.activeDownloads.remove(modelId)
        self.objectWillChange.send()
        Self.logger.info("Cleaned up \(modelId) after stream ended (not 100%, not canceled case).")
    }

    /// Rehydrate any in-flight backend downloads after the Models tab is
    /// revisited. The backend DownloadManager is the source of truth; local
    /// polling tasks are intentionally disposable UI observers.
    func restoreActiveDownloadsFromBackend() async {
        let candidates = modelGroups.values.flatMap { $0 }.filter { model in
            if case .available = model.status {
                return false
            }
            return true
        }

        for model in candidates {
            do {
                let dict = try await api.fetchModelDownloadProgressMetadata(
                    modelType: model.modelType,
                    variant: model.variantId
                )
                let status = (dict["status"] as? String) ?? "not_found"
                guard activeBackendDownloadStatuses.contains(status) else {
                    continue
                }

                let progress = (dict["progress"] as? Double) ?? 0.0
                let metadata = progressMetadata(from: dict, status: status)
                downloadProgress[model.id] = progress
                downloadProgressMetadata[model.id] = metadata
                activeDownloads.insert(model.id)

                if let updatedModel = markModelAsDownloading(modelId: model.id, progress: progress),
                   progressTimers[model.id] == nil {
                    startPollingProgress(for: updatedModel)
                }

                Self.logger.info("🔁 Restored active backend download for \(model.id) at \(Int(progress * 100))%")
            } catch {
                Self.logger.debug("No active backend download restored for \(model.id): \(String(describing: error))")
            }
        }
    }

    func progressMetadata(from dict: [String: Any], status: String) -> [String: Any] {
        var metadata: [String: Any] = [:]
        if let td = dict["total_downloaded"] { metadata["total_downloaded"] = td }
        if let ts = dict["total_size"] { metadata["total_size"] = ts }
        metadata["status"] = status
        if let msg = dict["message"] { metadata["message"] = msg }
        if let cf = dict["current_file"] { metadata["current_file"] = cf }
        if let cfp = dict["current_file_percent"] { metadata["current_file_percent"] = cfp }
        if let fc = dict["files_completed"] { metadata["files_completed"] = fc }
        if let tf = dict["total_files"] { metadata["total_files"] = tf }
        return metadata
    }

    func markModelAsDownloading(modelId: String, progress: Double) -> ModelDownloadInfo? {
        for group in modelGroups.keys {
            guard var models = modelGroups[group],
                  let index = models.firstIndex(where: { $0.id == modelId }) else {
                continue
            }

            var updatedModel = models[index]
            updatedModel.status = .downloading(progress: progress)
            models[index] = updatedModel
            modelGroups[group] = models
            return updatedModel
        }

        return nil
    }
    
    /// Poll the backend for download progress via HTTP (same pattern as the
    /// onboarding download view, which works reliably in packaged builds).
    func startPollingProgress(for model: ModelDownloadInfo) {
        #if DEBUG
        DevLogger.shared.info("Starting HTTP progress polling for \(model.id)", context: "ModelManagement")
        #endif
        Self.logger.info("📊 POLL_START for \(model.id)")
        downloadProgress[model.id] = 0.0

        if let existing = progressTimers[model.id] {
            existing.cancel()
            progressTimers.removeValue(forKey: model.id)
        }

        let pollingTask = Task { [weak self] in
            guard let self = self else { return }
            let modelId = model.id
            let modelType = model.modelType
            let variant = model.variantId

            while !Task.isCancelled {
                do {
                    let dict = try await self.api.fetchModelDownloadProgressMetadata(
                        modelType: modelType, variant: variant
                    )

                    let progress = (dict["progress"] as? Double) ?? 0.0
                    let status = (dict["status"] as? String) ?? "downloading"

                    // Populate metadata for the UI (byte counts, file info, etc.)
                    let metadata = self.progressMetadata(from: dict, status: status)

                    await MainActor.run {
                        self.downloadProgressMetadata[modelId] = metadata
                    }

                    // Terminal states — stop polling
                    if status == "not_found" || status == "error" || status == "user_canceled" {
                        Self.logger.info("📊 POLL terminal status '\(status)' for \(modelId). Stopping.")
                        await self.handlePostLoopCleanupUI(modelId: modelId)
                        break
                    }

                    await self.handleProgressUpdateUI(modelId: modelId, progress: progress, model: model)

                    if progress >= 1.0 || status == "completed" {
                        Self.logger.info("📊 POLL completed for \(modelId)")
                        break
                    }
                } catch {
                    Self.logger.error("📊 POLL error for \(modelId): \(String(describing: error))")
                }

                try? await Task.sleep(nanoseconds: 1_000_000_000) // 1 second
            }

            _ = await MainActor.run {
                self.progressTimers.removeValue(forKey: modelId)
            }
        }
        progressTimers[model.id] = pollingTask
    }

    // Cleanup method for view disappearance
    func cleanup() {
        // Cancel all progress streaming tasks
        for (modelId, task) in progressTimers {
            task.cancel()
            Self.logger.debug("🧹 Cleaning up progress streaming for \(modelId)")
            
            // Find the model to reset its progress cache
            for group in modelGroups.keys {
                if let models = modelGroups[group],
                   let model = models.first(where: { $0.id == modelId }) {
                    // Reset the progress cache for this model during cleanup
                    api.resetProgressCache(modelType: model.modelType, variant: model.variantId)
                    break
                }
            }
        }
        progressTimers.removeAll()
        activeDownloads.removeAll()
        // Clear any potentially lingering simple progress too
        downloadProgress.removeAll()
        downloadProgressMetadata.removeAll()
        Self.logger.info("ViewModel cleanup complete.")
    }
}

