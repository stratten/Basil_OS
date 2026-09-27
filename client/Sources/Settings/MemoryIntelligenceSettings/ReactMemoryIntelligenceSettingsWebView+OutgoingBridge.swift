import Foundation

@MainActor
protocol ReactMemoryIntelligenceSettingsBridgeOutput: AnyObject {
    func sendInit(settings: MemoryIntelligenceSettingsDTO, proposals: [MemoryProposalDTO], documents: [MemoryDocumentDTO], availableModels: [ReasoningModelInfo])
    func sendSnapshot(settings: MemoryIntelligenceSettingsDTO, proposals: [MemoryProposalDTO], documents: [MemoryDocumentDTO], availableModels: [ReasoningModelInfo])
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactMemoryIntelligenceSettingsWebView: ReactMemoryIntelligenceSettingsBridgeOutput {
    func sendInit(settings: MemoryIntelligenceSettingsDTO, proposals: [MemoryProposalDTO], documents: [MemoryDocumentDTO], availableModels: [ReasoningModelInfo]) {
        var event = stateEvent(type: "init", settings: settings, proposals: proposals, documents: documents, availableModels: availableModels)
        event["protocolVersion"] = 1
        callJS("window.basilMemoryIntelligenceSettings && window.basilMemoryIntelligenceSettings.onEvent", args: event)
    }

    func sendSnapshot(settings: MemoryIntelligenceSettingsDTO, proposals: [MemoryProposalDTO], documents: [MemoryDocumentDTO], availableModels: [ReasoningModelInfo]) {
        let event = stateEvent(type: "snapshot", settings: settings, proposals: proposals, documents: documents, availableModels: availableModels)
        callJS("window.basilMemoryIntelligenceSettings && window.basilMemoryIntelligenceSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = [
            "type": "intentResult",
            "requestId": requestId,
            "status": status,
        ]
        if let message {
            event["message"] = message
        }
        callJS("window.basilMemoryIntelligenceSettings && window.basilMemoryIntelligenceSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = [
            "type": "loadError",
            "message": message,
        ]
        callJS("window.basilMemoryIntelligenceSettings && window.basilMemoryIntelligenceSettings.onEvent", args: event)
    }

    private func stateEvent(
        type: String,
        settings: MemoryIntelligenceSettingsDTO,
        proposals: [MemoryProposalDTO],
        documents: [MemoryDocumentDTO],
        availableModels: [ReasoningModelInfo]
    ) -> [String: Any] {
        [
            "type": type,
            "settings": [
                "memoryAfterTaskEnabled": settings.memoryAfterTaskEnabled,
                "memoryDailyEnabled": settings.memoryDailyEnabled,
                "memoryDailyTimeLocal": settings.memoryDailyTimeLocal,
                "memoryProcessingModel": (settings.memoryProcessingModel ?? NSNull()) as Any,
            ],
            "proposals": proposals.map { proposal in
                [
                    "id": proposal.id,
                    "targetFileName": proposal.targetFileName,
                    "entry": proposal.entry,
                    "why": proposal.why ?? NSNull(),
                    "confidence": proposal.confidence ?? NSNull(),
                    "createdAt": proposal.createdAt,
                ] as [String: Any]
            },
            "documents": documents.map { document in
                [
                    "fileName": document.fileName,
                    "sizeBytes": document.sizeBytes,
                    "capBytes": document.capBytes ?? NSNull(),
                    "updatedAt": document.updatedAt ?? NSNull(),
                ] as [String: Any]
            },
            "availableModels": availableModels.map { model in
                ["id": model.id, "displayName": model.displayName] as [String: Any]
            },
        ]
    }
}
