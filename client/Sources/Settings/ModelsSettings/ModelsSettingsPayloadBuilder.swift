import Foundation

enum ModelsSettingsPayloadBuilder {
    static let preferredProviderOrder = ["Qwen", "Solar", "Mistral", "Anthropic"]

    static func sortedGroupKeys(_ groups: [String: [ModelDownloadInfo]]) -> [String] {
        groups.keys.sorted { key1, key2 in
            let index1 = preferredProviderOrder.firstIndex(of: key1) ?? Int.max
            let index2 = preferredProviderOrder.firstIndex(of: key2) ?? Int.max
            if index1 != index2 {
                return index1 < index2
            }
            return key1 < key2
        }
    }

    static func makeCapabilityGroups(
        modelGroups: [String: [ModelDownloadInfo]],
        capability: ModelCapabilityType,
        downloadProgress: [String: Double],
        downloadProgressMetadata: [String: [String: Any]]
    ) -> [[String: Any]] {
        let filtered = modelGroups
            .mapValues { $0.filter { $0.capabilities.contains(capability) } }
            .filter { !$0.value.isEmpty }
        return sortedGroupKeys(filtered).map { provider in
            [
                "provider": provider,
                "models": (filtered[provider] ?? []).map { model in
                    makeModelWireItem(model, downloadProgress: downloadProgress, downloadProgressMetadata: downloadProgressMetadata)
                },
            ]
        }
    }

    static func makeModelWireItem(
        _ model: ModelDownloadInfo,
        downloadProgress: [String: Double],
        downloadProgressMetadata: [String: [String: Any]]
    ) -> [String: Any] {
        var item: [String: Any] = [
            "id": model.id,
            "modelType": model.modelType,
            "variantId": model.variantId,
            "name": model.name,
            "capabilities": model.capabilities.map { $0.rawValue },
            "size": model.size ?? NSNull(),
        ]

        if let liveProgress = downloadProgress[model.id] {
            item["statusKind"] = "downloading"
            item["progress"] = liveProgress
        } else {
            switch model.status {
            case .available:
                item["statusKind"] = "available"
            case .downloadable:
                item["statusKind"] = "downloadable"
            case .downloading(let progress):
                item["statusKind"] = "downloading"
                item["progress"] = progress
            case .error(let message):
                item["statusKind"] = "error"
                item["errorMessage"] = message
            }
        }

        if let metadata = downloadProgressMetadata[model.id] {
            if let totalDownloaded = metadata["total_downloaded"] as? Int64 { item["totalDownloaded"] = totalDownloaded }
            if let totalSize = metadata["total_size"] as? Int64 { item["totalSize"] = totalSize }
            if let currentFile = metadata["current_file"] as? String, !currentFile.isEmpty { item["currentFile"] = currentFile }
            if let filesCompleted = metadata["files_completed"] as? Int { item["filesCompleted"] = filesCompleted }
            if let totalFiles = metadata["total_files"] as? Int { item["totalFiles"] = totalFiles }
        }

        return item
    }
}
