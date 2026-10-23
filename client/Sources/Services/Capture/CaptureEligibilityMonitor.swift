import AppKit
import Combine
import CoreGraphics
import Foundation

@MainActor
final class CaptureEligibilityMonitor: ObservableObject {
    static let shared = CaptureEligibilityMonitor()

    @Published private(set) var idleThresholdSeconds: Double
    @Published private(set) var postWakeGraceSeconds: Double

    var isScreenLocked = false
    var isScreensaverActive = false
    var isDisplayAsleep = false
    var lastWakeOrUnlockTimestamp: Date?

    private var hasFetchedDefaults = false
    private var notificationObservers: [NSObjectProtocol] = []
    private let idleSecondsProvider: () -> TimeInterval

    init(
        idleThresholdSeconds: Double = 120,
        postWakeGraceSeconds: Double = 5,
        observeSystemNotifications: Bool = true,
        idleSecondsProvider: @escaping () -> TimeInterval = {
            CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: .null)
        }
    ) {
        self.idleThresholdSeconds = idleThresholdSeconds
        self.postWakeGraceSeconds = postWakeGraceSeconds
        self.idleSecondsProvider = idleSecondsProvider

        if observeSystemNotifications {
            registerForSystemNotifications()
        }
    }

    func applySettings(idleThresholdSeconds: Double, postWakeGraceSeconds: Double) {
        self.idleThresholdSeconds = max(idleThresholdSeconds, 0)
        self.postWakeGraceSeconds = max(postWakeGraceSeconds, 0)
    }

    func ensureDefaultsLoaded() {
        guard !hasFetchedDefaults else { return }
        hasFetchedDefaults = true

        Task { [weak self] in
            do {
                let settings = try await APIClient.shared.getActivityCaptureSettings()
                self?.applySettings(
                    idleThresholdSeconds: settings.idleThresholdSeconds,
                    postWakeGraceSeconds: settings.postWakeGraceSeconds
                )
            } catch {
                #if DEBUG
                DevLogger.shared.warning(
                    "Unable to load capture eligibility settings; using defaults: \(error)",
                    context: "CaptureEligibility"
                )
                #endif
            }
        }
    }

    func currentIneligibilityReason() -> String? {
        if isScreenLocked || isScreensaverActive {
            return "session_locked"
        }
        if isDisplayAsleep {
            return "display_asleep"
        }
        if let lastWakeOrUnlockTimestamp,
           Date().timeIntervalSince(lastWakeOrUnlockTimestamp) < postWakeGraceSeconds {
            return "post_wake_grace"
        }
        if idleThresholdSeconds > 0, idleSecondsProvider() >= idleThresholdSeconds {
            return "idle"
        }
        return nil
    }

    func handleScreenLocked() {
        isScreenLocked = true
    }

    func handleScreenUnlocked() {
        isScreenLocked = false
        lastWakeOrUnlockTimestamp = Date()
    }

    func handleScreensaverStarted() {
        isScreensaverActive = true
    }

    func handleScreensaverStopped() {
        isScreensaverActive = false
        lastWakeOrUnlockTimestamp = Date()
    }

    func handleDisplaySleep() {
        isDisplayAsleep = true
    }

    func handleDisplayWake() {
        isDisplayAsleep = false
        lastWakeOrUnlockTimestamp = Date()
    }

    private func registerForSystemNotifications() {
        let distributedCenter = DistributedNotificationCenter.default()
        let workspaceCenter = NSWorkspace.shared.notificationCenter

        notificationObservers = [
            distributedCenter.addObserver(
                forName: Notification.Name("com.apple.screenIsLocked"),
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { @MainActor in self?.handleScreenLocked() }
            },
            distributedCenter.addObserver(
                forName: Notification.Name("com.apple.screenIsUnlocked"),
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { @MainActor in self?.handleScreenUnlocked() }
            },
            distributedCenter.addObserver(
                forName: Notification.Name("com.apple.screensaver.didlaunch"),
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { @MainActor in self?.handleScreensaverStarted() }
            },
            distributedCenter.addObserver(
                forName: Notification.Name("com.apple.screensaver.didstop"),
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { @MainActor in self?.handleScreensaverStopped() }
            },
            workspaceCenter.addObserver(
                forName: NSWorkspace.screensDidSleepNotification,
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { @MainActor in self?.handleDisplaySleep() }
            },
            workspaceCenter.addObserver(
                forName: NSWorkspace.screensDidWakeNotification,
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { @MainActor in self?.handleDisplayWake() }
            }
        ]
    }
}
