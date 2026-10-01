import Foundation

extension ModelDownloadViewModel {
    // Download model and poll HTTP endpoint for progress updates
    func downloadModel(_ model: ModelDownloadInfo) async {
        debugPrint("🚨 STARTING DOWNLOAD for model: \(model.id)")
        debugPrint("🚨 Model details: modelType='\(model.modelType)', variantId='\(model.variantId)', name='\(model.name)'")
        
        #if DEBUG
        DevLogger.shared.info("🚨 STARTING DOWNLOAD for model: \(model.id)", context: "ModelManagement")
        DevLogger.shared.info("🚨 Model details: modelType='\(model.modelType)', variantId='\(model.variantId)', name='\(model.name)'", context: "ModelManagement")
        #endif
        
        // Check backend availability first
        debugPrint("🚨 CHECKING BACKEND AVAILABILITY")
        #if DEBUG
        DevLogger.shared.info("🚨 CHECKING BACKEND AVAILABILITY", context: "ModelManagement")
        #endif
        
        if !api.isBackendAvailable {
            debugPrint("🚨 BACKEND NOT AVAILABLE - cannot start download")
            #if DEBUG
            DevLogger.shared.error("🚨 BACKEND NOT AVAILABLE - cannot start download", context: "ModelManagement")
            #endif
            for group in modelGroups.keys {
                if var models = modelGroups[group], let index = models.firstIndex(where: { $0.id == model.id }) {
                    var updatedModel = models[index]
                    updatedModel.status = .error(message: "Backend not available")
                    models[index] = updatedModel
                    modelGroups[group] = models
                }
            }
            return
        }
        debugPrint("🚨 BACKEND IS AVAILABLE - proceeding with download")
        #if DEBUG
        DevLogger.shared.info("🚨 BACKEND IS AVAILABLE - proceeding with download", context: "ModelManagement")
        #endif
        
        if !activeDownloads.contains(model.id) {
            activeDownloads.insert(model.id)
        }
        
        Task {
            do {
                debugPrint("🚨 MAKING API POST REQUEST to /models/download")
                debugPrint("🚨 API request payload: model_type='\(model.modelType)', variant='\(model.variantId)'")
                
                #if DEBUG
                DevLogger.shared.info("🚨 MAKING API POST REQUEST to /models/download", context: "ModelManagement")
                DevLogger.shared.info("🚨 API request payload: model_type='\(model.modelType)', variant='\(model.variantId)'", context: "ModelManagement")
                #endif
                
                let response = try await api.post("/models/download", [
                    "request": [
                        "model_type": model.modelType,
                        "variant": model.variantId
                    ]
                ])
                
                debugPrint("🚨 API RESPONSE RECEIVED successfully for \(model.id)")
                #if DEBUG
                DevLogger.shared.info("🚨 API RESPONSE RECEIVED successfully for \(model.id)", context: "ModelManagement")
                #endif
                
                if let details = response.details {
                    debugPrint("🚨 Download response details: \(details)")
                    #if DEBUG
                    DevLogger.shared.info("🚨 Download response details: \(details)", context: "ModelManagement")
                    #endif
                } else {
                    debugPrint("🚨 No details returned from download request")
                    #if DEBUG
                    DevLogger.shared.warning("🚨 No details returned from download request", context: "ModelManagement")
                    #endif
                }
                
                // NOW start streaming progress after the download request has been accepted by backend
                await MainActor.run {
                    for group in modelGroups.keys {
                        if var models = modelGroups[group] {
                            if let index = models.firstIndex(where: { $0.id == model.id }) {
                                var updatedModel = models[index]
                                updatedModel.status = .downloading(progress: 0.0)
                                models[index] = updatedModel
                                modelGroups[group] = models
                                // Start polling progress AFTER download request succeeds
                                startPollingProgress(for: updatedModel)
                            }
                        }
                    }
                }
            } catch {
                debugPrint("🚨 DOWNLOAD REQUEST FAILED for \(model.id): \(error.localizedDescription)")
                debugPrint("🚨 Error type: \(type(of: error))")
                
                #if DEBUG
                DevLogger.shared.error("🚨 DOWNLOAD REQUEST FAILED for \(model.id): \(error.localizedDescription)", context: "ModelManagement")
                DevLogger.shared.error("🚨 Error type: \(type(of: error))", context: "ModelManagement")
                if let apiError = error as? APIError {
                    DevLogger.shared.error("🚨 API Error details: \(apiError)", context: "ModelManagement")
                }
                #endif
                
                updateModelDownloadState(isDownloading: false, for: model.id)
                activeDownloads.remove(model.id)
                for group in modelGroups.keys {
                    if var models = modelGroups[group], let index = models.firstIndex(where: { $0.id == model.id }) {
                        var updatedModel = models[index]
                        updatedModel.status = .error(message: error.localizedDescription)
                        models[index] = updatedModel
                        modelGroups[group] = models
                    }
                }
            }
        }
    }
    
