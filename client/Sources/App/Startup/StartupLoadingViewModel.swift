import Foundation

@MainActor
final class StartupLoadingViewModel {
    private(set) var currentMessage = "Starting Basil..."

    private let minimumVisibleDuration: TimeInterval
    private var monitoringTimer: Timer?
    private var onCompletionCallback: (() -> Void)?
    private var onMessageChanged: ((String) -> Void)?
    private var didComplete = false
    private var hideWhenReady = false
    private var drawnInAt: Date?

    init(minimumVisibleDuration: TimeInterval = 2) {
        self.minimumVisibleDuration = minimumVisibleDuration
    }

    func startMonitoring() {
        #if DEBUG
        DevLogger.shared.info("StartupLoadingViewModel: StartMonitoring called (API polling)", context: "StartupLoadingWindow")
        #endif

        monitoringTimer?.invalidate()

        monitoringTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.fetchAndUpdateStatus()
            }
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self] in
            Task { @MainActor in
                guard let self, self.monitoringTimer != nil else { return }
                #if DEBUG
                DevLogger.shared.warning("Failsafe: Hiding startup window after 15 seconds", context: "StartupLoadingWindow")
                #endif
                self.complete(immediately: true)
            }
        }
    }

    func stopMonitoring() {
        monitoringTimer?.invalidate()
        monitoringTimer = nil
    }

    func onCompletion(_ callback: @escaping () -> Void) {
        onCompletionCallback = callback
    }

    func onStatusChange(_ callback: @escaping (String) -> Void) {
        onMessageChanged = callback
    }

    func markDrawnIn() {
        guard drawnInAt == nil else { return }
        drawnInAt = Date()
        finishIfReady()
    }

    func complete(immediately: Bool = false) {
        if immediately {
            finishNow()
            return
        }
        hideWhenReady = true
        finishIfReady()
    }

    private func finishIfReady() {
        guard hideWhenReady, !didComplete else { return }
        guard let drawnInAt else { return }
        let remaining = minimumVisibleDuration - Date().timeIntervalSince(drawnInAt)
        if remaining <= 0 {
            finishNow()
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + remaining) { [weak self] in
            self?.finishIfReady()
        }
    }

    private func finishNow() {
        guard !didComplete else { return }
        didComplete = true
        stopMonitoring()
        onCompletionCallback?()
    }

    private func fetchAndUpdateStatus() {
        Task {
            do {
                let statusResponse = try await APIClient.shared.fetchStartupStatus()
                let newMessage = statusResponse.message

                if newMessage != currentMessage {
                    currentMessage = newMessage
                    onMessageChanged?(newMessage)
                    #if DEBUG
                    DevLogger.shared.info("Status updated via API: \(newMessage)", context: "StartupLoadingWindow")
                    #endif
                }

                if newMessage.contains("Launching interface") {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                        Task { @MainActor in
                            self.complete()
                        }
                    }
                }
            } catch APIError.backendNotAvailable {
                #if DEBUG
                if Int.random(in: 0..<10) == 0 {
                    DevLogger.shared.warning("Backend not available yet while fetching startup status.", context: "StartupLoadingWindow")
                }
                #endif
            } catch {
                #if DEBUG
                DevLogger.shared.warning("Error fetching startup status: \(error.localizedDescription)", context: "StartupLoadingWindow")
                #endif
            }
        }
    }
}
