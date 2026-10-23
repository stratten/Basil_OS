import AppKit

/// Helper to create an NSMenuItem with the correct keyEquivalent and modifier mask for a given hotkey key/modifiers.
/// Handles F-keys, space, and standard keys. Accepts a target for the menu item.
@MainActor
func makeMenuItemWithHotkey(title: String, action: Selector?, key: String, modifiers: [String], tag: Int, target: AnyObject?) -> NSMenuItem {
    var modMask = NSEvent.ModifierFlags()
    for mod in modifiers {
        switch mod.lowercased() {
        case "command": modMask.insert(.command)
        case "option": modMask.insert(.option)
        case "control": modMask.insert(.control)
        case "shift": modMask.insert(.shift)
        case "function": modMask.insert(.function)
        default: break
        }
    }
    let keyEquivalent: String
    if key.caseInsensitiveCompare("F1") == .orderedSame ||
       key.caseInsensitiveCompare("F2") == .orderedSame ||
       key.caseInsensitiveCompare("F3") == .orderedSame ||
       key.caseInsensitiveCompare("F4") == .orderedSame ||
       key.caseInsensitiveCompare("F5") == .orderedSame ||
       key.caseInsensitiveCompare("F6") == .orderedSame ||
       key.caseInsensitiveCompare("F7") == .orderedSame ||
       key.caseInsensitiveCompare("F8") == .orderedSame ||
       key.caseInsensitiveCompare("F9") == .orderedSame ||
       key.caseInsensitiveCompare("F10") == .orderedSame ||
       key.caseInsensitiveCompare("F11") == .orderedSame ||
       key.caseInsensitiveCompare("F12") == .orderedSame ||
       key.caseInsensitiveCompare("F13") == .orderedSame ||
       key.caseInsensitiveCompare("F14") == .orderedSame ||
       key.caseInsensitiveCompare("F15") == .orderedSame ||
       key.caseInsensitiveCompare("F16") == .orderedSame ||
       key.caseInsensitiveCompare("F17") == .orderedSame ||
       key.caseInsensitiveCompare("F18") == .orderedSame ||
       key.caseInsensitiveCompare("F19") == .orderedSame ||
       key.caseInsensitiveCompare("F20") == .orderedSame {
        // Extract the F-key number
        let fNum = Int(key.dropFirst()) ?? 1
        let unicodeScalar = UnicodeScalar(0xF704 + fNum - 1)!
        keyEquivalent = String(unicodeScalar)
        modMask.insert(.function) // Always add .function for F-keys
    } else if key.caseInsensitiveCompare("Space") == .orderedSame {
        keyEquivalent = " "
    } else {
        keyEquivalent = key
    }
    let item = NSMenuItem(title: title, action: action, keyEquivalent: keyEquivalent)
    item.keyEquivalentModifierMask = modMask
    item.target = target
    item.tag = tag
    return item
}

@MainActor
func updateMenuItemWithHotkey(item: NSMenuItem, key: String, modifiers: [String]) {
    updateMenuItemWithHotkey(item: item, key: key, modifiers: modifiers, isDoublePress: false, doublePressKey: nil)
}

@MainActor
func updateMenuItemWithHotkeyBinding(item: NSMenuItem, binding: HotkeyBinding) {
    updateMenuItemWithHotkey(
        item: item,
        key: binding.key,
        modifiers: binding.modifiers,
        isDoublePress: binding.isDoublePress,
        doublePressKey: binding.doublePressKey
    )
}

@MainActor
func updateMenuItemWithHotkey(item: NSMenuItem, key: String, modifiers: [String], isDoublePress: Bool, doublePressKey: String?) {
    // Use custom display for ALL hotkeys (not native keyEquivalent) for consistent alignment
    // Hotkeys still work via HotkeyManager, not menu item key equivalents
    
    // Remove any existing shortcut/padding suffix from title (in case of refresh)
    let baseTitle = item.title
        .replacingOccurrences(of: #"[\s\t\u{2003}\u{2007}]+[⌘⌥⌃⇧A-Za-z0-9]+$"#, with: "", options: .regularExpression)
    
    // Build the shortcut display string
    let shortcutText: String
    
    if isDoublePress, let dpKey = doublePressKey {
        // Double-press hotkey (e.g., ⌘⌘ or ⌥⌥)
        let symbol = modifierToSymbol(dpKey)
        shortcutText = "\(symbol)\(symbol)"
    } else {
        // Standard hotkey - convert modifiers to symbols + key
        var symbols = ""
        for mod in modifiers {
            symbols += modifierToSymbol(mod)
        }
        
        // Format the key for display
        let keyTrimmed = key.trimmingCharacters(in: .whitespacesAndNewlines)
        let displayKey: String
        if keyTrimmed.caseInsensitiveCompare("Space") == .orderedSame {
            displayKey = "␣"  // U+2423 Open Box - standard space bar symbol
        } else if keyTrimmed.uppercased().hasPrefix("F") && keyTrimmed.count <= 3 {
            // F-key: display as-is (e.g., "F1", "F12")
            displayKey = keyTrimmed.uppercased()
        } else {
            displayKey = keyTrimmed.uppercased()
        }
        
        shortcutText = "\(symbols)\(displayKey)"
    }
    
    // Use a paragraph style with a right-aligned tab stop for proper alignment
    // Title is left-aligned, shortcut is right-aligned at a fixed position
    let menuFont = NSFont.menuFont(ofSize: 0)  // System menu font at default size
    let menuFontSize = menuFont.pointSize
    let smallerFont = NSFont.menuFont(ofSize: menuFontSize - 2)  // Slightly smaller for shortcuts
    
    // Create paragraph style with right-aligned tab stop
    let paragraphStyle = NSMutableParagraphStyle()
    let tabPosition: CGFloat = 220  // Fixed position for right edge of shortcuts
    paragraphStyle.tabStops = [NSTextTab(textAlignment: .right, location: tabPosition, options: [:])]
    
    // Build the string: "Title\tShortcut"
    let fullText = "\(baseTitle)\t\(shortcutText)"
    let attributedString = NSMutableAttributedString(string: fullText)
    
    // Apply paragraph style to entire string
    let fullRange = NSRange(location: 0, length: fullText.count)
    attributedString.addAttribute(.paragraphStyle, value: paragraphStyle, range: fullRange)
    
    // Apply regular font to title portion
    let titleRange = NSRange(location: 0, length: baseTitle.count)
    attributedString.addAttribute(.font, value: menuFont, range: titleRange)
    
    // Style the shortcut portion with smaller font and secondary color
    let shortcutStart = baseTitle.count + 1  // +1 for the tab character
    let shortcutRange = NSRange(location: shortcutStart, length: shortcutText.count)
    attributedString.addAttributes([
        .font: smallerFont,
        .foregroundColor: NSColor.secondaryLabelColor
    ], range: shortcutRange)
    
    item.attributedTitle = attributedString
    
    // Clear native key equivalent - we're using custom display only
    item.keyEquivalent = ""
    item.keyEquivalentModifierMask = []
}

/// Convert modifier name to symbol
private func modifierToSymbol(_ modifier: String) -> String {
    switch modifier.lowercased() {
    case "command", "cmd": return "⌘"
    case "option", "alt": return "⌥"
    case "control", "ctrl": return "⌃"
    case "shift": return "⇧"
    case "function", "fn": return "fn"
    default: return modifier
    }
} 