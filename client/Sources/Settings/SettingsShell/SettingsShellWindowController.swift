import AppKit
import Combine
@preconcurrency import WebKit

@MainActor
final class SettingsShellWindowController: NSWindowController, NSWindowDelegate, AppearanceRefreshable {
    static let shared = SettingsShellWindowController()

    private var appearanceWebView: ReactAppearanceSettingsWebView?
    private var hotkeyWebView: HotkeySettingsWebView?
    private var shellBridge: SettingsShellBridge?
    private var keyboardShortcuts: WindowKeyboardShortcuts?
    private var collapseController: WindowCollapseController?

    private var draftSettings: AppearanceSettings
    private var persistedSettings: AppearanceSettings
    private var revision = AestheticSystem.currentAppearanceRevision + 1
    private var inFlightRequestIDs: Set<String> = []
    private var hasUnsavedAppearanceDraft = false
    private var appearanceColorWell: NSColorWell?
    private var appearanceColorPickerField: ReactAppearanceColorPickerField?
    private var pendingSettingsShellNavigation: [String: String]?

    private var hotkeyBindings: [String: HotkeyBinding] = [:]
    private var enableMonitoringAtStartup: Bool = false
    var profileWebView: ReactProfileSettingsWebView?
    var macContactsSettingsWebView: ReactMacContactsSettingsWebView?
    var dateTimeWebView: ReactDateTimeSettingsWebView?
    var dateTimeLoadGeneration: Int = 0
    var appearanceThemesWebView: ReactAppearanceThemesWebView?
    var appearanceThemesLoadGeneration: Int = 0
    var memoryWebView: ReactMemoryIntelligenceSettingsWebView?
    var memorySettingsCache: MemoryIntelligenceSettingsDTO?
    var memoryProposalsCache: [MemoryProposalDTO] = []
    var memoryDocumentsCache: [MemoryDocumentDTO] = []
    var availableMemoryModelsCache: [ReasoningModelInfo] = []
    var writingExamplesWebView: ReactWritingExamplesSettingsWebView?
    var writingExamplesCurrentFilter: ReactWritingExamplesFilter = .all
    var writingExamplesFilterGeneration: Int = 0
    var writingExamplesSamplesCache: [WritingSample] = []
    var writingExamplesStyleCache: CommunicationStyleProfile?
    var modelsWebView: ReactModelsSettingsWebView?
    let modelsViewModel = ModelDownloadViewModel()
    var modelsLoadGeneration: Int = 0
    var modelsChangeCancellable: AnyCancellable?
    var modelsLogStreamTasks: [String: Task<Void, Never>] = [:]
    var transcriptionApiModelsWebView: ReactTranscriptionAPIModelsWebView?
    let transcriptionApiModelsViewModel = TranscriptionAPIModelsViewModel()
    var transcriptionApiModelsLoadGeneration: Int = 0
    var reasoningApiModelsWebView: ReactReasoningAPIModelsWebView?
    let reasoningApiModelsViewModel = APIModelsViewModel()
    var reasoningApiModelsLoadGeneration: Int = 0
    var customModelsWebView: ReactCustomModelsWebView?
    let customModelsViewModel = CustomModelsViewModel()
    var customModelsLoadGeneration: Int = 0
    var customModelsDownloadCancellable: AnyCancellable?
    var customModelsDownloadProgressSnapshot: [String: CustomModelsDownloadProgress] = [:]
    var browserAutomationWebView: ReactBrowserAutomationSettingsWebView?
    let browserAutomationViewModel = BrowserAutomationSettingsViewModel()
    var browserAutomationLoadGeneration: Int = 0
    var reasoningDefaultsWebView: ReactReasoningDefaultsSettingsWebView?
    let reasoningDefaultsViewModel = ReasoningSettingsViewModel()
    var reasoningDefaultsLoadGeneration: Int = 0
    var skillsWebView: ReactSkillsSettingsWebView?
    let skillsViewModel = ReasoningSettingsViewModel()
    var skillsLoadGeneration: Int = 0
    var isOpeningSkillsReconciliationWorkspace = false
    var memoriesWebView: ReactMemoriesSettingsWebView?
    var memoriesSettingsCache: ZettelSettingsData?
    var availableMemoriesModelsCache: [ActivityCaptureModelInfo] = []
    var memoriesLoadGeneration: Int = 0
    var proactiveSuggestionsWebView: ReactProactiveSuggestionsSettingsWebView?
    let proactiveSuggestionsViewModel = AmbientSuggestionSettingsViewModel()
    var proactiveSuggestionsLoadGeneration: Int = 0
    var activityCaptureWebView: ReactActivityCaptureSettingsWebView?
    let activityCaptureViewModel = ActivityCaptureSettingsViewModel()
    var activityCaptureLoadGeneration: Int = 0
    var meetingDetectionWebView: ReactMeetingDetectionSettingsWebView?
    let meetingDetectionViewModel = MeetingDetectionSettingsViewModel()
    var meetingDetectionLoadGeneration: Int = 0
    var meetingAutomationWebView: ReactMeetingAutomationSettingsWebView?
    let transcriptionAutomationViewModel = TranscriptionSettingsViewModel()
    var meetingAutomationLoadGeneration: Int = 0
    var accountWebView: ReactAccountSettingsWebView?
    let accountViewModel = AccountSettingsViewModel()
    var accountLoadGeneration: Int = 0
    var accountAuthObserverCancellable: AnyCancellable?
    var transcriptionSettingsWebView: ReactTranscriptionSettingsWebView?
    let transcriptionSettingsViewModel = TranscriptionSettingsViewModel()
    var transcriptionSettingsLoadGeneration: Int = 0
    var transcriptionHistoryWebView: ReactTranscriptionHistoryWebView?
    let transcriptionHistoryViewModel = TranscriptionHistoryViewModel()
    var transcriptionHistoryLoadGeneration: Int = 0
    var transcriptionHistoryObserverCancellable: AnyCancellable?
    var permissionsApplicationWebView: ReactPermissionsApplicationWebView?
    var permissionsCommandSecurityWebView: ReactPermissionsCommandSecurityWebView?
    let permissionsSettingsViewModel = PermissionsSettingsViewModel()
    var permissionsCommandSecurityLoadGeneration: Int = 0
    var connectionsWebView: ReactConnectionsSettingsWebView?
    let connectionsViewModel = ConnectionsSettingsViewModel()
    let providerProfilesViewModel = ProviderProfilesViewModel()
    var connectionsLoadGeneration: Int = 0
    var connectionsObserverCancellable: AnyCancellable?
    var providerProfilesObserverCancellable: AnyCancellable?
    var homeWebView: ReactHomeSettingsWebView?
    let homeSetupAssistantPendingStateModel = SetupAssistantPendingStateModel()
    var homeLoadGeneration: Int = 0

