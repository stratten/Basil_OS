import Foundation

struct CustomModelsDownloadProgress: Equatable {
    let progress: Double
    let status: String
}

enum CustomModelsPayloadBuilder {
    static func makeModelSummaries(
        models: [CustomModelConfig],
        downloadProgressMap: [String: Double],
        downloadStatus: [String: String]
    ) -> [[String: Any]] {
        models.map { model in
            let needsDownload = model.isLocal
                && model.downloadUrl != nil
                && (model.modelPath == nil || model.modelPath!.isEmpty)
            var payload: [String: Any] = [
                "modelId": model.modelId,
                "displayName": model.displayName,
                "handler": model.handler,
                "isLocal": model.isLocal,
                "baseUrl": model.baseUrl as Any? ?? NSNull(),
                "modelIdentifier": model.modelIdentifier as Any? ?? NSNull(),
                "modelPath": model.modelPath as Any? ?? NSNull(),
                "downloadUrl": model.downloadUrl as Any? ?? NSNull(),
                "contextWindow": model.contextWindow,
                "maxOutputTokens": model.maxOutputTokens,
                "requiresAuth": model.requiresAuth,
                "capabilities": model.capabilities,
                "features": model.features,
                "toolRendering": model.toolRendering as Any? ?? NSNull(),
                "toolCallFormat": model.toolCallFormat as Any? ?? NSNull(),
                "description": model.description as Any? ?? NSNull(),
                "fileSize": model.fileSize as Any? ?? NSNull(),
                "fileSizeHuman": model.fileSizeHuman as Any? ?? NSNull(),
                "needsDownload": needsDownload,
            ]
            if let progress = downloadProgressMap[model.modelId] {
                payload["downloadProgress"] = progress
            }
            if let status = downloadStatus[model.modelId] {
                payload["downloadStatus"] = status
            }
            return payload
        }
    }

    static func changedDownloadProgress(
        previous: [String: CustomModelsDownloadProgress],
        downloadProgressMap: [String: Double],
        downloadStatus: [String: String]
    ) -> (snapshot: [String: CustomModelsDownloadProgress], changes: [String: CustomModelsDownloadProgress]) {
        let snapshot = Set(downloadProgressMap.keys)
            .union(downloadStatus.keys)
            .reduce(into: [String: CustomModelsDownloadProgress]()) { result, modelId in
                result[modelId] = CustomModelsDownloadProgress(
                    progress: downloadProgressMap[modelId] ?? 0,
                    status: downloadStatus[modelId] ?? "downloading"
                )
            }
        let changes = snapshot.filter { modelId, progress in
            previous[modelId] != progress
        }
        return (snapshot, changes)
    }
}
