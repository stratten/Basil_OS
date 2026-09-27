import Foundation

enum MemoriesSettingsPayloadBuilder {
    static func settingsPayload(_ settings: ZettelSettingsData) -> [String: Any] {
        [
            "enabledSources": settings.enabledSources,
            "historyDays": settings.historyDays,
            "cardingEnabled": settings.cardingEnabled,
            "cardingIntervalMinutes": settings.cardingIntervalMinutes,
            "limitPerSourcePerPass": settings.limitPerSourcePerPass,
            "narrativeEnabled": settings.narrativeEnabled,
            "narrativeModel": settings.narrativeModel,
            "narrativeMode": settings.narrativeMode,
            "narrativeScheduledTime": settings.narrativeScheduledTime,
            "narrativeIntervalMinutes": settings.narrativeIntervalMinutes,
            "narrativeBatchSize": settings.narrativeBatchSize,
            "narrativeMaxAttempts": settings.narrativeMaxAttempts,
            "narrativeMaxRecords": settings.narrativeMaxRecords,
        ]
    }

    static func statsPayload(_ stats: ZettelStatsData?) -> Any {
        guard let stats else { return NSNull() }
        return [
            "collected": stats.collected,
            "summarized": stats.summarized,
            "awaitingSummary": stats.awaitingSummary,
            "awaitingRetry": stats.awaitingRetry,
            "failed": stats.failed,
            "awaitingCollection": stats.awaitingCollection,
            "bySource": stats.bySource.map { source in
                [
                    "kind": source.kind,
                    "collected": source.collected,
                    "awaitingCollection": source.awaitingCollection,
                ] as [String: Any]
            },
        ]
    }

    static func narrativeProgressPayload(_ progress: NarrativeProgressData?) -> Any {
        guard let progress else { return NSNull() }
        return [
            "active": progress.active,
            "total": progress.total,
            "processed": progress.processed,
            "finalized": progress.finalized,
            "stillOpen": progress.stillOpen,
            "failed": progress.failed,
            "remaining": progress.remaining,
            "etaSeconds": progress.etaSeconds ?? NSNull(),
            "lastError": progress.lastError ?? NSNull(),
            "cancelling": progress.cancelling ?? NSNull(),
            "analysisConcurrency": progress.analysisConcurrency ?? NSNull(),
            "processingStrategy": progress.processingStrategy ?? NSNull(),
        ] as [String: Any]
    }

    static func modelsPayload(_ models: [ActivityCaptureModelInfo]) -> [[String: Any]] {
        models.map { model in
            [
                "id": model.id,
                "displayName": model.displayName,
                "isLocal": model.isLocal,
            ]
        }
    }
}