    private override init(window: NSWindow?) {
        // Seed from the app-startup-cached persisted settings, not a hardcoded fixture; this production window must show the user's selected appearance on open.
        let cached = APIClient.shared.getCachedAppearanceSettings()
        self.draftSettings = cached
        self.persistedSettings = cached
        super.init(window: window)
    }

    private convenience init() {
        self.init(window: nil)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func show() {
        if window == nil || appearanceWebView == nil {
            let cached = APIClient.shared.getCachedAppearanceSettings()
            draftSettings = cached
            persistedSettings = cached
            buildWindow()
        }
        appearanceWebView?.loadContent()
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func showTranscriptionHistory() {
        pendingSettingsShellNavigation = ["tabId": "transcription", "subTabId": "history"]
        show()
    }

    /// Show the settings window and navigate directly to the given top-level
    /// tab (e.g. `"account"`). Mirrors ``showTranscriptionHistory()``.
    func navigateToTab(_ tabId: String) {
        pendingSettingsShellNavigation = ["tabId": tabId]
        show()
    }

    private func sendPendingSettingsShellNavigation() {
        guard let pendingSettingsShellNavigation, let appearanceWebView else { return }
        self.pendingSettingsShellNavigation = nil
        appearanceWebView.callJS(
            "window.basilSettingsShell && window.basilSettingsShell.navigate",
            args: pendingSettingsShellNavigation
        )
    }

    private func buildWindow() {
        let appearanceWebView = ReactAppearanceSettingsWebView()
        self.appearanceWebView = appearanceWebView

        let hotkeyWebView = HotkeySettingsWebView(webView: appearanceWebView.webView)
        self.hotkeyWebView = hotkeyWebView

        let profileWebView = ReactProfileSettingsWebView(webView: appearanceWebView.webView)
        self.profileWebView = profileWebView

        let macContactsSettingsWebView = ReactMacContactsSettingsWebView(webView: appearanceWebView.webView)
        self.macContactsSettingsWebView = macContactsSettingsWebView

        let dateTimeWebView = ReactDateTimeSettingsWebView(webView: appearanceWebView.webView)
        self.dateTimeWebView = dateTimeWebView

        let appearanceThemesWebView = ReactAppearanceThemesWebView(webView: appearanceWebView.webView)
        self.appearanceThemesWebView = appearanceThemesWebView

        let memoryWebView = ReactMemoryIntelligenceSettingsWebView(webView: appearanceWebView.webView)
        self.memoryWebView = memoryWebView

        let writingExamplesWebView = ReactWritingExamplesSettingsWebView(webView: appearanceWebView.webView)
        self.writingExamplesWebView = writingExamplesWebView

        let modelsWebView = ReactModelsSettingsWebView(webView: appearanceWebView.webView)
        self.modelsWebView = modelsWebView

        let transcriptionApiModelsWebView = ReactTranscriptionAPIModelsWebView(webView: appearanceWebView.webView)
        self.transcriptionApiModelsWebView = transcriptionApiModelsWebView

        let reasoningApiModelsWebView = ReactReasoningAPIModelsWebView(webView: appearanceWebView.webView)
        self.reasoningApiModelsWebView = reasoningApiModelsWebView

        let customModelsWebView = ReactCustomModelsWebView(webView: appearanceWebView.webView)
        self.customModelsWebView = customModelsWebView

        let browserAutomationWebView = ReactBrowserAutomationSettingsWebView(webView: appearanceWebView.webView)
        self.browserAutomationWebView = browserAutomationWebView

        let reasoningDefaultsWebView = ReactReasoningDefaultsSettingsWebView(webView: appearanceWebView.webView)
        self.reasoningDefaultsWebView = reasoningDefaultsWebView

        let skillsWebView = ReactSkillsSettingsWebView(webView: appearanceWebView.webView)
        self.skillsWebView = skillsWebView

        let memoriesWebView = ReactMemoriesSettingsWebView(webView: appearanceWebView.webView)
        self.memoriesWebView = memoriesWebView

        let proactiveSuggestionsWebView = ReactProactiveSuggestionsSettingsWebView(webView: appearanceWebView.webView)
        self.proactiveSuggestionsWebView = proactiveSuggestionsWebView

        let activityCaptureWebView = ReactActivityCaptureSettingsWebView(webView: appearanceWebView.webView)
        self.activityCaptureWebView = activityCaptureWebView

        let meetingDetectionWebView = ReactMeetingDetectionSettingsWebView(webView: appearanceWebView.webView)
        self.meetingDetectionWebView = meetingDetectionWebView

        let meetingAutomationWebView = ReactMeetingAutomationSettingsWebView(webView: appearanceWebView.webView)
        self.meetingAutomationWebView = meetingAutomationWebView

        let accountWebView = ReactAccountSettingsWebView(webView: appearanceWebView.webView)
        self.accountWebView = accountWebView

        let transcriptionSettingsWebView = ReactTranscriptionSettingsWebView(webView: appearanceWebView.webView)
        self.transcriptionSettingsWebView = transcriptionSettingsWebView

        let transcriptionHistoryWebView = ReactTranscriptionHistoryWebView(webView: appearanceWebView.webView)
        self.transcriptionHistoryWebView = transcriptionHistoryWebView

        let permissionsApplicationWebView = ReactPermissionsApplicationWebView(webView: appearanceWebView.webView)
        self.permissionsApplicationWebView = permissionsApplicationWebView

        let permissionsCommandSecurityWebView = ReactPermissionsCommandSecurityWebView(webView: appearanceWebView.webView)
        self.permissionsCommandSecurityWebView = permissionsCommandSecurityWebView

        let connectionsWebView = ReactConnectionsSettingsWebView(webView: appearanceWebView.webView)
        self.connectionsWebView = connectionsWebView

        let homeWebView = ReactHomeSettingsWebView(webView: appearanceWebView.webView)
        self.homeWebView = homeWebView

        let shellBridge = SettingsShellBridge(webView: appearanceWebView.webView)
        self.shellBridge = shellBridge

        appearanceWebView.onReady = { [weak self] in
            guard let self else { return }
            appearanceWebView.sendInit(revision: self.revision, settings: self.draftSettings, availableFonts: AestheticSystem.availableFonts)
            self.sendPendingSettingsShellNavigation()
        }
        appearanceWebView.onPreviewDraft = { [weak self] payload in
            guard let self else { return }
            guard AestheticSystem.availableFonts.contains(payload.preferredFont) else { return }
            self.draftSettings = payload.toAppearanceSettings()
            self.hasUnsavedAppearanceDraft = true
            AestheticSystem.loadFromSettings(self.draftSettings)
        }
        appearanceWebView.onSaveDraft = { [weak self] requestId, payload in
            guard let self else { return }
            guard AestheticSystem.availableFonts.contains(payload.preferredFont) else {
                appearanceWebView.sendIntentResult(requestId: requestId, status: "error", message: "Unrecognized font.")
                return
            }
            self.inFlightRequestIDs.insert(requestId)
            let settings = payload.toAppearanceSettings()
            Task { @MainActor in
                do {
                    let encoder = JSONEncoder()
                    encoder.keyEncodingStrategy = .convertToSnakeCase
                    let data = try encoder.encode(settings)
                    _ = try await APIClient.shared.put("/settings/appearance", data: data)
                    APIClient.shared.cacheAppearanceSettings(settings)
                    self.draftSettings = settings
                    self.persistedSettings = settings
                    self.hasUnsavedAppearanceDraft = false
                    self.revision += 1
                    self.inFlightRequestIDs.remove(requestId)
                    appearanceWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
                    appearanceWebView.sendSnapshot(revision: self.revision, settings: self.persistedSettings, availableFonts: AestheticSystem.availableFonts)
                } catch {
                    self.inFlightRequestIDs.remove(requestId)
                    appearanceWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to save appearance settings.")
                }
            }
        }
        appearanceWebView.onCancelDraft = { [weak self] requestId in
            guard let self else { return }
            self.draftSettings = self.persistedSettings
            self.hasUnsavedAppearanceDraft = false
            AestheticSystem.loadFromSettings(self.persistedSettings)
            appearanceWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
            appearanceWebView.sendSnapshot(revision: self.revision, settings: self.persistedSettings, availableFonts: AestheticSystem.availableFonts)
        }
        appearanceWebView.onResetDraft = { [weak self] requestId in
            guard let self else { return }
            self.draftSettings = AppearanceSettings()
            self.hasUnsavedAppearanceDraft = true
            AestheticSystem.loadFromSettings(self.draftSettings)
            appearanceWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        }
        appearanceWebView.onOpenColorPicker = { [weak self] request in
            self?.presentAppearanceColorPicker(request)
        }

        shellBridge.onClose = { [weak self] in
            self?.window?.close()
        }
        shellBridge.onMinimize = { [weak self] in
            self?.window?.miniaturize(nil)
        }
        shellBridge.onCollapse = { [weak self] in
            self?.collapseController?.setCollapsed(true)
        }
        shellBridge.onExpand = { [weak self] in
            self?.collapseController?.setCollapsed(false)
        }

        wireHotkeyWebView(hotkeyWebView)
        wireProfileSettingsWebView(profileWebView)
        wireMacContactsSettingsWebView(macContactsSettingsWebView)
        wireDateTimeSettingsWebView(dateTimeWebView)
        wireAppearanceThemesWebView(appearanceThemesWebView)
        wireMemoryIntelligenceSettingsWebView(memoryWebView)
        wireWritingExamplesSettingsWebView(writingExamplesWebView)
        wireModelsSettingsWebView(modelsWebView)
        wireTranscriptionApiModelsSettingsWebView(transcriptionApiModelsWebView)
        wireReasoningApiModelsSettingsWebView(reasoningApiModelsWebView)
        wireCustomModelsSettingsWebView(customModelsWebView)
        wireBrowserAutomationSettingsWebView(browserAutomationWebView)
        wireReasoningDefaultsSettingsWebView(reasoningDefaultsWebView)
        wireSkillsSettingsWebView(skillsWebView)
        wireMemoriesSettingsWebView(memoriesWebView)
        wireProactiveSuggestionsSettingsWebView(proactiveSuggestionsWebView)
        wireActivityCaptureSettingsWebView(activityCaptureWebView)
        wireMeetingDetectionSettingsWebView(meetingDetectionWebView)
        wireMeetingAutomationSettingsWebView(meetingAutomationWebView)
        wireAccountSettingsWebView(accountWebView)
        wireTranscriptionSettingsWebView(transcriptionSettingsWebView)
        wireTranscriptionHistoryWebView(transcriptionHistoryWebView)
        wirePermissionsApplicationWebView(permissionsApplicationWebView)
        wirePermissionsCommandSecurityWebView(permissionsCommandSecurityWebView)
        wireConnectionsSettingsWebView(connectionsWebView)
        wireHomeSettingsWebView(homeWebView)

        AppearanceRefreshCoordinator.shared.register(self)
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleAppearanceSettingsCacheUpdated),
            name: .appearanceSettingsCacheUpdated,
            object: nil
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleHotkeyStateChanged),
            name: NSNotification.Name("HotkeyStateChanged"),
            object: nil
        )

