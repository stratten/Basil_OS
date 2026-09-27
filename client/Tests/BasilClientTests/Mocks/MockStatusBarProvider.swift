import AppKit
@testable import BasilClient

@MainActor
final class MockStatusBarProvider: StatusBarItemProvider {
    nonisolated(unsafe) private(set) var createItemCallCount = 0
    nonisolated(unsafe) private(set) var removeItemCallCount = 0
    nonisolated(unsafe) private(set) var lastCreatedItem: NSStatusItem?
    nonisolated(unsafe) private(set) var lastRemovedItem: NSStatusItem?
    
    nonisolated func createStatusItem(withLength length: CGFloat) -> NSStatusItem {
        createItemCallCount += 1
        let item = NSStatusItem()
        lastCreatedItem = item
        return item
    }
    
    nonisolated func removeStatusItem(_ item: NSStatusItem) {
        removeItemCallCount += 1
        lastRemovedItem = item
    }
} 