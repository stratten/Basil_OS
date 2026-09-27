import SwiftUI
import Combine
import Foundation
import AppKit

// MARK: - Utilities: Helper Functions
extension AssistantSessionViewModel {
    
    // MARK: - Thinking Content Extraction

    /// Extracts thinking content from response text and returns both
    /// thinking and actual content.
    ///
    /// - Parameter rawText: The raw response text potentially containing
    ///   `<think>...</think>` tags.
    /// - Returns: A tuple `(thinking, content)` where `thinking` is `nil`
    ///   if no think tags were present (or contained only whitespace).
    ///
    /// This is now a thin wrapper around `ThinkingExtractor.split` so
    /// that the live streaming view model and the persisted-history
    /// renderers (sidebar preview, history detail, refinement entries,
    /// clipboard copy) all parse `<think>` blocks identically. Keeping
    /// the instance-method signature here avoids churning the only
    /// caller (`performAssistantSessionUpdate`) and any future view-model code
    /// that already expects this shape.
    func extractThinkingContent(from rawText: String) -> (thinking: String?, content: String) {
        ThinkingExtractor.split(rawText)
    }
    
    // MARK: - Pasting Helpers

    /// Paste plain-text AssistantSession output to the active application.
    func pasteAssistantSession(_ text: String) {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)

        // Simulate Command-V
        let source = CGEventSource(stateID: .hidSystemState)
        let keyDown = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: true) // 9 is 'v'
        keyDown?.flags = .maskCommand
        let keyUp = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: false)
        keyUp?.flags = .maskCommand

        keyDown?.post(tap: .cgAnnotatedSessionEventTap)
        keyUp?.post(tap: .cgAnnotatedSessionEventTap)
        #if DEBUG
        DevLogger.shared.info("Pasted AssistantSession text to active application.", context: "AssistantSessionViewModel")
        #endif
    }

    /// Paste rich-formatted AssistantSession output (markdown to RTF) to the active application.
    func pasteRichAssistantSession(_ markdown: String) {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        
        // Convert markdown to attributed string with minimal font specifications
        let attributedString = MarkdownUtils.markdownToAttributedString(markdown)
        
        // Add plain text for compatibility
        pasteboard.setString(attributedString.string, forType: .string)
        
        // Add RTF data with minimal font specifications (traits only, no explicit fonts)
        // This should allow target apps to use their own fonts while preserving bold/italic
        if let rtfData = attributedString.rtf(from: NSRange(location: 0, length: attributedString.length), documentAttributes: [:]) {
            pasteboard.setData(rtfData, forType: .rtf)
        }

        // Simulate Command-Shift-V (Paste and Match Style)
        // This preserves formatting like bold/bullets while matching destination font
        let source = CGEventSource(stateID: .hidSystemState)
        let keyDown = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: true) // 9 is 'v'
        keyDown?.flags = [.maskCommand, .maskShift]
        let keyUp = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: false)
        keyUp?.flags = [.maskCommand, .maskShift]

        keyDown?.post(tap: .cgAnnotatedSessionEventTap)
        keyUp?.post(tap: .cgAnnotatedSessionEventTap)
        #if DEBUG
        DevLogger.shared.info("Pasted AssistantSession with 'Paste and Match Style' (Cmd+Shift+V).", context: "AssistantSessionViewModel")
        #endif
    }

    // MARK: - Throttled AssistantSession Output Updates

    /// Updates AssistantSession output with throttling to prevent UI lag during streaming.
    @MainActor
    func updateAssistantSessionThrottled(_ newOutput: String) {
        let now = Date()
        let timeSinceLastUpdate = now.timeIntervalSince(lastAssistantSessionUpdateTime)

        // Store the pending update
        pendingAssistantSessionUpdate = newOutput

        // If enough time has passed, update immediately
        if timeSinceLastUpdate >= assistantSessionUpdateThrottleInterval {
            performAssistantSessionUpdate(newOutput)
        } else if assistantSessionUpdateTask == nil {
            // Schedule a throttled update
            let delay = assistantSessionUpdateThrottleInterval - timeSinceLastUpdate
            assistantSessionUpdateTask = Task { @MainActor in
                try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
                if let pending = self.pendingAssistantSessionUpdate {
                    self.performAssistantSessionUpdate(pending)
                }
                self.assistantSessionUpdateTask = nil
            }
        }
    }

    @MainActor
    private func performAssistantSessionUpdate(_ newOutput: String) {
        let (thinking, content) = extractThinkingContent(from: newOutput)
        thinkingContent = thinking
        assistantOutput = content
        lastAssistantSessionUpdateTime = Date()
        pendingAssistantSessionUpdate = nil
    }
}
