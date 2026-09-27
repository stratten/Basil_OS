import AppKit

extension Notification.Name {
    static let basilStatusBarIconDidChange = Notification.Name("BasilStatusBarIconDidChange")
}

protocol StatusBarItemProvider {
    func createStatusItem(withLength length: CGFloat) -> NSStatusItem
    func removeStatusItem(_ item: NSStatusItem)
}

extension NSStatusBar: StatusBarItemProvider {
    func createStatusItem(withLength length: CGFloat) -> NSStatusItem {
        statusItem(withLength: length)
    }
}

final class StatusBarItem {
    // MARK: - Appearance State
    var isActiveState: Bool = false
    var isRecordingState: Bool = false
    weak var statusBarManager: StatusBarManager? // Reference to get full system state
    let modifierSymbols: [String: String] = [
        "command": "⌘",
        "option": "⌥",
        "control": "⌃",
        "shift": "⇧",
        "function": "fn"
    ]
    var statusItem: NSStatusItem?
    var statusMenu: NSMenu?
    var statusBarProvider: StatusBarItemProvider
    
    // MARK: - Initialization
    init(statusBarProvider: StatusBarItemProvider = NSStatusBar.system) {
        self.statusBarProvider = statusBarProvider
        self.statusBarManager = nil
    }
    
    // MARK: - Status Bar Item Creation/Removal
    @MainActor func setupStatusBar() {
        guard statusItem == nil else { return }
        print("Creating status item...")
        statusItem = statusBarProvider.createStatusItem(withLength: NSStatusItem.variableLength)
        if statusItem?.button == nil {
            print("Warning: Status item button is nil")
        }
        updateIconForCurrentState()
        // Menu setup would be called from the manager
        if statusItem == nil {
            print("Warning: Status item was not enabled properly")
        } else {
            print("Status item created successfully")
        }
    }
    @MainActor func enableStatusItem() async {
        setupStatusBar()
    }
    func disableStatusItem() async {
        if let statusItem = statusItem {
            statusItem.menu = nil
            statusMenu = nil
            NSStatusBar.system.removeStatusItem(statusItem)
            self.statusItem = nil
        }
    }
    
    // MARK: - Icon/Appearance Logic
    
    @MainActor private func getTopDotState() -> String {
        // Top dot: Recording (R) > Hotkey Active (G) > Hotkey Inactive (N)
        if isRecordingState {
            return "R" // Red dot for recording (overrides everything)
        } else if isActiveState {
            return "G" // Green dot for hotkey active
        } else {
            return "N" // No dot for hotkey inactive
        }
    }
    
    @MainActor private func getMiddleDotState() -> String {
        // Middle dot: Voice Active (G) > Voice Enabled but Inactive (Y) > Voice Disabled (N)
        guard let manager = statusBarManager else { return "N" }
        
        if manager.isVoiceListenerEnabled {
            // TODO: We need to track if voice listener is actively listening vs just enabled
            // For now, treat enabled as active (green), but this should be enhanced later
            return "G" // Green dot for voice listener active
        } else {
            return "N" // No dot for voice listener disabled
        }
    }
    
    @MainActor private func getBottomDotState() -> String {
        // Bottom dot: Activity Running (G) > Activity Enabled but Idle (Y) > Activity Disabled (N)
        guard let manager = statusBarManager else { return "N" }
        
        if manager.isActivityCaptureActive {
            return "G" // Green dot for activity capture running
        } else if manager.isActivityCaptureEnabled {
            return "Y" // Yellow dot for activity capture enabled but not running
        } else {
            return "N" // No dot for activity capture disabled
        }
    }
    
    @MainActor func currentIconResourceName() -> String {
        let topDot = getTopDotState()
        let middleDot = getMiddleDotState()
        let bottomDot = getBottomDotState()
        return "StatusBarIcon_T\(topDot)_M\(middleDot)_B\(bottomDot)"
    }
    