        // The React Settings shell is a multi-leaf window, so it uses the shared 1200×800 Settings size contract rather than the narrower appearance fixture size. Unlike SwiftUI's `.infinity`, AppKit needs a concrete maximum; `.greatestFiniteMagnitude` is the established unbounded-resize pattern elsewhere in this codebase (see TranscriptionWindowController).
        let window = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1100, height: 800),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Settings"
        window.isReleasedWhenClosed = false
        window.isMovableByWindowBackground = true
        window.contentView = appearanceWebView.webView
        WebKitWindowChromeAppearance.apply(to: window)
        window.contentMinSize = NSSize(width: 1000, height: 700)
        window.contentMaxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        window.center()
        window.delegate = self

        keyboardShortcuts = WindowKeyboardShortcuts(window: window)
        collapseController = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: NSSize(width: 1100, height: 800)
        )

        let dragView = WindowDragAreaView(leadingInteractiveWidth: 84, trailingInteractiveWidth: 0)
        dragView.translatesAutoresizingMaskIntoConstraints = false
        appearanceWebView.webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: appearanceWebView.webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: appearanceWebView.webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: appearanceWebView.webView.trailingAnchor),
            dragView.heightAnchor.constraint(equalToConstant: WebKitWindowChromeAppearance.frameInset + 44),
        ])

        self.window = window
    }

    func refreshAppearance() {
        appearanceWebView?.sendThemeChanged()
    }

    @objc private func handleAppearanceSettingsCacheUpdated() {
        guard !hasUnsavedAppearanceDraft,
              let settings = APIClient.shared.cachedAppearanceSettings else {
            return
        }
        persistedSettings = settings
        draftSettings = settings
        revision += 1
        appearanceWebView?.sendSnapshot(
            revision: revision,
            settings: settings,
            availableFonts: AestheticSystem.availableFonts
        )
    }

    @objc private func handleHotkeyStateChanged() {
        Task { @MainActor in
            await reloadHotkeySettingsAndSendSnapshot()
        }
    }

    func windowWillClose(_ notification: Notification) {
        // Revert any unsaved live-previewed Appearance draft regardless of
        // how the window closed (in-window Close button, Cmd+W, or any
        // other future close path) -- this used to live only in the
        // button's own `shellBridge.onClose` closure, which Cmd+W bypassed
        // entirely since it calls `window.close()` directly.
        AestheticSystem.loadFromSettings(persistedSettings)
        keyboardShortcuts?.cleanup()
        keyboardShortcuts = nil
        collapseController = nil
        HotkeyRecordingCapture.shared.cancelCapture()
        dismissAppearanceColorPicker()
        AppearanceRefreshCoordinator.shared.unregister(self)
        NotificationCenter.default.removeObserver(self, name: .appearanceSettingsCacheUpdated, object: nil)
        NotificationCenter.default.removeObserver(self, name: NSNotification.Name("HotkeyStateChanged"), object: nil)
        appearanceWebView?.tearDown()
        hotkeyWebView?.tearDown()
        profileWebView?.tearDown()
        macContactsSettingsWebView?.tearDown()
        dateTimeWebView?.tearDown()
        appearanceThemesWebView?.tearDown()
        memoryWebView?.tearDown()
        writingExamplesWebView?.tearDown()
        modelsWebView?.tearDown()
        tearDownModelsSettings()
        transcriptionApiModelsWebView?.tearDown()
        reasoningApiModelsWebView?.tearDown()
        customModelsDownloadCancellable?.cancel()
        customModelsWebView?.tearDown()
        browserAutomationWebView?.tearDown()
        reasoningDefaultsWebView?.tearDown()
        skillsWebView?.tearDown()
        memoriesWebView?.tearDown()
        proactiveSuggestionsWebView?.tearDown()
        activityCaptureViewModel.onViewDisappear()
        activityCaptureWebView?.tearDown()
        meetingDetectionWebView?.tearDown()
        meetingAutomationWebView?.tearDown()
        accountWebView?.tearDown()
        accountAuthObserverCancellable?.cancel()
        transcriptionSettingsWebView?.tearDown()
        transcriptionHistoryWebView?.tearDown()
        transcriptionHistoryObserverCancellable?.cancel()
        permissionsApplicationWebView?.tearDown()
        permissionsCommandSecurityWebView?.tearDown()
        connectionsWebView?.tearDown()
        connectionsObserverCancellable?.cancel()
        providerProfilesObserverCancellable?.cancel()
        homeWebView?.tearDown()
        shellBridge?.tearDown()
        appearanceWebView = nil
        hotkeyWebView = nil
        profileWebView = nil
        macContactsSettingsWebView = nil
        dateTimeWebView = nil
        appearanceThemesWebView = nil
        memoryWebView = nil
        writingExamplesWebView = nil
        modelsWebView = nil
        transcriptionApiModelsWebView = nil
        reasoningApiModelsWebView = nil
        customModelsWebView = nil
        customModelsDownloadCancellable = nil
        customModelsDownloadProgressSnapshot = [:]
        browserAutomationWebView = nil
        reasoningDefaultsWebView = nil
        skillsWebView = nil
        isOpeningSkillsReconciliationWorkspace = false
        memoriesWebView = nil
        memoriesSettingsCache = nil
        proactiveSuggestionsWebView = nil
        activityCaptureWebView = nil
        meetingDetectionWebView = nil
        meetingAutomationWebView = nil
        accountWebView = nil
        accountAuthObserverCancellable = nil
        transcriptionSettingsWebView = nil
        transcriptionHistoryWebView = nil
        transcriptionHistoryObserverCancellable = nil
        permissionsApplicationWebView = nil
        permissionsCommandSecurityWebView = nil
        connectionsWebView = nil
        connectionsObserverCancellable = nil
        providerProfilesObserverCancellable = nil
        homeWebView = nil
        shellBridge = nil
        pendingSettingsShellNavigation = nil
    }

    private func presentAppearanceColorPicker(_ request: ReactAppearanceColorPickerRequest) {
        guard let webView = appearanceWebView?.webView, let window = webView.window else { return }
        dismissAppearanceColorPicker()

        let pointInWindow = window.convertPoint(fromScreen: NSEvent.mouseLocation)
        let pointInWebView = webView.convert(pointInWindow, from: nil)
        let colorWell = NSColorWell(frame: NSRect(x: pointInWebView.x, y: pointInWebView.y, width: 1, height: 1))
        colorWell.alphaValue = 0
        colorWell.color = NSColor(srgbRed: request.red, green: request.green, blue: request.blue, alpha: 1)
        colorWell.target = self
        colorWell.action = #selector(handleAppearanceColorWellChanged(_:))
        webView.addSubview(colorWell)

        appearanceColorWell = colorWell
        appearanceColorPickerField = request.field
        positionColorPanel(near: NSEvent.mouseLocation)
        colorWell.activate(true)
    }

    @objc private func handleAppearanceColorWellChanged(_ sender: NSColorWell) {
        guard sender === appearanceColorWell,
              let field = appearanceColorPickerField,
              let color = sender.color.usingColorSpace(.sRGB) else { return }
        appearanceWebView?.sendColorPicked(
            field: field,
            red: color.redComponent,
            green: color.greenComponent,
            blue: color.blueComponent
        )
    }

    private func positionColorPanel(near screenPoint: NSPoint) {
        let colorPanel = NSColorPanel.shared
        guard let screen = NSScreen.screens.first(where: { $0.frame.contains(screenPoint) }) ?? NSScreen.main else { return }
        let visibleFrame = screen.visibleFrame
        let originX = min(max(visibleFrame.minX, screenPoint.x), visibleFrame.maxX - colorPanel.frame.width)
        let topY = min(max(visibleFrame.minY + colorPanel.frame.height, screenPoint.y), visibleFrame.maxY)
        colorPanel.setFrameTopLeftPoint(NSPoint(x: originX, y: topY))
    }

    private func dismissAppearanceColorPicker() {
        appearanceColorWell?.activate(false)
        appearanceColorWell?.removeFromSuperview()
        appearanceColorWell = nil
        appearanceColorPickerField = nil
    }
}