    func deleteModel(_ model: ModelDownloadInfo) async {
        // Cancel any active download for this model
        activeDownloads.remove(model.id)
        
        // Reset the progress cache for this model
        api.resetProgressCache(modelType: model.modelType, variant: model.variantId)
        
        #if DEBUG
        DevLogger.shared.info("Deleting model: \(model.id) (\(model.name))", context: "model_management")
        #endif
        
        do {
            struct EmptyBody: Codable {}
            
            #if DEBUG
            DevLogger.shared.info("Sending delete request to API for \(model.id)", context: "model_management")
            #endif
            
            _ = try await api.delete("/models/predefined/\(model.modelType)/\(model.variantId)")
            Self.logger.info("✅ Deleted model: \(model.name)")
            
            #if DEBUG
            DevLogger.shared.info("Model \(model.id) successfully deleted", context: "model_management")
            #endif
            
            // Refresh model status
            if let status = try? await checkModelStatus(model) {
                updateModelStatus(group: model.modelType, model: model.name, status: status)
                
                #if DEBUG
                DevLogger.shared.info("Model \(model.id) status updated after deletion: isDownloaded=\(status.isDownloaded)", context: "model_management")
                #endif
            }
        } catch {
            Self.logger.error("❌ Failed to delete model: \(error)")
            
            #if DEBUG
            DevLogger.shared.error("Failed to delete model \(model.id): \(error.localizedDescription)", context: "model_management")
            #endif
            
            updateModelError(name: model.name, message: error.localizedDescription)
        }
    }
    
    func updateModelError(name: String, message: String) {
        for group in modelGroups.keys {
            guard var models = modelGroups[group] else { continue }
            
            if let index = models.firstIndex(where: { $0.name == name }) {
                var updatedModel = models[index]
                updatedModel.status = .error(message: message)
                models[index] = updatedModel
                modelGroups[group] = models
            }
        }
    }
    
    func updateModelDownloadState(isDownloading: Bool, for modelId: String) {
        #if DEBUG
        DevLogger.shared.info("Updating model download state: isDownloading=\(isDownloading) for model \(modelId)", context: "ModelManagement")
        #endif
        
        for group in modelGroups.keys {
            guard var models = modelGroups[group] else { continue }
            
            if let index = models.firstIndex(where: { $0.id == modelId }) {
                var updatedModel = models[index]
                if isDownloading {
                    // Only update to downloading if not already in a downloading state
                    if case .downloading = updatedModel.status {
                        // Already downloading, no need to update
                    } else {
                        updatedModel.status = .downloading(progress: 0.0)
                    }
                } else {
                    // Reset to downloadable if not downloading
                    if case .downloading = updatedModel.status {
                        updatedModel.status = .downloadable
                    }
                }
                
                models[index] = updatedModel
                modelGroups[group] = models
                
                #if DEBUG
                DevLogger.shared.info("Model \(modelId) state updated: \(updatedModel.status)", context: "ModelManagement")
                #endif
                
                break
            }
        }
    }

    // MARK: - Cancel Download
    func cancelDownload(_ model: ModelDownloadInfo) async {
        let modelId = model.id
        Self.logger.info("🚫 Attempting to cancel download for model: \(modelId) (\(model.name))")

        // 1. Call API to cancel backend download process
        do {
            Self.logger.info("📤 Sending cancel request to backend for \(modelId)")
            _ = try await api.post("/models/cancel", [
                "model_type": model.modelType,
                "variant": model.variantId
            ])
            Self.logger.info("✅ Backend acknowledged cancel request for \(modelId)")
        } catch {
            Self.logger.error("❌ Failed to send cancel request to backend for \(modelId): \(error.localizedDescription)")
            // Optionally, update model status to an error here or decide to proceed with local cleanup anyway
        }

        // 2. Cancel local streaming task
        if let streamingTask = progressTimers[modelId] {
            streamingTask.cancel()
            Self.logger.info("🔪 Canceled local progress streaming task for \(modelId)")
        }
        progressTimers.removeValue(forKey: modelId)

        // 3. Update model status and clear progress indicators
        activeDownloads.remove(modelId)
        downloadProgress.removeValue(forKey: modelId)
        downloadProgressMetadata.removeValue(forKey: modelId)
        
        // Update the model's status in the modelGroups to reflect cancellation
        // Iterate through modelGroups to find and update the specific model
        var modelFoundAndUpdated = false
        for groupKey in modelGroups.keys {
            if var modelsInGroup = modelGroups[groupKey],
               let index = modelsInGroup.firstIndex(where: { $0.id == modelId }) {
                modelsInGroup[index].status = .downloadable // Or .error("Canceled by user") to be more specific
                modelGroups[groupKey] = modelsInGroup
                modelFoundAndUpdated = true
                Self.logger.info("🔄 Updated status of \(modelId) to downloadable after cancellation.")
                break
            }
        }
        if !modelFoundAndUpdated {
            Self.logger.warning("⚠️ Could not find \(modelId) in modelGroups to update status after cancellation.")
        }

        // 4. Notify UI of changes
        objectWillChange.send()
        Self.logger.info("✅ Cancellation process completed for \(modelId)")
    }
}

extension ModelDownloadViewModel {
    var isLocalVisionFallbackModelInstalled: Bool {
        modelGroups.values
            .flatMap { $0 }
            .contains { model in
                guard model.id == Self.localVisionFallbackModelId else { return false }
                if case .available = model.status {
                    return true
                }
                return false
            }
    }

    var reasoningModelsByProvider: [String: [ModelDownloadInfo]] {
        modelGroups
            .mapValues { $0.filter { $0.capabilities.contains(.reasoning) } }
            .filter { !$0.value.isEmpty }
    }
    var transcriptionModelsByProvider: [String: [ModelDownloadInfo]] {
        modelGroups
            .mapValues { $0.filter { $0.capabilities.contains(.transcription) } }
            .filter { !$0.value.isEmpty }
    }
}

// Add provider property to ModelDownloadInfo
extension ModelDownloadInfo {
    var provider: String {
        id.components(separatedBy: "-").first ?? "Unknown"
    }
}

