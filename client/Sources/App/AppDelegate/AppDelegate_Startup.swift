import AppKit
import Foundation
import Sparkle

// MARK: - Startup Flow

@MainActor
extension AppDelegate {
    func configureBackendStartupFromArguments() {
        if BasilRuntimeProfile.isValidation {
            AppDelegate.shouldStartBackend = false
            return
        }
        let args = CommandLine.arguments
        if args.contains("--no-backend-startup") {
            AppDelegate.shouldStartBackend = false
            #if DEBUG
            DevLogger.shared.info("🚫 Backend startup disabled via --no-backend-startup flag", context: "AppDelegate")
            #endif
        } else {
            // Ensure backend startup is enabled for bundled apps
            AppDelegate.shouldStartBackend = true
            #if DEBUG
            DevLogger.shared.info("✅ Backend startup enabled (no --no-backend-startup flag found)", context: "AppDelegate")
            #endif
        }
    }

    func initializeLaunchServices() {
        // Initialize WebSocketService here, as applicationDidFinishLaunching is on the main actor
        self.webSocketService = WebSocketService.shared

        // Show startup loading window immediately
        startupLoadingWindow = StartupLoadingWindowController()
        startupLoadingWindow?.viewModel?.onCompletion { [weak self] in
            Task { @MainActor in
                self?.hideStartupLoadingWindow()
            }
        }

        // Set activation policy to regular (shows dock icon)
        NSApplication.shared.setActivationPolicy(.regular)

        if !BasilRuntimeProfile.isValidation {
            // Initialize Sparkle updater for in-app updates
            updaterController = SPUStandardUpdaterController(
                startingUpdater: true,
                updaterDelegate: nil,
                userDriverDelegate: nil
            )
        }

        // Create and set up the main application menu
        createApplicationMenu()
    }

    func logBundleDebugInformation() {
        #if DEBUG
        let bundle = Bundle.main
        DevLogger.shared.info("=== Bundle Debug Information ===", context: "AppDelegate")
        DevLogger.shared.info("Bundle identifier: \(bundle.bundleIdentifier ?? "nil")", context: "AppDelegate")
        DevLogger.shared.info("Bundle path: \(bundle.bundlePath)", context: "AppDelegate")
        DevLogger.shared.info("Resource path: \(bundle.resourcePath ?? "nil")", context: "AppDelegate")
        DevLogger.shared.info("Executable path: \(bundle.executablePath ?? "nil")", context: "AppDelegate")

        DevLogger.shared.info("=== Resource URLs ===", context: "AppDelegate")
        if let resourceURL = bundle.resourceURL {
            DevLogger.shared.info("Resource URL: \(resourceURL)", context: "AppDelegate")
            do {
                let contents = try FileManager.default.contentsOfDirectory(at: resourceURL, includingPropertiesForKeys: nil)
                DevLogger.shared.info("Resource directory contents:", context: "AppDelegate")
                contents.forEach { DevLogger.shared.info("  - \($0)", context: "AppDelegate") }
            } catch {
                DevLogger.shared.error("Error listing resource directory: \(error)", context: "AppDelegate")
            }
        } else {
            DevLogger.shared.warning("No resource URL found", context: "AppDelegate")
        }
        #endif
    }

    func startBackendTask() {
        Task {
            await startBackendProcess()
        }
    }

    func evaluateOnboardingStatus(api: APIClient, localPrefs: LocalPreferences?) {
        // For NEW users: Default to showing the permission-gated Setup Assistant.
        // Only skip it if we have positive confirmation the user completed it.
        let localSaysCompleted = localPrefs?.general?.has_completed_onboarding == true

        if localSaysCompleted {
            self.presentSetupPermissionsWindowIfRequiredFromDelegate()
        } else {
            // No local confirmation of completion - check with backend, default to showing
            Task { @MainActor in
                // Wait for backend to become available (up to ~10s)
                var waited = 0
                while !api.isBackendAvailable && waited < 10 {
                    await api.updatePortAndCheckStatus()
                    try? await Task.sleep(nanoseconds: 1_000_000_000)
                    waited += 1
                }

                if api.isBackendAvailable {
                    // Backend available - check its onboarding status
                    if let settings = await api.getGeneralSettings() {
                        // Only skip onboarding if backend EXPLICITLY says completed
                        if settings.hasCompletedOnboarding == true {
                        } else {
                            // Backend says not completed (or nil) - show primary Setup Assistant flow.
                            self.presentPrimarySetupAssistantFlowFromDelegate()
                        }
                    } else {
                        // Couldn't get settings - default to showing primary Setup Assistant flow for new users.
                        self.presentPrimarySetupAssistantFlowFromDelegate()
                    }
                } else {
                    // Backend not available - default to showing primary Setup Assistant flow for new users.
                    // Better to surface setup twice than never.
                    self.presentPrimarySetupAssistantFlowFromDelegate()
                }
            }
        }
    }