extension SettingsShellWindowController {
    private func wireHotkeyWebView(_ hotkeyWebView: HotkeySettingsWebView) {
        hotkeyWebView.onReady = { [weak self] in
            guard let self else { return }
            Task { @MainActor in
                await self.loadHotkeySettingsAndSendInit()
            }
        }
        hotkeyWebView.onStartCapture = { [weak self] id in
            guard let self, let webView = self.appearanceWebView?.webView else { return }
            guard HotkeyRowCatalog.rows.contains(where: { $0.id == id }), !self.hotkeyBindings.isEmpty else {
                hotkeyWebView.sendCaptureCanceled(id: id)
                return
            }
            HotkeyRecordingCapture.shared.startCapture(
                in: webView,
                onCaptured: { [weak self] displayString in
                    guard let self, let hotkeyWebView = self.hotkeyWebView else { return }
                    let binding = HotkeyBindingParser.parse(displayString: displayString, enabled: true)
                    hotkeyWebView.sendCaptured(id: id, binding: binding)
                },
                onCanceled: { [weak self] in
                    self?.hotkeyWebView?.sendCaptureCanceled(id: id)
                }
            )
        }
        hotkeyWebView.onCancelCapture = { _ in
            HotkeyRecordingCapture.shared.cancelCapture()
        }
        hotkeyWebView.onSaveBinding = { [weak self] requestId, id, payload in
            guard let self else { return }
            guard HotkeyRowCatalog.rows.contains(where: { $0.id == id }), !self.hotkeyBindings.isEmpty else {
                hotkeyWebView.sendIntentResult(
                    requestId: requestId,
                    status: "error",
                    message: "Hotkeys have not finished loading."
                )
                return
            }
            guard let existingBinding = self.hotkeyBindings[id] else {
                hotkeyWebView.sendIntentResult(
                    requestId: requestId,
                    status: "error",
                    message: "The selected hotkey is unavailable."
                )
                return
            }
            var updatedBindings = self.hotkeyBindings
            updatedBindings[id] = payload.toHotkeyBinding(
                preservingDescription: existingBinding.hotkeyDescription
            )
            Task { @MainActor in
                await self.putHotkeyBindings(requestId: requestId, bindings: updatedBindings)
            }
        }
        hotkeyWebView.onToggleEnableMonitoring = { [weak self] requestId, enabled in
            guard let self else { return }
            Task { @MainActor in
                await self.putEnableMonitoringAtStartup(requestId: requestId, enabled: enabled)
            }
        }
    }

