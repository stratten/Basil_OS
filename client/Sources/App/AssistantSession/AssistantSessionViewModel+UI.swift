import SwiftUI
import Combine
import Foundation

// MARK: - UI: Sizing and Layout Management
extension AssistantSessionViewModel {
    
    // MARK: - Ideal Size Calculation
    
    /// Calculate ideal sizes based on actual content
    /// - Parameter shouldPersist: If true, calculate size for persistent display; if false, reset to compact initial size
    @MainActor
    func updateIdealSizes(shouldPersist: Bool) {
        if shouldPersist {
            // Calculate size based on content length
            let contentLength = assistantOutput.count
            let estimatedLines = max(3, min(35, contentLength / 60)) // Rough estimate: 60 chars per line, up to ~35 lines
            
            // Dynamic height based on content
            let baseTextHeight: CGFloat = 80  // Base for chrome (header, buttons, padding)
            let lineHeight: CGFloat = 20      // Approximate height per line
            let calculatedTextHeight = baseTextHeight + (CGFloat(estimatedLines) * lineHeight)
            
            // Clamp to reasonable bounds - generous max to accommodate longer content
            self.currentIdealTextHeight = min(700, max(120, calculatedTextHeight))
            
            // Widget dimensions with some padding
            let chromeHeight: CGFloat = 150 // Header + buttons + padding
            self.currentIdealWidgetWidth = 520  // Comfortable reading width
            self.currentIdealWidgetHeight = min(900, max(250, self.currentIdealTextHeight + chromeHeight))
            self.expandedResultWidgetWidth = self.currentIdealWidgetWidth
            self.expandedResultWidgetHeight = self.currentIdealWidgetHeight
            
            if isResultChromeCollapsed {
                publishCollapsedResultChromeSize()
            } else {
                // Throttled publish to prevent UI thrashing
                scheduleThrottledSizeUpdate()
            }
        } else {
            // Reset to compact initial size
            self.isResultChromeCollapsed = false
            self.currentIdealTextHeight = 100
            self.currentIdealWidgetWidth = 450
            self.currentIdealWidgetHeight = 220
            
            // Immediate update for closing
            idealSizeUpdateRequest.send((width: currentIdealWidgetWidth, height: currentIdealWidgetHeight))
        }
    }
    
    // MARK: - Throttled Size Updates
    
    @MainActor
    func scheduleThrottledSizeUpdate() {
        let now = Date()
        let timeSinceLastUpdate = now.timeIntervalSince(lastSizeUpdateTime)
        
        pendingSizeUpdate = true
        
        // If enough time has passed, update immediately
        if timeSinceLastUpdate >= sizeUpdateThrottleInterval {
            performSizeUpdate()
        } else if sizeUpdateTask == nil {
            // Schedule a throttled update
            let delay = sizeUpdateThrottleInterval - timeSinceLastUpdate
            sizeUpdateTask = Task { @MainActor in
                try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
                if self.pendingSizeUpdate {
                    self.performSizeUpdate()
                }
                self.sizeUpdateTask = nil
            }
        }
    }
    
    @MainActor
    private func performSizeUpdate() {
        if isResultChromeCollapsed {
            publishCollapsedResultChromeSize()
        } else {
            idealSizeUpdateRequest.send((width: currentIdealWidgetWidth, height: currentIdealWidgetHeight))
        }
        lastSizeUpdateTime = Date()
        pendingSizeUpdate = false
    }

    @MainActor
    func setResultChromeCollapsed(_ collapsed: Bool) {
        isResultChromeCollapsed = collapsed
        if collapsed {
            publishCollapsedResultChromeSize()
        } else {
            idealSizeUpdateRequest.send((width: expandedResultWidgetWidth, height: expandedResultWidgetHeight))
        }
    }

    @MainActor
    private func publishCollapsedResultChromeSize() {
        idealSizeUpdateRequest.send((width: 260, height: 87))
    }
}

