import XCTest
import AppKit
@testable import BasilClient

/// Mock status bar implementation for testing
@MainActor
final class MockStatusBarManager: StatusBarServiceProtocol {
    var isEnabled: Bool = false
    var currentIcon: NSImage?
    var currentTitle: String?
    var isActiveState: Bool = false
    var enableCallCount = 0
    var disableCallCount = 0
    var updateIconCallCount = 0
    var updateTitleCallCount = 0
    var setActiveCallCount = 0
    
    func enableStatusItem() {
        isEnabled = true
        enableCallCount += 1
    }
    
    func disableStatusItem() {
        isEnabled = false
        currentIcon = nil
        currentTitle = nil
        disableCallCount += 1
    }
    
    func updateIcon(_ icon: NSImage) {
        currentIcon = icon
        updateIconCallCount += 1
    }
    
    func updateTitle(_ title: String) {
        currentTitle = title
        updateTitleCallCount += 1
    }
    
    func setActive(_ active: Bool) {
        isActiveState = active
        setActiveCallCount += 1
    }
}

@MainActor
final class StatusBarManagerTests: XCTestCase {
    var sut: StatusBarManager!
    var mockProvider: MockStatusBarProvider!
    
    @MainActor
    override func setUp() {
        super.setUp()
        mockProvider = MockStatusBarProvider()
        sut = StatusBarManager(statusBarProvider: mockProvider)
    }
    
    @MainActor
    override func tearDown() async throws {
        await sut.disableStatusItem()
        sut = nil
        mockProvider = nil
        try await super.tearDown()
    }
    
    // MARK: - Initialization Tests
    
    @MainActor
    func testInitialState() async {
        // When initialized, status bar should be enabled
        let isEnabled = await sut.isEnabled
        XCTAssertTrue(isEnabled)
        XCTAssertEqual(mockProvider.createItemCallCount, 1)
    }
    
    // MARK: - Enable/Disable Tests
    
    @MainActor
    func testDisableStatusItem() async {
        // Given
        let initialEnabled = await sut.isEnabled
        XCTAssertTrue(initialEnabled)
        let createdItem = mockProvider.lastCreatedItem
        XCTAssertNotNil(createdItem)
        
        // When
        await sut.disableStatusItem()
        
        // Then
        let finalEnabled = await sut.isEnabled
        XCTAssertFalse(finalEnabled)
        XCTAssertEqual(mockProvider.removeItemCallCount, 1)
        XCTAssertEqual(mockProvider.lastRemovedItem, createdItem)
    }
    
    @MainActor
    func testReenableStatusItem() async {
        // Given
        await sut.disableStatusItem()
        let initialEnabled = await sut.isEnabled
        XCTAssertFalse(initialEnabled)
        let initialCreateCount = mockProvider.createItemCallCount
        
        // When
        await sut.enableStatusItem()
        
        // Then
        let finalEnabled = await sut.isEnabled
        XCTAssertTrue(finalEnabled)
        XCTAssertEqual(mockProvider.createItemCallCount, initialCreateCount + 1)
    }
    
    // MARK: - Icon Tests
    
    @MainActor
    func testUpdateIcon() async {
        // Given
        let testIcon = NSImage()
        
        // When
        sut.updateIcon(testIcon)
        
        // Then
        let isEnabled = await sut.isEnabled
        XCTAssertTrue(isEnabled)
        XCTAssertEqual(mockProvider.createItemCallCount, 1)
    }
    
    @MainActor
    func testUpdateIconWithPlaceholder() async {
        // Given
        let testIcon = NSImage()
        sut.updateIcon(testIcon)
        
        // When - Update with a different icon
        let newIcon = NSImage()
        sut.updateIcon(newIcon)
        
        // Then
        let isEnabled = await sut.isEnabled
        XCTAssertTrue(isEnabled)
    }

    @MainActor
    func testDisablingActivityCaptureClearsItsStatusBarState() {
        sut.isActivityCaptureEnabled = true
        sut.isActivityCaptureActive = true

        sut.updateActivityCaptureEnabledState(false)

        XCTAssertFalse(sut.isActivityCaptureEnabled)
        XCTAssertFalse(sut.isActivityCaptureActive)
        XCTAssertEqual(sut.statusBarItem.currentIconResourceName(), "StatusBarIcon_TN_MN_BN")
    }
    
    // MARK: - Title Tests
    
    @MainActor
    func testUpdateTitle() async {
        // Given
        let testTitle = "Test Title"
        
        // When
        sut.updateTitle(testTitle)
        
        // Then
        let isEnabled = await sut.isEnabled
        XCTAssertTrue(isEnabled)
    }
    
    @MainActor
    func testUpdateTitleWithEmptyString() async {
        // Given
        sut.updateTitle("Previous Title")
        
        // When
        sut.updateTitle("")
        
        // Then
        let isEnabled = await sut.isEnabled
        XCTAssertTrue(isEnabled)
    }
    
    // MARK: - Active State Tests
    
    @MainActor
    func testSetActive() {
        // Given
        let initialCreateCount = mockProvider.createItemCallCount
        
        // When
        sut.setActive(true)
        
        // Then
        XCTAssertEqual(mockProvider.createItemCallCount, initialCreateCount)
    }
    
    @MainActor
    func testToggleActiveState() {
        // Given
        sut.setActive(true)
        let createCount = mockProvider.createItemCallCount
        
        // When
        sut.setActive(false)
        
        // Then
        XCTAssertEqual(mockProvider.createItemCallCount, createCount)
    }
    
    // MARK: - Integration Tests
    
    @MainActor
    func testFullLifecycle() async {
        // Given
        let testIcon = NSImage()
        let testTitle = "Test Title"
        let initialCreateCount = mockProvider.createItemCallCount
        
        // When - Enable and configure
        sut.updateIcon(testIcon)
        sut.updateTitle(testTitle)
        sut.setActive(true)
        
        // Then - Verify state
        let isEnabled = await sut.isEnabled
        XCTAssertTrue(isEnabled)
        XCTAssertEqual(mockProvider.createItemCallCount, initialCreateCount)
        
        // When - Disable
        await sut.disableStatusItem()
        
        // Then - Verify cleaned up state
        let finalEnabled = await sut.isEnabled
        XCTAssertFalse(finalEnabled)
        XCTAssertEqual(mockProvider.removeItemCallCount, 1)
    }

    func testStatusMenuOmitsLegacyComparisonItemsAndKeepsCanonicalMeetingEntry() {
        let menu = StatusBarMenuBuilder.buildMenu(hotkeyService: sut.hotkeyService, target: sut)

        XCTAssertNil(
            menu.items.first { $0.title == "Open Legacy SwiftUI Conversation Comparison" }
        )
        XCTAssertNil(
            menu.items.first { $0.title == "Meeting / Call Transcription (Legacy QA)" }
        )
        XCTAssertNotNil(
            menu.items.first { $0.title == "Notetaker (Meeting / Call Assistant)" }
        )
    }
} 