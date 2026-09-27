import AppKit
import SwiftUI
import AVFoundation
import Combine
import HotKey
import ScreenCaptureKit
import CoreMedia
import Darwin
import ApplicationServices
import Foundation
import Sparkle

// Remove the incorrect import
// import BasilClient.Services.AudioProcessing

// Define an internal typealias to use in place of the concrete type
typealias AudioRecordingContentProvider = (() -> AnyView)

// AudioRecordingContentProvider will be initialized in a SwiftUI extension file
private var audioRecordingContentProvider: AudioRecordingContentProvider = {
    // If the provider isn't set up yet, return a placeholder view
    return AnyView(
        VStack {
            Text("Audio Recording")
                .font(.title)
            Text("Loading...")
                .font(.subheadline)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    )
}

// MARK: - App
final class AppDelegate: NSObject, NSApplicationDelegate {
    var statusBarManager: StatusBarManager!
    var hotkeyService: HotkeyService!
    var webSocketService: WebSocketService!
    
    // Add startup loading window
    var startupLoadingWindow: StartupLoadingWindowController?
    
    // Add a dedicated escape key monitor
    var escapeKeyMonitor: Any?
    // Add a local key monitor for diagnostic purposes
    var localKeyMonitor: Any?
    var plainTextPasteShortcutMonitor: PlainTextPasteShortcutMonitor?
    
    // Flag to control backend startup - set this to false when backend is managed externally (e.g., dev.sh)
    static var shouldStartBackend: Bool = true
    
    // Parallel setup assistant preview state. This intentionally does not
    // participate in first-run launch routing yet.
    var setupAssistantWindow: NSWindow?
    var setupPermissionsWindow: NSWindow?
    var setupAssistantKeyboardShortcuts: WindowKeyboardShortcuts?
    var setupPermissionsKeyboardShortcuts: WindowKeyboardShortcuts?
    var setupAssistantCollapseController: WindowCollapseController?
    var setupPermissionsCollapseController: WindowCollapseController?
    weak var setupAssistantThemeCoordinator: SetupAssistantWebView.Coordinator?
    weak var setupPermissionsThemeCoordinator: SetupPermissionsWebView.Coordinator?

    // Launch-time "resume your setup" toast. Lazily created on first show
    // by AppDelegate_SetupAssistant. Guarded by ``hasShownSetupAssistantResumeToastThisLaunch``
    // so a Settings-tab visit that triggers a state reload doesn't re-pop the toast.
    var setupAssistantResumeToastController: SetupAssistantResumeToastWindowController?
    var hasShownSetupAssistantResumeToastThisLaunch: Bool = false
    
    // Model download mini widget (shown alongside onboarding, independent of flow)
    var modelDownloadWindowController: ModelDownloadWindowController?

    // Floating scheduled-run mini panel (shown when scheduled agent tasks fire).
    // Lazily instantiated by AppDelegate_ScheduledRunMiniPanel so it doesn't
    // pull WKWebView resources at app launch.
    var scheduledRunMiniPanelController: ScheduledRunMiniPanelWindowController?

    // NotificationCenter observer token for the WS-bridged scheduled-agent-task
    // events that drive auto-show of the mini panel. nil until the AppDelegate
    // calls ``registerScheduledRunMiniPanelObserver()`` during launch.
    var scheduledRunMiniPanelObserverToken: NSObjectProtocol?

    // Floating ambient suggestions panel (shown when context-aware suggestions arrive).
    var ambientSuggestionsPanelController: AmbientSuggestionsPanelWindowController?
    var ambientSuggestionsObserverToken: NSObjectProtocol?

    // NotificationCenter observer token for "navigateToSettings", posted by
    // the trial-exhaustion alert (both the React panel's Swift bridge and
    // its native SwiftUI fallback) when the user picks "Sign Up"/"Continue
    // with Basil Cloud" or "Use Your Own Provider Account".
    var trialExhaustionNavigateObserverToken: NSObjectProtocol?

    // Floating meeting-detected mini panel (shown when the mechanical
    // meeting-detection loop reports a meeting in progress). Lazily built by
    // AppDelegate_MeetingDetectedMiniPanel so it costs nothing until first use.
    var meetingDetectedMiniPanelController: MeetingDetectedMiniPanelWindowController?
    var meetingDetectedObserverToken: NSObjectProtocol?

    // Observer for the "a recording actively started" signal, used to dismiss an
    // open meeting-detected join prompt (see AppDelegate_MeetingDetectedMiniPanel).
    var recordingDidStartObserverToken: NSObjectProtocol?
    
    // Sparkle updater controller for in-app updates
    var updaterController: SPUStandardUpdaterController!
    
    // Remove the explicit ConversationWidgetManager reference
    
    override init() {
        super.init()
        
        if !BasilRuntimeProfile.isValidation {
            NSLog("🚨🚨🚨 AppDelegate.init() CALLED - REGISTERING URL HANDLER")

            // Register for URL events IMMEDIATELY in init (before app finishes launching)
            // This is critical for receiving URLs when app is already running
            NSAppleEventManager.shared().setEventHandler(
                self,
                andSelector: #selector(handleGetURLEvent(_:withReplyEvent:)),
                forEventClass: AEEventClass(kInternetEventClass),
                andEventID: AEEventID(kAEGetURL)
            )

            NSLog("🚨🚨🚨 URL event handler REGISTERED successfully")

            #if DEBUG
            DevLogger.shared.info("✅ URL event handler registered in AppDelegate.init()", context: "AppDelegate")
            #endif
        }
    }
    
    // MARK: - URL Event Handler (must be in same file as registration)
    @objc func handleGetURLEvent(_ event: NSAppleEventDescriptor, withReplyEvent replyEvent: NSAppleEventDescriptor) {
        NSLog("🚨🚨🚨 handleGetURLEvent CALLED")
        DevLogger.shared.info("🚨 handleGetURLEvent called", context: "AppDelegate")
        
        guard let urlString = event.paramDescriptor(forKeyword: AEKeyword(keyDirectObject))?.stringValue,
              let url = URL(string: urlString) else {
            NSLog("🚨🚨🚨 FAILED TO EXTRACT URL from AppleEvent")
            DevLogger.shared.error("Failed to extract URL from AppleEvent", context: "AppDelegate")
            return
        }
        
        NSLog("🚨🚨🚨 Extracted URL: %@", url.absoluteString)
        DevLogger.shared.info("🚨 Extracted URL from AppleEvent: \(url.absoluteString)", context: "AppDelegate")
        
        // Call the existing URL handling logic from the extension
        self.application(NSApplication.shared, open: [url])
    }
    
    @MainActor
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSLog("🚀 BASIL APP HAS LAUNCHED - applicationDidFinishLaunching anfang") // German for beginning :)

        applyRuntimeCircularDockIcon()
        configureBackendStartupFromArguments()
        initializeLaunchServices()
        logBundleDebugInformation()

        if !BasilRuntimeProfile.isValidation {
            // Set up diagnostic local key monitor
            setupLocalKeyMonitor()
            plainTextPasteShortcutMonitor = PlainTextPasteShortcutMonitor()
        }

        // NOTE: Permissions are NOT requested at startup to avoid bombarding users with dialogs.
        // Permissions are requested either:
        // 1. During the onboarding flow (if user hasn't completed it)
        // 2. On-demand when user tries to use a feature that requires the permission

        if AppDelegate.shouldStartBackend && !BasilRuntimeProfile.isValidation {
            startBackendTask()
        }

        let api = APIClient.shared
        let localPrefs = readLocalPreferences()

        evaluateOnboardingStatus(api: api, localPrefs: localPrefs)
        logStartupHotkeySettings(api: api)
        configureBehaviorSettingsAfterBackendReady(api: api, localPrefs: localPrefs)
        cacheAppearanceSettings(api: api)
        cacheGeneralSettings(api: api)
        initializeCoreServices(api: api)
        verifyTranscriptionSettingsAfterDelay(api: api)
        setInitialStatusBarState()

        // Configure hotkeys
        // F10 for screen capture
        // F7 for audio transcription
        // F8 for suggestions
        // F9 for conversation toggle

        startWebSocketConnection()

        // Observe scheduled-agent-task WS events so the floating mini panel can
        // auto-show when a scheduled run fires. Registered after the WS
        // connection is kicked off; the actual AppDelegate-side observer
        // doesn't depend on WS state, only on the NotificationCenter signal
        // that WebSocketService posts when those event types arrive.
        if !BasilRuntimeProfile.isValidation {
            registerScheduledRunMiniPanelObserver()
            registerAmbientSuggestionsObserver()
            registerMeetingDetectedMiniPanelObserver()
            registerRecordingDidStartObserver()
            registerTrialExhaustionNavigateObserver()
        } else {
            configureValidationLaunch()
        }

        // Surface the "want to resume your setup?" toast on the next runloop
        // tick, with a small delay so the backend has a chance to come up and
        // so the menu-bar status item has been positioned (we anchor to it).
        if !BasilRuntimeProfile.isValidation {
            Task { @MainActor in
                try? await Task.sleep(nanoseconds: 3_500_000_000)
                self.presentSetupAssistantResumeToastIfPendingFromDelegate()
            }
        }
    }
    
    func applicationDidBecomeActive(_ notification: Notification) {
        #if DEBUG
        DevLogger.shared.info("Application became active", context: "AppDelegate")
        DevLogger.shared.info("🔍 Checking if URL handlers have been called...", context: "AppDelegate")
        #endif
        
        // Check if this activation is from a URL event
        // If it is, the URL handler should have already been called
        
        if !BasilRuntimeProfile.isValidation {
            // Ensure the local key monitor is set up
            setupLocalKeyMonitor()
        }
        
        print("📢 APPLICATION BECAME ACTIVE - KEY MONITORS RESET 📢")
    }

    private func applyRuntimeCircularDockIcon() {
        guard let dockIconURL = Bundle.main.url(forResource: "DockIcon", withExtension: "png"),
              let dockIcon = NSImage(contentsOf: dockIconURL) else {
            DevLogger.shared.warning("Unable to load DockIcon.png for runtime Dock icon", context: "AppDelegate")
            return
        }

        dockIcon.size = NSSize(width: 512, height: 512)
        NSApplication.shared.applicationIconImage = dockIcon
        DevLogger.shared.info("Applied runtime circular Dock icon", context: "AppDelegate")
    }
}
