import SwiftUI
import Foundation

@MainActor
final class ActivityCaptureSettingsViewModel: ObservableObject {
    // MARK: - Published Properties
    @Published var automaticCaptureEnabled: Bool = false
    @Published var startAtStartup: Bool = false
    @Published var captureFrequencyMinutes: Double = 5.0
    @Published var selectedProcessingModel: String = ""
    @Published var processingMode: ActivityCaptureProcessingMode = .realtime
    @Published var scheduledProcessingTime: Date = Date()
    @Published var maxFileAgeDays: Int = 30
    @Published var maxStorageMb: Int = 500
    @Published var autoCleanupEnabled: Bool = false
    @Published var excludedBundleIds: [String] = []
    @Published var idleThresholdSeconds: Double = 120
    @Published var postWakeGraceSeconds: Double = 5
    
    // Status properties (read-only for display)
    @Published var isSchedulerRunning: Bool = false
    @Published var nextCaptureTime: Date?
    @Published var todaysCaptures: Int = 0
    @Published var totalCapturesLast7Days: Int = 0
    @Published var totalCapturesLast30Days: Int = 0
    @Published var pendingCaptures: Int = 0
    @Published var failedCaptures: Int = 0
    @Published var skippedCaptureCount: Int = 0
    @Published var compactedCaptureCount: Int = 0
    @Published var lastPolicyDecision: String?
    @Published var lastPolicyDecisionTime: String?
    @Published var processingMaxRecords: Int = 0
    @Published var processingProgress: ActivityProcessingProgressResponse?
    @Published var isCancelingProcessing: Bool = false
    
    // Model selection
    @Published var availableModels: [ActivityCaptureModelInfo] = []
    @Published var isLoadingModels: Bool = false
    
    // Capture file management
    @Published var captureStats: ActivityCaptureStats?
    @Published var isLoadingCaptureStats: Bool = false
    @Published var retentionDays: Int = 30
    @Published var cleanupTime: Date = Date()
    
    // Operation states
    @Published var operationInProgress: Bool = false
    @Published var statusMessage: String?
    
    // View state tracking
    @Published var isViewVisible: Bool = false {
        didSet {
            if isViewVisible {
                startStatusRefresh()
            } else {
                stopStatusRefresh()
            }
        }
    }
    
    // MARK: - Constants
    let retentionDayOptions = [0, 7, 14, 30, 60, 90, 180, 365]
    let maxStorageOptions = [50, 100, 200, 500, 1000, 2000, 5000]
    
    // MARK: - Internal Properties
    let apiClient = APIClient.shared
    var statusRefreshTimer: Timer?
    var processingProgressPollTask: Task<Void, Never>?

    deinit {
        // Timer.invalidate() is safe to call from any thread
        statusRefreshTimer?.invalidate()
        processingProgressPollTask?.cancel()
    }
}
