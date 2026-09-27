import Foundation

extension ActivityCaptureSettingsViewModel {
    // MARK: - View Lifecycle
    func onViewAppear() {
        isViewVisible = true
        Task { await adoptActiveProcessingRunIfNeeded() }
    }
    
    func onViewDisappear() {
        isViewVisible = false
        processingProgressPollTask?.cancel()
        processingProgressPollTask = nil
    }

    /// A backlog pass can be started by a previous session or window and
    /// still be running when this tab (re)opens, in which case no local poll
    /// loop exists and the progress readout/Cancel button would never appear.
    /// Adopt an in-flight run so it stays observable and interruptible, matching the Memories bridge's handling of an active narrative pass.
    private func adoptActiveProcessingRunIfNeeded() async {
        guard processingProgressPollTask == nil else { return }
        guard let progress = try? await apiClient.getActivityCaptureProcessingProgress(),
              progress.active else { return }
        await MainActor.run { self.processingProgress = progress }
        startProcessingProgressPoll()
    }
    
    // MARK: - Public Methods
    func initialize() async {
        await loadAllSettings()
    }
    
    func loadAllSettings() async {
        await withTaskGroup(of: Void.self) { group in
            group.addTask { await self.loadActivityCaptureSettings() }
            group.addTask { await self.loadAvailableModels() }
            group.addTask { await self.loadCaptureStats() }
            group.addTask { await self.loadCleanupSettings() }
            group.addTask { await self.refreshStatus() }
        }
    }
    
    func refreshStatus() async {
        do {
            let response = try await apiClient.fetchActivityCaptureStatus()
            
            isSchedulerRunning = response.isRunning
            todaysCaptures = response.todaysCaptures
            totalCapturesLast7Days = response.totalCapturesLast7Days
            totalCapturesLast30Days = response.totalCapturesLast30Days
            pendingCaptures = response.pendingCaptures
            failedCaptures = response.failedCaptures
            
            if let nextCaptureString = response.nextCapture {
                nextCaptureTime = ISO8601DateFormatter().date(from: nextCaptureString)
            }
            
            skippedCaptureCount = response.skippedCaptureCount ?? 0
            compactedCaptureCount = response.compactedCaptureCount ?? 0
            lastPolicyDecision = response.lastPolicyDecision
            if let policyTime = response.lastPolicyDecisionTime {
                lastPolicyDecisionTime = policyTime
            }

        } catch {
            print("Failed to refresh status: \(error)")
        }
    }
    
    // MARK: - Private Methods
    func setupStatusRefreshTimer() {
        statusRefreshTimer = Timer.scheduledTimer(withTimeInterval: 30.0, repeats: true) { _ in
            Task {
                await self.refreshStatus()
            }
        }
    }
    
    func startStatusRefresh() {
        setupStatusRefreshTimer()
    }
    
    func stopStatusRefresh() {
        statusRefreshTimer?.invalidate()
        statusRefreshTimer = nil
    }
}

