import Foundation
import ApplicationServices
import AppKit

struct TextSelectionResult {
    let hasSelection: Bool
    let selectedText: String
    let selectionRange: NSRange
    let containingText: String
    let applicationName: String
    let confidence: Double
    
    static let empty = TextSelectionResult(
        hasSelection: false,
        selectedText: "",
        selectionRange: NSRange(location: 0, length: 0),
        containingText: "",
        applicationName: "Unknown",
        confidence: 0.0
    )
}

@MainActor
class TextSelectionService: ObservableObject {
    
    func detectTextSelection() async -> TextSelectionResult {
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] Starting text selection detection", context: "TextSelectionService")
        #endif
        
        // First check if we have accessibility permissions
        guard checkAccessibilityPermissions() else {
            #if DEBUG
            DevLogger.shared.warning("[TEXT_SELECTION] No accessibility permissions - cannot detect text selection", context: "TextSelectionService")
            #endif
            return TextSelectionResult.empty
        }
        
        let appName = getCurrentApplicationName()
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] Current application: \(appName)", context: "TextSelectionService")
        #endif
        
        // Try multiple detection strategies
        if let result = try_strategy_focusedElement(appName: appName) {
            return result
        }
        
        if let result = try_strategy_systemWideElement(appName: appName) {
            return result
        }
        
        if let result = try_strategy_applicationSpecific(appName: appName) {
            return result
        }
        
        // Final fallback: Use clipboard method (Command+C simulation)
        if let result = try_strategy_clipboardFallback(appName: appName) {
            return result
        }
        
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] No text selection detected with any strategy", context: "TextSelectionService")
        #endif
        return TextSelectionResult.empty
    }
    
    private func checkAccessibilityPermissions() -> Bool {
        let checkOptPrompt = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        let options = [checkOptPrompt: false] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }
    
    // Strategy 1: Standard focused element approach
    private func try_strategy_focusedElement(appName: String) -> TextSelectionResult? {
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] Trying focused element strategy", context: "TextSelectionService")
        #endif
        
        guard let focusedElement = getFocusedElement() else {
            #if DEBUG
            DevLogger.shared.info("[TEXT_SELECTION] No focused element found", context: "TextSelectionService")
            #endif
            return nil
        }
        
        return extractSelectionFromElement(focusedElement, appName: appName, strategy: "focused_element")
    }
    
    // Strategy 2: System-wide element traversal
    private func try_strategy_systemWideElement(appName: String) -> TextSelectionResult? {
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] Trying system-wide element strategy", context: "TextSelectionService")
        #endif
        
        // Try to find application element
        if let appElement = getApplicationElement(for: appName) {
            return extractSelectionFromElement(appElement, appName: appName, strategy: "system_wide")
        }
        
        return nil
    }
    
    // Strategy 3: Application-specific approaches 
    private func try_strategy_applicationSpecific(appName: String) -> TextSelectionResult? {
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] Trying application-specific strategy for: \(appName)", context: "TextSelectionService")
        #endif
        
        // Handle specific applications that might have different accessibility patterns
        switch appName.lowercased() {
        case "textedit", "pages", "word", "notes":
            return try_textEditor_strategy(appName: appName)
        case "safari", "chrome", "firefox":
            return try_webBrowser_strategy(appName: appName)
        case "mail":
            return try_mail_strategy(appName: appName)
        default:
            return try_generic_fallback(appName: appName)
        }
    }
    
    // Strategy 4: Clipboard-based fallback (Command+C simulation)
    private func try_strategy_clipboardFallback(appName: String) -> TextSelectionResult? {
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] Trying clipboard fallback strategy (Command+C simulation)", context: "TextSelectionService")
        #endif
        
        let pasteboard = NSPasteboard.general
        
        // Save current clipboard content BEFORE Command+C
        let originalClipboard = pasteboard.string(forType: .string)
        let originalChangeCount = pasteboard.changeCount
        
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] Original clipboard saved (change count: \(originalChangeCount))", context: "TextSelectionService")
        if let original = originalClipboard {
            DevLogger.shared.info("[TEXT_SELECTION] Original clipboard preview: \"\(original.prefix(50))...\"", context: "TextSelectionService")
        }
        #endif
        
        // Simulate Command+C WITHOUT clearing clipboard first
        let success = simulateCopyShortcut()
        
        guard success else {
            #if DEBUG
            DevLogger.shared.warning("[TEXT_SELECTION] Failed to simulate Command+C", context: "TextSelectionService")
            #endif
            return nil
        }
        
        // Small delay to allow clipboard to update
        usleep(50000) // 50ms delay
        
        let newChangeCount = pasteboard.changeCount
        let newClipboardContent = pasteboard.string(forType: .string)
        
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] Clipboard check - original count: \(originalChangeCount), new count: \(newChangeCount)", context: "TextSelectionService")
        #endif
        
        // Only succeed if Command+C actually CHANGED the clipboard
        // If changeCount increased AND content is different from original, something was selected
        if newChangeCount > originalChangeCount,
           let selectedText = newClipboardContent,
           !selectedText.isEmpty,
           selectedText != originalClipboard {
            
            #if DEBUG
            DevLogger.shared.info("[TEXT_SELECTION] ✅ Clipboard fallback successful! Found selected text: \"\(selectedText.prefix(50))...\" (length: \(selectedText.count))", context: "TextSelectionService")
            #endif
            
            // Restore original clipboard
            restoreClipboard(originalContent: originalClipboard)
            
            // Create result with high confidence since this method is very reliable
            return TextSelectionResult(
                hasSelection: true,
                selectedText: selectedText,
                selectionRange: NSRange(location: 0, length: selectedText.count),
                containingText: "", // We don't have context with this method
                applicationName: appName,
                confidence: 0.95 // High confidence - clipboard method is very reliable
            )
        } else {
            #if DEBUG
            DevLogger.shared.info("[TEXT_SELECTION] No text selection detected via clipboard method", context: "TextSelectionService")
            #endif
            
            // Restore original clipboard
            restoreClipboard(originalContent: originalClipboard)
            return nil
        }
    }
    
    private func simulateCopyShortcut() -> Bool {
        // Create Command+C key event
        guard let keyDownEvent = CGEvent(keyboardEventSource: nil, virtualKey: 8, keyDown: true),  // 8 = 'C' key
              let keyUpEvent = CGEvent(keyboardEventSource: nil, virtualKey: 8, keyDown: false) else {
            return false
        }
        
        // Add Command modifier
        keyDownEvent.flags = .maskCommand
        keyUpEvent.flags = .maskCommand
        
        // Post the events
        keyDownEvent.post(tap: .cghidEventTap)
        keyUpEvent.post(tap: .cghidEventTap)
        
        return true
    }
    
    private func restoreClipboard(originalContent: String?) {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        
        if let originalContent = originalContent {
            pasteboard.setString(originalContent, forType: .string)
            #if DEBUG
            DevLogger.shared.info("[TEXT_SELECTION] Original clipboard content restored", context: "TextSelectionService")
            #endif
        }
    }
    
    private func extractSelectionFromElement(_ element: AXUIElement, appName: String, strategy: String) -> TextSelectionResult? {
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] Extracting selection from element using \(strategy) strategy", context: "TextSelectionService")
        #endif
        
        // Log available attributes for debugging
        logElementAttributes(element, strategy: strategy)
        
        // Try to get selected text directly
        if let (selectedText, range) = getSelectedTextFromElement(element),
           !selectedText.isEmpty {
            
            #if DEBUG
            DevLogger.shared.info("[TEXT_SELECTION] Found selected text: \"\(selectedText.prefix(50))...\" (length: \(selectedText.count))", context: "TextSelectionService")
            #endif
            
            // Get containing text for context
            let containingText = getContainingTextFromElement(element) ?? ""
            
            return TextSelectionResult(
                hasSelection: true,
                selectedText: selectedText,
                selectionRange: range,
                containingText: containingText,
                applicationName: appName,
                confidence: validateSelection(selectedText, in: containingText)
            )
        }
        
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] No selected text found with \(strategy) strategy", context: "TextSelectionService")
        #endif
        return nil
    }
    
    private func logElementAttributes(_ element: AXUIElement, strategy: String) {
        #if DEBUG
        var attributeNames: CFArray?
        let result = AXUIElementCopyAttributeNames(element, &attributeNames)
        
        if result == .success, let names = attributeNames as? [String] {
            DevLogger.shared.info("[TEXT_SELECTION] [\(strategy)] Available attributes: \(names.joined(separator: ", "))", context: "TextSelectionService")
            
            // Check specifically for text-related attributes
            let textAttributes = names.filter { name in
                name.lowercased().contains("text") || name.lowercased().contains("select")
            }
            if !textAttributes.isEmpty {
                DevLogger.shared.info("[TEXT_SELECTION] [\(strategy)] Text-related attributes: \(textAttributes.joined(separator: ", "))", context: "TextSelectionService")
            }
        }
        #endif
    }
    
    private func getFocusedElement() -> AXUIElement? {
        let systemWideElement = AXUIElementCreateSystemWide()
        var focusedElement: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(systemWideElement, kAXFocusedUIElementAttribute as CFString, &focusedElement)
        
        guard result == .success, let element = focusedElement else {
            return nil
        }
        
        return (element as! AXUIElement)
    }
    
    private func getApplicationElement(for appName: String) -> AXUIElement? {
        // Get running applications and find the one matching appName
        for app in NSWorkspace.shared.runningApplications {
            if app.localizedName == appName && app.isActive {
                let pid = app.processIdentifier
                return AXUIElementCreateApplication(pid)
            }
        }
        return nil
    }
    
    private func getSelectedTextFromElement(_ element: AXUIElement) -> (text: String, range: NSRange)? {
        // Try multiple attribute approaches
        let attributesToTry = [
            kAXSelectedTextAttribute as CFString,
            "AXSelectedText" as CFString,
            kAXValueAttribute as CFString  // Sometimes selection is part of value
        ]
        
        for attribute in attributesToTry {
            var selectedTextRef: CFTypeRef?
            let selectedTextResult = AXUIElementCopyAttributeValue(element, attribute, &selectedTextRef)
            
            if selectedTextResult == .success,
               let selectedText = selectedTextRef as? String,
               !selectedText.isEmpty {
                
                #if DEBUG
                DevLogger.shared.info("[TEXT_SELECTION] Found text via attribute \(attribute): \"\(selectedText.prefix(30))...\"", context: "TextSelectionService")
                #endif
                
                // Try to get selection range
                var rangeRef: CFTypeRef?
                let rangeResult = AXUIElementCopyAttributeValue(element, kAXSelectedTextRangeAttribute as CFString, &rangeRef)
                
                if rangeResult == .success,
                   let rangeValue = rangeRef {
                    var range = NSRange()
                    if AXValueGetValue(rangeValue as! AXValue, .cfRange, &range) {
                        // CRITICAL: Check if this is actually a selection or just the full content
                        // If range length is 0, or if it spans the entire text, it's likely not a real selection
                        if range.length == 0 {
                            #if DEBUG
                            DevLogger.shared.info("[TEXT_SELECTION] Range length is 0 - not a real selection", context: "TextSelectionService")
                            #endif
                            continue  // Try next attribute
                        }
                        
                        // If range covers the entire text AND text is large, it's probably the full content, not a selection
                        if range.location == 0 && range.length == selectedText.count && selectedText.count > 500 {
                            #if DEBUG
                            DevLogger.shared.info("[TEXT_SELECTION] Range covers entire text (\(selectedText.count) chars) - likely full content, not selection", context: "TextSelectionService")
                            #endif
                            continue  // Try next attribute
                        }
                        
                        return (selectedText, range)
                    }
                }
                
                // If we got text but no valid range, check if it's suspiciously large
                if selectedText.count > 500 {
                    #if DEBUG
                    DevLogger.shared.info("[TEXT_SELECTION] Text is large (\(selectedText.count) chars) with no range - likely full content, not selection", context: "TextSelectionService")
                    #endif
                    continue  // Try next attribute
                }
                
                // Return with default range if we can't get the actual range
                return (selectedText, NSRange(location: 0, length: selectedText.count))
            }
        }
        
        return nil
    }
    
    private func getContainingTextFromElement(_ element: AXUIElement) -> String? {
        let attributesToTry = [
            kAXValueAttribute as CFString,
            "AXValue" as CFString,
            "AXContents" as CFString,
            "AXTextContent" as CFString
        ]
        
        for attribute in attributesToTry {
            var valueRef: CFTypeRef?
            let result = AXUIElementCopyAttributeValue(element, attribute, &valueRef)
            
            if result == .success, let value = valueRef as? String, !value.isEmpty {
                #if DEBUG
                DevLogger.shared.info("[TEXT_SELECTION] Found containing text via \(attribute): \(value.count) characters", context: "TextSelectionService")
                #endif
                return value
            }
        }
        
        return nil
    }
    
    // Application-specific strategies
    private func try_textEditor_strategy(appName: String) -> TextSelectionResult? {
        // For text editors, try to access document content directly
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] Using text editor strategy for \(appName)", context: "TextSelectionService")
        #endif
        return nil // Placeholder for specific implementation
    }
    
    private func try_webBrowser_strategy(appName: String) -> TextSelectionResult? {
        // For browsers, might need to use different accessibility paths
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] Using web browser strategy for \(appName)", context: "TextSelectionService")
        #endif
        return nil // Placeholder for specific implementation
    }
    
    private func try_mail_strategy(appName: String) -> TextSelectionResult? {
        // For Mail.app, specific accessibility patterns
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] Using mail strategy for \(appName)", context: "TextSelectionService")
        #endif
        return nil // Placeholder for specific implementation
    }
    
    private func try_generic_fallback(appName: String) -> TextSelectionResult? {
        // Generic fallback for unknown applications
        #if DEBUG
        DevLogger.shared.info("[TEXT_SELECTION] Using generic fallback strategy for \(appName)", context: "TextSelectionService")
        #endif
        return nil // Placeholder for generic implementation
    }
    
    private func getCurrentApplicationName() -> String {
        let workspace = NSWorkspace.shared
        if let frontApp = workspace.frontmostApplication {
            return frontApp.localizedName ?? "Unknown"
        }
        return "Unknown"
    }
    
    private func validateSelection(_ selectedText: String, in containingText: String) -> Double {
        // Basic validation - check if selected text is actually contained in the full text
        if containingText.contains(selectedText) {
            return 0.9
        } else if selectedText.count > 0 {
            return 0.5 // Has selection but might not be perfectly extracted
        }
        return 0.0
    }
} 