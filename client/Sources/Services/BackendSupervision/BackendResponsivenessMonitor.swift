import AppKit
import Foundation

/// Watches the backend the client launched and, when it has stopped answering for about a minute, offers to restart it.
///
/// The backend heartbeat banner in the web views only says the service "will reconnect automatically if it recovers". A backend that is frozen for good never recovers, and until now the only way out was quitting Basil or restarting the backend by hand. This monitor probes `/health` every few seconds from the native side, which is independent of the web views and of the backend's own watchdog, and asks the user before doing anything. The restart reuses ``AppDelegate/startBackendProcess()``, whose launch script already terminates the old process by pid file and by port before starting a new one.
///
/// It only runs when the client owns the backend. A client started with `--no-backend-startup`, or a validation launch, never starts it.
@MainActor
final class BackendResponsivenessMonitor {
    static let shared = BackendResponsivenessMonitor()

    static let probeIntervalSeconds = 5.0
    static let probeTimeoutSeconds = 4.0
    static let offerAfterSeconds = 60.0
    static let reofferAfterSeconds = 300.0

    private var tracker = BackendResponsivenessTracker(
        offerAfterSeconds: BackendResponsivenessMonitor.offerAfterSeconds,
        reofferAfterSeconds: BackendResponsivenessMonitor.reofferAfterSeconds
    )
    private var monitorTask: Task<Void, Never>?
    private var isHandlingOffer = false
    private var restartBackend: (@MainActor () async -> Void)?
    private let session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = BackendResponsivenessMonitor.probeTimeoutSeconds
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: configuration)
    }()

    private init() {}

    /// Starts probing; calling it again is harmless. `restartBackend` must stop the stuck backend and start a fresh one, returning once the new one is ready or has failed to start.
    func start(restartBackend: @escaping @MainActor () async -> Void) {
        guard monitorTask == nil else { return }
        self.restartBackend = restartBackend
        monitorTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(BackendResponsivenessMonitor.probeIntervalSeconds * 1_000_000_000))
                await self?.probeOnce()
            }
        }
    }

    /// Uptime that does not advance while the Mac sleeps, so waking from sleep is not counted as time the backend was unresponsive.
    private static func monotonicSeconds() -> Double {
        Double(DispatchTime.now().uptimeNanoseconds) / 1_000_000_000
    }

    private func isBackendResponding() async -> Bool {
        guard let url = URL(string: APIClient.shared.baseURL + "/health") else { return false }
        var request = URLRequest(url: url)
        request.timeoutInterval = Self.probeTimeoutSeconds
        do {
            let (_, response) = try await session.data(for: request)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    private func probeOnce() async {
        guard !APIClient.isBackendShuttingDown, !isHandlingOffer else { return }
        let isHealthy = await isBackendResponding()
        guard !APIClient.isBackendShuttingDown, !isHandlingOffer else { return }
        switch tracker.record(isHealthy: isHealthy, now: Self.monotonicSeconds()) {
        case .offerRestart(let unresponsiveSeconds):
            await offerRestart(unresponsiveSeconds: unresponsiveSeconds)
        case .recoveredAfterOffer:
            NSLog("✅ BASIL: Backend answered again after a restart offer was shown")
        case nil:
            break
        }
    }

    private func offerRestart(unresponsiveSeconds: Double) async {
        isHandlingOffer = true
        defer { isHandlingOffer = false }
        NSLog("⚠️ BASIL: Backend has not answered /health for %.0f seconds; offering a restart", unresponsiveSeconds)

        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert(
            title: "Basil's background service isn't responding",
            message: "It has not answered for about a minute. Restarting it ends whatever it is doing right now, such as a transcription or an agent task, and starts it again.",
            buttons: ["Restart Background Service", "Keep Waiting"]
        )
        guard alert.runModal() == .alertFirstButtonReturn else {
            NSLog("ℹ️ BASIL: User chose to keep waiting for the backend")
            return
        }

        // The backend may have recovered while the alert was open, and a needless restart would end real work.
        if await isBackendResponding() {
            NSLog("✅ BASIL: Backend recovered while the restart offer was open; not restarting it")
            tracker.clearStreak()
            return
        }

        NSLog("🔄 BASIL: Restarting the unresponsive backend at the user's request")
        await restartBackend?()
        await APIClient.shared.updatePortAndCheckStatus()
        tracker.clearStreak()
    }
}
