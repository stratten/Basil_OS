import Foundation
import AppKit

public struct HotkeyBinding: Codable, Sendable {
    public let key: String
    public let enabled: Bool
    public let modifiers: [String]
    public let hotkeyDescription: String
    // Double-press modifier support (e.g., Option+Option instead of Option+Space)
    public let isDoublePress: Bool
    public let doublePressKey: String?
    
    public var modifierFlags: NSEvent.ModifierFlags {
        NSEvent.ModifierFlags(modifiers: modifiers)
    }
    
    public var description: String {
        if isDoublePress, let dpKey = doublePressKey {
            let symbol = modifierSymbol(for: dpKey)
            return "\(symbol)+\(symbol) (\(enabled ? "enabled" : "disabled"))"
        }
        let modString = modifiers.isEmpty ? "" : "\(modifiers.joined(separator: "+"))+"
        return "\(modString)\(key) (\(enabled ? "enabled" : "disabled"))"
    }
    
    /// Formatted string for UI display (e.g., "⌥␣" for Option+Space)
    public var displayString: String {
        if isDoublePress, let dpKey = doublePressKey {
            let symbol = modifierSymbol(for: dpKey)
            return "\(symbol)\(symbol)"
        }
        let symbols = modifiers.map { modifierSymbol(for: $0) }.joined()
        let displayKey: String
        if key.caseInsensitiveCompare("Space") == .orderedSame {
            displayKey = "␣"
        } else if key.uppercased().hasPrefix("F") && key.count <= 3 {
            displayKey = key.uppercased()
        } else {
            displayKey = key.uppercased()
        }
        return "\(symbols)\(displayKey)"
    }
    
    /// Get the display symbol for a modifier key
    private func modifierSymbol(for modifier: String) -> String {
        switch modifier.lowercased() {
        case "option", "alt": return "⌥"
        case "command", "cmd": return "⌘"
        case "control", "ctrl": return "⌃"
        case "shift": return "⇧"
        default: return modifier
        }
    }
    
    enum CodingKeys: String, CodingKey {
        case key
        case enabled
        case modifiers
        case hotkeyDescription = "description"
        case isDoublePress = "is_double_press"
        case doublePressKey = "double_press_key"
    }
    
    public init(key: String, enabled: Bool, modifiers: [String], hotkeyDescription: String = "", isDoublePress: Bool = false, doublePressKey: String? = nil) {
        self.key = key
        self.enabled = enabled
        self.modifiers = modifiers
        self.hotkeyDescription = hotkeyDescription
        self.isDoublePress = isDoublePress
        self.doublePressKey = doublePressKey
    }
    
    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        key = try container.decode(String.self, forKey: .key)
        enabled = try container.decode(Bool.self, forKey: .enabled)
        modifiers = try container.decode([String].self, forKey: .modifiers)
        hotkeyDescription = try container.decodeIfPresent(String.self, forKey: .hotkeyDescription) ?? ""
        isDoublePress = try container.decodeIfPresent(Bool.self, forKey: .isDoublePress) ?? false
        doublePressKey = try container.decodeIfPresent(String.self, forKey: .doublePressKey)
    }
} 