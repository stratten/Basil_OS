import Foundation

// MARK: - Supporting Types
enum ActivityCaptureProcessingMode: String, CaseIterable {
    case realtime = "realtime"
    case scheduled = "scheduled"
}

struct ActivityCaptureModelInfo: Identifiable {
    let id: String
    let displayName: String
    let provider: String
    let isLocal: Bool
}

struct ActivityCaptureStats {
    let totalFiles: Int
    let totalSizeBytes: Int64
    let filesLast7Days: Int
    let sizeLast7DaysBytes: Int64
    let filesLast30Days: Int
    let sizeLast30DaysBytes: Int64
}