    func logStartupHotkeySettings(api: APIClient) {
        #if DEBUG
        DevLogger.shared.info("Loading application settings")

        // Hotkey Settings - keep these logs as requested
        if let data = try? api.getSync("/settings/hotkeys") {
            DevLogger.shared.info("Loaded hotkey settings", context: "AppDelegate")
            DevLogger.shared.info(String(data: data, encoding: .utf8) ?? "Unable to decode as UTF-8", context: "AppDelegate")
        } else {
            DevLogger.shared.error("Failed to fetch hotkey settings", context: "AppDelegate")
        }
        #endif
    }

    func configureBehaviorSettingsAfterBackendReady(api: APIClient, localPrefs: LocalPreferences?) {
        // Load behavior settings after backend is healthy; fall back to local only for UI defaults
        Task { @MainActor in
            // Decide desired monitoring from local preferences only
            let desiredMonitoring = (localPrefs?.behavior?.enable_monitoring_at_startup == true)

            // Wait up to ~10s for backend
            var waited = 0
            while !api.isBackendAvailable && waited < 10 {
                await api.updatePortAndCheckStatus()
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                waited += 1
            }

            // Fetch behavior for caching only (do not drive enablement from server here)
            if api.isBackendAvailable, let data = try? await api.get("/settings/behavior") {
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                if let response = try? decoder.decode(BehaviorSettingsResponse.self, from: data) {
                    api.cacheBehaviorSettings(response.settings)
                }
            }

            // Enable hotkeys based on local preference, and configure when backend is ready
            if desiredMonitoring && !BasilRuntimeProfile.isValidation {
                if self.hotkeyService == nil { self.hotkeyService = HotkeyService.shared }
                if !self.hotkeyService.isEnabled {
                    self.hotkeyService.toggleHotkeys()
                }
                Task { await self.hotkeyService.configureHotkeysWhenBackendReady() }
            }

            guard !BasilRuntimeProfile.isValidation else { return }

            // Meeting Detection and Activity Capture autostart are one-shot checks
            // with no other retry path in the app: if the backend isn't available
            // right now, the user's "start at startup" preference is silently
            // never acted on for this whole session. The ~10s wait above is tuned
            // for the common case, but backend startup (e.g. loading local
            // reasoning models) can occasionally take longer, which previously
            // caused autostart to be skipped intermittently even though the
            // preference itself never changed. Give backend readiness up to two
            // more minutes here before giving up.
            var extendedWaited = 0
            while !api.isBackendAvailable && extendedWaited < 110 {
                await api.updatePortAndCheckStatus()
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                extendedWaited += 1
            }

            guard api.isBackendAvailable else {
                DevLogger.shared.error(
                    "Backend did not become available within the startup window; Meeting Detection and Activity Capture autostart were skipped for this session.",
                    context: "AppDelegate"
                )
                return
            }

            // Auto-start Meeting Detection if the user opted in. The backend
            // runtime gates the loop on `enabled`, so this is a safe no-op when
            // the feature itself is off; we then refresh the menu state to
            // reflect the running monitor.
            if let meetingDetection = try? await api.getMeetingDetectionSettings(),
               meetingDetection.startAtStartup {
                _ = try? await api.startMeetingDetection()
                await self.statusBarManager?.refreshMeetingDetectionState()
            }

            if let activityCapture = try? await api.getActivityCaptureSettings(),
               activityCapture.activityCaptureEnabled,
               activityCapture.startAtStartup {
                do {
                    try await api.startActivityCapture()
                    await self.statusBarManager?.refreshActivityCaptureState()
                } catch {
                    DevLogger.shared.error(
                        "Failed to start Activity Capture at startup: \(error.localizedDescription)",
                        context: "AppDelegate"
                    )
                }
            }
        }
    }

    func cacheAppearanceSettings(api: APIClient) {
        Task { @MainActor in
            do {
                // `get` waits for the asynchronously launched backend to become healthy and follows its port file. `getSync` raced startup on the default port, causing the in-memory theme cache to fall back to defaults despite a valid persisted file.
                let appearanceData = try await api.get("/settings/appearance")
                #if DEBUG
                DevLogger.shared.info("📥 STARTUP: Retrieved appearance settings data (\(appearanceData.count) bytes)", context: "AppDelegate")
                #endif
                let decoder = JSONDecoder()
                let response = try decoder.decode(AppearanceSettingsResponse.self, from: appearanceData)
                api.cacheAppearanceSettings(response.settings)
                #if DEBUG
                DevLogger.shared.info("✅ STARTUP: Successfully loaded and cached appearance settings", context: "AppDelegate")
                DevLogger.shared.info("🎨 STARTUP: Font: \(response.settings.preferredFont)", context: "AppDelegate")
                #endif
            } catch {
                #if DEBUG
                DevLogger.shared.error("❌ STARTUP: Error loading appearance settings: \(error)", context: "AppDelegate")
                #endif
                let defaultSettings = AppearanceSettings()
                api.cacheAppearanceSettings(defaultSettings)
                #if DEBUG
                DevLogger.shared.info("💾 STARTUP: Using default appearance settings", context: "AppDelegate")
                #endif
            }
        }
    }

