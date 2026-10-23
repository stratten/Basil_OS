import AppKit
import SwiftUI

extension AgentTaskResultWebView {
    func agentTaskThemePayload() -> [String: Any] {
        AestheticWebPayload.themePayload()
    }

    func agentTaskFontPayload() -> [String: Any] {
        AestheticWebPayload.fontPayload()
    }

    func colorToHex(_ color: NSColor) -> String {
        AestheticWebPayload.colorToHex(color)
    }

    // Overload for SwiftUI Color → NSColor conversion
    func colorToHex(_ color: SwiftUI.Color) -> String {
        AestheticWebPayload.colorToHex(color)
    }
}

