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

    /// How long to wait before the failsafe looks at whether the backend has answered.
    private let failsafeSeconds: TimeInterval
    /// The longest the window stays up for a backend that has still not answered. After this it hides anyway, so a backend that failed to start cannot hold the window forever.
    private let slowStartLimitSeconds: TimeInterval
    private let slowStartRecheckSeconds: TimeInterval
    private var startedAt: Date?
    private(set) var backendReached = false

    static let slowStartMessage = "Still starting. This can take a minute on a slower Mac."

    init(
        minimumVisibleDuration: TimeInterval = 2,
        failsafeSeconds: TimeInterval = 15,
        slowStartLimitSeconds: TimeInterval = 120,
        slowStartRecheckSeconds: TimeInterval = 5
    ) {
        self.minimumVisibleDuration = minimumVisibleDuration
        self.failsafeSeconds = failsafeSeconds
        self.slowStartLimitSeconds = slowStartLimitSeconds
        self.slowStartRecheckSeconds = slowStartRecheckSeconds
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

        markStarted()
        DispatchQueue.main.asyncAfter(deadline: .now() + failsafeSeconds) { [weak self] in
            Task { @MainActor in
                self?.evaluateFailsafe()
            }
        }
    }

    func markStarted(at date: Date = Date()) {
        startedAt = date
    }

    /// Records that the backend answered a status request, which means the splash is waiting on startup steps and not on a backend that has not come up.
    func noteBackendReached() {
        backendReached = true
    }

    /// The failsafe that keeps the splash from outliving a startup that never finishes. A backend that has answered but never reports "Launching interface" is hidden at once, as before. A backend that has not answered at all is most likely just slow, on a Mac with less memory for instance, so the window stays up with a plain "Still starting" message and is rechecked, until the limit.
    func evaluateFailsafe(now: Date = Date()) {
        guard !didComplete, let startedAt else { return }
        let elapsed = now.timeIntervalSince(startedAt)
        if backendReached || elapsed >= slowStartLimitSeconds {
            #if DEBUG
            DevLogger.shared.warning("Failsafe: Hiding startup window after \(Int(elapsed)) seconds (backend reached: \(backendReached))", context: "StartupLoadingWindow")
            #endif
            complete(immediately: true)
            return
        }
        if currentMessage != Self.slowStartMessage {
            currentMessage = Self.slowStartMessage
            onMessageChanged?(Self.slowStartMessage)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + slowStartRecheckSeconds) { [weak self] in
            Task { @MainActor in
                self?.evaluateFailsafe()
            }
        }
    }

    func stopMonitoring() {
        monitoringTimer?.invalidate()
        monitoringTimer = nil
        startedAt = nil
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
                noteBackendReached()
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