    func cacheGeneralSettings(api: APIClient) {
        // Warm general settings (incl. date display style) so the shared
        // DateDisplayPreferenceStore is set before any history sidebar first renders.
        let settings = api.getCachedGeneralSettings()
        #if DEBUG
        DevLogger.shared.info("✅ STARTUP: Cached general settings (dateDisplayStyle: \(settings.dateDisplayStyle))", context: "AppDelegate")
        #endif
    }

    func initializeCoreServices(api: APIClient) {
        // Initialize services
        statusBarManager = StatusBarManager()
        hotkeyService = HotkeyService.shared
        GlobalModelDownloadMonitor.shared.start()

        // Load StatusBar states when backend becomes available
        Task {
            await statusBarManager.loadStatesWhenBackendReady()
        }

        // Check if monitoring should be enabled at startup using cached settings
        let behaviorSettings = api.getCachedBehaviorSettings()
        #if DEBUG
        DevLogger.shared.info("🔄 STARTUP: Retrieved cached behavior settings", context: "AppDelegate")
        DevLogger.shared.info("🔑 STARTUP: Cached enable_monitoring_at_startup = \(behaviorSettings.enableMonitoringAtStartup)", context: "AppDelegate")
        #endif

        if behaviorSettings.enableMonitoringAtStartup && !BasilRuntimeProfile.isValidation {
            #if DEBUG
            DevLogger.shared.info("🎯 STARTUP: Auto-enabling monitoring at startup as requested in settings", context: "AppDelegate")
            DevLogger.shared.info("🔍 STARTUP: Current hotkeyService.isEnabled = \(hotkeyService.isEnabled)", context: "AppDelegate")
            #endif

            // Enable hotkeys/monitoring if the setting is true
            if !hotkeyService.isEnabled {
                #if DEBUG
                DevLogger.shared.info("🚀 STARTUP: Calling hotkeyService.toggleHotkeys() to enable monitoring", context: "AppDelegate")
                #endif
                hotkeyService.toggleHotkeys()
                #if DEBUG
                DevLogger.shared.info("✅ STARTUP: After toggle, hotkeyService.isEnabled = \(hotkeyService.isEnabled)", context: "AppDelegate")
                #endif
            } else {
                #if DEBUG
                DevLogger.shared.info("ℹ️ STARTUP: Hotkey service already enabled, no toggle needed", context: "AppDelegate")
                #endif
            }

            // Configure hotkeys when backend becomes available
            Task {
                await hotkeyService.configureHotkeysWhenBackendReady()
            }
        } else {
            #if DEBUG
            DevLogger.shared.info("⏸️ STARTUP: Monitoring at startup is disabled in settings (enableMonitoringAtStartup=false)", context: "AppDelegate")
            #endif
        }
    }

    func verifyTranscriptionSettingsAfterDelay(api: APIClient) {
        // Initiate a second check after a delay to see if settings change
        Task {
            // Wait a moment to let the UI initialize
            try? await Task.sleep(nanoseconds: 2_000_000_000) // 2 seconds

            #if DEBUG
            DevLogger.shared.info("Verifying settings after delay", context: "AppDelegate")

            // Get fresh settings from the server for comparison
            do {
                let data = try await api.get("/settings/transcription")
                if let response = try? JSONDecoder().decode(TranscriptionSettingsResponse.self, from: data) {
                    DevLogger.shared.info("Verified transcription settings - autoCloseOnPaste: \(response.settings.autoCloseOnPaste)", context: "AppDelegate")
                }
            } catch {
                DevLogger.shared.error("Failed to get fresh settings: \(error)", context: "AppDelegate")
            }
            #endif
        }
    }

    func setInitialStatusBarState() {
        // Set up initial state
        Task { @MainActor in
            statusBarManager.setActive(false)

            #if DEBUG
            DevLogger.shared.info("Basil initialized successfully!", context: "AppDelegate")
            DevLogger.shared.info("Status bar icon should now be visible in the menu bar", context: "AppDelegate")
            #endif
        }
    }

    func startWebSocketConnection() {
        // Initialize WebSocket connection
        Task {
            await APIClient.shared.updatePortAndCheckStatus()
            webSocketService.connect()
        }
    }
}