    @MainActor func updateIconForCurrentState() {
        let iconName = currentIconResourceName()
        NotificationCenter.default.post(
            name: .basilStatusBarIconDidChange,
            object: self,
            userInfo: ["iconName": iconName]
        )
        
        #if DEBUG
        print("🎨 STATUS BAR: Looking for icon: \(iconName)")
        #endif
        
        // Try 1: Asset catalog (preferred method)
        if let icon = NSImage(named: NSImage.Name(iconName)) {
            #if DEBUG
            print("✅ STATUS BAR: Found icon in asset catalog: \(iconName)")
            #endif
            configureAndSetIcon(icon)
            return
        }
        
        // Try 2: Resource URL direct path
        if let resourceURL = Bundle.main.resourceURL {
            let directPath = resourceURL.appendingPathComponent("\(iconName).png")
            #if DEBUG
            print("🔍 STATUS BAR: Trying resource URL path: \(directPath.path)")
            #endif
            if let icon = NSImage(contentsOfFile: directPath.path) {
                #if DEBUG
                print("✅ STATUS BAR: Found icon at resource URL: \(directPath.path)")
                #endif
                configureAndSetIcon(icon)
                return
            }
        }
        
        // Try 3: Bundle resource path variations
        if let resourcePath = Bundle.main.resourcePath {
            let paths = [
                "\(resourcePath)/\(iconName).png",
                "\(resourcePath)/Resources/\(iconName).png",
                "\(resourcePath)/StatusBarResources/\(iconName).png",
                "\(resourcePath)/BasilClient.app/Contents/Resources/\(iconName).png",
                "\(resourcePath)/BasilClient.app/Contents/Resources/Assets.xcassets/\(iconName).imageset/\(iconName).png"
            ]
            
            for iconPath in paths {
                #if DEBUG
                print("🔍 STATUS BAR: Trying bundle path: \(iconPath)")
                #endif
                if let icon = NSImage(contentsOfFile: iconPath) {
                    #if DEBUG
                    print("✅ STATUS BAR: Found icon at bundle path: \(iconPath)")
                    #endif
                    configureAndSetIcon(icon)
                    return
                }
            }
        }
        
        // Try 4: Development paths (only outside an explicit bundled environment).
        let isBundledApp = ProcessInfo.processInfo.environment["BASIL_BUNDLED"]?.lowercased() == "true"
        
        #if DEBUG
        print("🏭 STATUS BAR: Bundle detection:")
        print("   BASIL_BUNDLED env var: \(ProcessInfo.processInfo.environment["BASIL_BUNDLED"] ?? "not set")")
        print("   Is bundled app: \(isBundledApp)")
        #endif
        
        if !isBundledApp {
            #if DEBUG
            print("🔧 STATUS BAR: Running in development mode, trying local source paths")
            #endif
            
            let workingDirectory = URL(fileURLWithPath: FileManager.default.currentDirectoryPath, isDirectory: true)
            let clientRoots = [
                ProcessInfo.processInfo.environment["BASIL_DEVELOPMENT_CLIENT_ROOT"],
                workingDirectory.path(percentEncoded: false),
                workingDirectory.appendingPathComponent("client").path(percentEncoded: false)
            ].compactMap { $0 }
            let devPaths = clientRoots.flatMap { clientRoot in
                [
                    "\(clientRoot)/Sources/Resources/\(iconName).png",
                    "\(clientRoot)/Sources/StatusBarResources/\(iconName).png"
                ]
            }
            
            for iconPath in devPaths {
                #if DEBUG
                print("🔍 STATUS BAR: Trying dev path: \(iconPath)")
                #endif
                if let icon = NSImage(contentsOfFile: iconPath) {
                    #if DEBUG
                    print("✅ STATUS BAR: Found icon at dev path: \(iconPath)")
                    #endif
                    configureAndSetIcon(icon)
                    return
                }
            }
        } else {
            #if DEBUG
            print("🏭 STATUS BAR: Running in bundled app, skipping hardcoded dev paths")
            print("⚠️ STATUS BAR: Bundle resource loading failed - this needs investigation")
            #endif
        }
        
        // Emergency fallback for recording state
        if isRecordingState {
            #if DEBUG
            print("🔴 STATUS BAR: Using recording emoji fallback")
            #endif
            statusItem?.button?.title = "🔴"
            statusItem?.button?.image = nil
            return
        }
        
        // Final fallback: plain text "B"
        #if DEBUG
        print("⚠️ STATUS BAR: All icon loading failed, using text fallback: B")
        print("📁 STATUS BAR: Bundle info:")
        print("   Bundle path: \(Bundle.main.bundlePath)")
        print("   Resource path: \(Bundle.main.resourcePath ?? "nil")")
        print("   Resource URL: \(Bundle.main.resourceURL?.path ?? "nil")")
        #endif
        statusItem?.button?.title = "B"
        statusItem?.button?.image = nil
    }
    func configureAndSetIcon(_ icon: NSImage) {
        // Force non-template mode with multiple approaches
        icon.isTemplate = false
        
        // Create a copy to ensure we don't modify the original
        let colorIcon = icon.copy() as! NSImage
        colorIcon.isTemplate = false
        
        // Force size for consistent appearance
        colorIcon.size = NSSize(width: 22, height: 22)
        
        if let button = statusItem?.button {
            // Clear any existing image first
            button.image = nil
            button.title = ""
            
            // Set the image with non-template mode
            button.image = colorIcon
            button.imagePosition = .imageOnly
            button.imageScaling = .scaleProportionallyDown
            
            // Additional forced non-template settings
            button.image?.isTemplate = false
            
            // Force the button appearance to not treat image as template
            if let cell = button.cell as? NSButtonCell {
                cell.highlightsBy = []
                cell.showsStateBy = []
            }
            
            // Set appearance to force color rendering
            button.appearance = NSAppearance(named: .aqua)
            
            // Alternative approach: If all else fails, try setting it as a background
            if button.image?.isTemplate == true {
                // Last resort: create a composite image that can't be templated
                let compositeImage = NSImage(size: NSSize(width: 22, height: 22))
                compositeImage.lockFocus()
                colorIcon.draw(in: NSRect(x: 0, y: 0, width: 22, height: 22))
                compositeImage.unlockFocus()
                compositeImage.isTemplate = false
                
                button.image = compositeImage
                button.image?.isTemplate = false
            }
        }
    }
    // MARK: - Title/Tooltip Updates
    @MainActor
    func updateTitle(_ title: String) {
        statusItem?.button?.title = title
    }
} 