    private func loadHotkeySettingsAndSendInit() async {
        do {
            let data = try await APIClient.shared.get("/settings/hotkeys")
            // NOTE: no `.convertFromSnakeCase` -- `HotkeyBinding` has explicit
            // `CodingKeys`, mirroring `HotkeySettingsViewModel.loadHotkeys()`.
            let response = try JSONDecoder().decode(HotkeySettingsResponse.self, from: data)
            hotkeyBindings = response.settings

            let behaviorData = try await APIClient.shared.get("/settings/behavior")
            let behaviorDecoder = JSONDecoder()
            behaviorDecoder.keyDecodingStrategy = .convertFromSnakeCase
            struct BehaviorSettingsResponse: Codable { let status: String; let settings: BehaviorSettings }
            let behaviorResponse = try behaviorDecoder.decode(BehaviorSettingsResponse.self, from: behaviorData)
            enableMonitoringAtStartup = behaviorResponse.settings.enableMonitoringAtStartup
        } catch {
            #if DEBUG
            DevLogger.shared.error("[HOTKEY_SETTINGS] Failed to load hotkeys/behavior for React tab: \(error)", context: "SettingsShellWindowController")
            #endif
            hotkeyWebView?.sendLoadError(message: "Failed to load hotkey settings.")
            return
        }
        hotkeyWebView?.sendInit(rows: HotkeyRowCatalog.rows, bindings: hotkeyBindings, enableMonitoringAtStartup: enableMonitoringAtStartup)
    }

