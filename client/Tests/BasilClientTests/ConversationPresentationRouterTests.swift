import XCTest
@testable import BasilClient

@MainActor
final class ConversationPresentationRouterTests: XCTestCase {
    func testStandaloneRemainsAuthoritativeOverDetachedThread() {
        XCTAssertEqual(
            ConversationPresentationRouter.destination(
                presenter: .standalone,
                hasDetachedThread: true
            ),
            .standalone
        )
    }

    func testBoardRemainsAuthoritativeOverDetachedThread() {
        XCTAssertEqual(
            ConversationPresentationRouter.destination(
                presenter: .board,
                hasDetachedThread: true
            ),
            .board
        )
    }

    func testExistingDetachedThreadIsFocusedWhenNoCanonicalSurfaceIsVisible() {
        XCTAssertEqual(
            ConversationPresentationRouter.destination(
                presenter: nil,
                hasDetachedThread: true
            ),
            .detached
        )
    }

    func testGlobalStandaloneIsOpenedWhenNoConversationSurfaceExists() {
        XCTAssertEqual(
            ConversationPresentationRouter.destination(
                presenter: nil,
                hasDetachedThread: false
            ),
            .standalone
        )
    }

    func testRejectsBlankConversationIdentifier() {
        XCTAssertFalse(
            ConversationPresentationRouter.showConversation(
                conversationId: "   "
            )
        )
    }
}
