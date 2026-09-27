import SwiftUI
import Combine
import os

@MainActor
final class ModelDownloadViewModel: ObservableObject {
    @Published var isLoaded = false
    @Published var modelGroups: [String: [ModelDownloadInfo]] = [:]
    @Published var loadError: Error?
    @Published var activeDownloads: Set<String> = []
    @Published var downloadProgress: [String: Double] = [:]
    @Published var downloadProgressMetadata: [String: [String: Any]] = [:]
    @Published var forceRefresh: Bool = false
    @Published var localVisionFallbackEnabled: Bool = false
    @Published var localVisionModelId: String = ModelDownloadViewModel.localVisionFallbackModelId
    @Published var reasoningFallbackEnabled: Bool = true
    @Published var reasoningFallbackModelId: String = ""
    
    let api = APIClient.shared
    var progressTimers: [String: Task<Void, Never>] = [:]
    let activeBackendDownloadStatuses: Set<String> = ["queued", "downloading"]
    static let localVisionFallbackModelId = "Qwen-qwen25vl-7b-instruct-q4k"
    static let logger = Logger(subsystem: Bundle.main.bundleIdentifier ?? "com.basil.client", category: "ModelManagement")
    
    var rowTimer: AnyCancellable?
    
    init() {
        Self.logger.info("📱 Initializing ModelDownloadViewModel")
    }
}

