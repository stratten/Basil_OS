import AppKit
import Sparkle

// Extension to AppDelegate to handle menu bar creation and actions
extension AppDelegate {

    @MainActor
    func createApplicationMenu() {
        let mainMenu = NSMenu() // This will be the main menu bar

        // --- Application Menu (to be fully populated in Phase 3) ---
        let appMenuItem = NSMenuItem()
        mainMenu.addItem(appMenuItem)
        let appMenu = NSMenu() // Title will be set by the system based on the app's name
        appMenuItem.submenu = appMenu
        
        // Populate App Menu
        let appName = Bundle.main.object(forInfoDictionaryKey: "CFBundleName") as? String ?? "Basil"
        appMenu.addItem(withTitle: "About \(appName)", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        
        if !BasilRuntimeProfile.isValidation {
            // Check for Updates (Sparkle)
            let checkForUpdatesItem = NSMenuItem(
                title: "Check for Updates...",
                action: #selector(SPUStandardUpdaterController.checkForUpdates(_:)),
                keyEquivalent: ""
            )
            checkForUpdatesItem.target = updaterController
            appMenu.addItem(checkForUpdatesItem)
        }
        
        appMenu.addItem(NSMenuItem.separator())
        let prefsItem = appMenu.addItem(withTitle: "Preferences...", action: #selector(AppDelegate.openSettings), keyEquivalent: ",")
        prefsItem.target = self // Target AppDelegate instance for openSettings

        // Services Menu
        appMenu.addItem(NSMenuItem.separator())
        let servicesItem = appMenu.addItem(withTitle: "Services", action: nil, keyEquivalent: "")
        let servicesMenu = NSMenu()
        NSApp.servicesMenu = servicesMenu // Assign a menu to servicesMenu property of NSApplication
        servicesItem.submenu = servicesMenu // Set the submenu for the "Services" menu item

        // Hide Menu
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Hide \(appName)", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let hideOthersItem = appMenu.addItem(withTitle: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        hideOthersItem.keyEquivalentModifierMask = [.command, .option]

        // Show All Menu
        appMenu.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        let quitMenuItem = appMenu.addItem(withTitle: "Quit \(appName)", action: #selector(StatusBarManager.quitApp), keyEquivalent: "q")
        quitMenuItem.target = self.statusBarManager // Assuming self (AppDelegate) has a statusBarManager instance

        // --- File Menu (to be fully populated in Phase 3) ---
        let fileMenuItem = NSMenuItem()
        mainMenu.addItem(fileMenuItem)
        let fileMenu = NSMenu(title: "File")
        fileMenuItem.submenu = fileMenu
        
        // Populate File Menu
        fileMenu.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")

        // --- Edit Menu (Populated in Phase 2, already done in previous step context) ---
        let editMenuItem = NSMenuItem()
        mainMenu.addItem(editMenuItem)
        let editMenu = NSMenu(title: "Edit")
        editMenuItem.submenu = editMenu

        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Delete", action: #selector(NSText.delete(_:)), keyEquivalent: "")
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")

        // --- View Menu (Placeholder - to be populated in Phase 3) ---
        let viewMenuItem = NSMenuItem()
        mainMenu.addItem(viewMenuItem)
        let viewMenu = NSMenu(title: "View")
        viewMenuItem.submenu = viewMenu
        // TODO: Populate View Menu - See Phase 3 of menu plan (if needed)

        // --- Window Menu (to be fully populated in Phase 3) ---
        let windowMenuItem = NSMenuItem()
        mainMenu.addItem(windowMenuItem)
        let windowMenu = NSMenu(title: "Window")
        windowMenuItem.submenu = windowMenu
        
        // Populate Window Menu
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        windowMenu.addItem(NSMenuItem.separator())
        windowMenu.addItem(withTitle: "Bring All to Front", action: #selector(NSApplication.arrangeInFront(_:)), keyEquivalent: "")

        if BasilRuntimeProfile.isValidation {
            mainMenu.addItem(validationMenuItem())
        }

        NSApplication.shared.mainMenu = mainMenu
    }

    @objc @MainActor func openSettings() {
        SettingsShellWindowController.shared.show()
    }
} 