    private func reloadHotkeySettingsAndSendSnapshot() async {
        do {
            let data = try await APIClient.shared.get("/settings/hotkeys")
            let response = try JSONDecoder().decode(HotkeySettingsResponse.self, from: data)

            let behaviorData = try await APIClient.shared.get("/settings/behavior")
            let behaviorDecoder = JSONDecoder()
            behaviorDecoder.keyDecodingStrategy = .convertFromSnakeCase
            struct BehaviorSettingsResponse: Codable { let status: String; let settings: BehaviorSettings }
            let behaviorResponse = try behaviorDecoder.decode(BehaviorSettingsResponse.self, from: behaviorData)

            hotkeyBindings = response.settings
            enableMonitoringAtStartup = behaviorResponse.settings.enableMonitoringAtStartup
            hotkeyWebView?.sendSnapshot(
                rows: HotkeyRowCatalog.rows,
                bindings: hotkeyBindings,
                enableMonitoringAtStartup: enableMonitoringAtStartup
            )
        } catch {
            #if DEBUG
            DevLogger.shared.error("[HOTKEY_SETTINGS] Failed to refresh externally changed hotkeys: \(error)", context: "SettingsShellWindowController")
            #endif
        }
    }

    private func putHotkeyBindings(requestId: String, bindings: [String: HotkeyBinding]) async {
        do {
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            let data = try encoder.encode(bindings)
            _ = try await APIClient.shared.put("/settings/hotkeys", data: data)
            await HotkeyService.shared.refreshHotkeys()
            hotkeyBindings = bindings
            hotkeyWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
        } catch {
            hotkeyWebView?.sendIntentResult(requestId: requestId, status: "error", message: "Failed to save hotkey.")
        }
    }

    private func putEnableMonitoringAtStartup(requestId: String, enabled: Bool) async {
        do {
            let data = try JSONSerialization.data(withJSONObject: [
                "enable_monitoring_at_startup": enabled,
            ])
            let responseData = try await APIClient.shared.put("/settings/behavior", data: data)
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            struct BehaviorSettingsUpdateResponse: Codable { let status: String; let updatedSettings: BehaviorSettings }
            let response = try decoder.decode(BehaviorSettingsUpdateResponse.self, from: responseData)
            APIClient.shared.cacheBehaviorSettings(response.updatedSettings)
            enableMonitoringAtStartup = response.updatedSettings.enableMonitoringAtStartup
            hotkeyWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
        } catch {
            hotkeyWebView?.sendIntentResult(requestId: requestId, status: "error", message: "Failed to update monitoring setting.")
        }
    }
}
