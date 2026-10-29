import Foundation

extension ModelDownloadViewModel {
    func loadModels() async {
        Self.logger.info("🚀 Starting model refresh")
        do {
            Self.logger.info("📡 Making request to /models/available")
            let data = try await api.get("/models/available")
            DevLogger.shared.info("📚 Raw models response: \(String(data: data, encoding: .utf8) ?? "unable to decode")", context: "ModelManagementUI")
            
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            
            let response = try decoder.decode([String: ProviderType].self, from: data)
            var groups: [String: [ModelDownloadInfo]] = [:]
            for (provider, providerType) in response {
                var modelInfos: [ModelDownloadInfo] = []
                for (variantKey, variant) in providerType.variants {
                    let modelCapabilities = (variant.capabilities ?? []).compactMap { $0.toModelCapabilityType() }
                    // Parse size using decimal conversion (1000^3) to match actual file sizes
                    var sizeBytes: Int64?
                    let sizeStr = variant.size.lowercased()
                    if sizeStr.hasSuffix("gb") {
                        let numStr = sizeStr.replacingOccurrences(of: "gb", with: "")
                        if let sizeGB = Double(numStr) {
                            sizeBytes = Int64(sizeGB * 1000 * 1000 * 1000)
                        }
                    } else if sizeStr.hasSuffix("mb") {
                        let numStr = sizeStr.replacingOccurrences(of: "mb", with: "")
                        if let sizeMB = Double(numStr) {
                            sizeBytes = Int64(sizeMB * 1000 * 1000)
                        }
                    } else if let size = Int64(sizeStr) {
                        sizeBytes = size
                    }
                    // Determine status
                    var status: ModelDownloadStatus = .downloadable
                    if let valid = variant.valid, valid, let path = variant.path {
                        status = .available(path: path)
                    }
                    let modelInfo = ModelDownloadInfo(
                        id: "\(provider)-\(variantKey)",
                        modelType: provider,
                        variantId: variantKey,
                        name: variant.name,
                        capabilities: modelCapabilities,
                        status: status,
                        size: sizeBytes,
                        variants: ["variants": modelCapabilities.map { $0.rawValue }]
                    )
                    modelInfos.append(modelInfo)
                }
                if !modelInfos.isEmpty {
                    groups[provider] = modelInfos.sorted(by: { $0.name < $1.name })
                }
            }
            await MainActor.run {
                self.modelGroups = groups
                self.loadError = nil
                self.isLoaded = true
            }
            await loadLocalVisionFallbackSettings()
            await loadReasoningFallbackSettings()
            await restoreActiveDownloadsFromBackend()
        } catch {
            Self.logger.error("❌ Failed to load models: \(error)")
            await MainActor.run {
                self.loadError = error
                self.isLoaded = true
            }
        }
    }

    func fetchModelSettingsDictionary() async throws -> [String: Any] {
        let data = try await api.get("/settings/models")
        guard let response = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let settings = response["settings"] as? [String: Any] else {
            throw NSError(
                domain: "ModelDownloadViewModel",
                code: -1,
                userInfo: [NSLocalizedDescriptionKey: "Invalid model settings response"]
            )
        }
        return settings
    }

    func loadLocalVisionFallbackSettings() async {
        do {
            let settings = try await fetchModelSettingsDictionary()
            localVisionFallbackEnabled = (settings["local_vision_fallback_enabled"] as? Bool) ?? false
            localVisionModelId = (settings["local_vision_model_id"] as? String) ?? Self.localVisionFallbackModelId
        } catch {
            Self.logger.error("❌ Failed to load local vision fallback settings: \(error.localizedDescription)")
        }
    }

    func updateLocalVisionFallback(enabled: Bool) async {
        do {
            var settings = try await fetchModelSettingsDictionary()
            settings["local_vision_fallback_enabled"] = enabled
            settings["local_vision_model_id"] = Self.localVisionFallbackModelId

            let data = try JSONSerialization.data(withJSONObject: settings)
            _ = try await api.put("/settings/models", data: data)
            localVisionFallbackEnabled = enabled
            localVisionModelId = Self.localVisionFallbackModelId
        } catch {
            Self.logger.error("❌ Failed to update local vision fallback: \(error.localizedDescription)")
            await loadLocalVisionFallbackSettings()
        }
    }

    func loadReasoningFallbackSettings() async {
        do {
            let settings = try await fetchModelSettingsDictionary()
            reasoningFallbackEnabled = (settings["reasoning_fallback_enabled"] as? Bool) ?? true
            reasoningFallbackModelId = (settings["reasoning_fallback_model_id"] as? String) ?? ""
        } catch {
            Self.logger.error("❌ Failed to load reasoning fallback settings: \(error.localizedDescription)")
        }
    }

    func updateReasoningFallback(enabled: Bool, modelId: String) async {
        do {
            var settings = try await fetchModelSettingsDictionary()
            settings["reasoning_fallback_enabled"] = enabled
            settings["reasoning_fallback_model_id"] = modelId

            let data = try JSONSerialization.data(withJSONObject: settings)
            _ = try await api.put("/settings/models", data: data)
            reasoningFallbackEnabled = enabled
            reasoningFallbackModelId = modelId
        } catch {
            Self.logger.error("❌ Failed to update reasoning fallback: \(error.localizedDescription)")
            await loadReasoningFallbackSettings()
        }
    }

    func checkModelStatus(_ model: ModelDownloadInfo) async throws -> (isDownloaded: Bool, size: Int64) {
        let data = try await api.get("/models/predefined/\(model.modelType)/\(model.variantId)/status")
        let status = try JSONDecoder().decode([String: Bool].self, from: data)
        let size = try await getModelSize(model)
        return (isDownloaded: status["is_downloaded"] ?? false, size: size)
    }
    
    func getModelSize(_ model: ModelDownloadInfo) async throws -> Int64 {
        let data = try await api.get("/models/predefined/\(model.modelType)/\(model.variantId)/size")
        let size = try JSONDecoder().decode([String: Int64].self, from: data)
        return size["size"] ?? 0
    }
    
    func updateModelStatus(group: String, model: String, status: (isDownloaded: Bool, size: Int64)?) {
        guard var models = modelGroups[group] else { return }
        
        if let index = models.firstIndex(where: { $0.name == model }),
           let status = status {
            var updatedModel = models[index]
            
            // Check for transition from downloading to available status
            let isTransitioningFromDownloading: Bool
            if case .downloading = updatedModel.status {
                isTransitioningFromDownloading = status.isDownloaded
            } else {
                isTransitioningFromDownloading = false
            }
            
            updatedModel.status = status.isDownloaded ? .available(path: "") : .downloadable
            updatedModel.size = status.size
            models[index] = updatedModel
            modelGroups[group] = models
            
            // If the model was downloading and is now available, reset the progress cache
            if isTransitioningFromDownloading {
                #if DEBUG
                DevLogger.shared.info("Model \(updatedModel.id) transitioned from downloading to available, resetting progress cache", context: "model_management")
                #endif
                
                api.resetProgressCache(modelType: updatedModel.modelType, variant: updatedModel.variantId)
            }
        }
    }
}

