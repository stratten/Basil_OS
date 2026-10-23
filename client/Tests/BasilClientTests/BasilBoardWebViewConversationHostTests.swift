import XCTest
@testable import BasilClient

@MainActor
final class BasilBoardWebViewConversationHostTests: XCTestCase {
    func testDefaultEntryPageIsBasilBoard() {
        let webView = BasilBoardWebView()
        XCTAssertEqual(webView.entryPage.htmlRelativePath, "src/entries/basil-board.html")
    }

    func testConversationEntryPageLoadsTheConversationHtml() {
        let webView = BasilBoardWebView(entryPage: .conversation)
        XCTAssertEqual(webView.entryPage.htmlRelativePath, "src/entries/conversation.html")
    }

    func testConversationHostsExposeDetachedThreadsObserverIdentity() {
        let boardHost = BasilBoardWebView()
        let globalConversationHost = BasilBoardWebView(entryPage: .conversation)
        let detachedThreadHost = BasilBoardWebView(
            entryPage: .conversation,
            conversationPresentation: .thread
        )
        let boardObserver: any ConversationDetachedThreadsObserver = boardHost
        let globalConversationObserver: any ConversationDetachedThreadsObserver = globalConversationHost
        let detachedThreadObserver: any ConversationDetachedThreadsObserver = detachedThreadHost

        XCTAssertTrue((boardObserver as AnyObject) === boardHost)
        XCTAssertTrue((globalConversationObserver as AnyObject) === globalConversationHost)
        XCTAssertTrue((detachedThreadObserver as AnyObject) === detachedThreadHost)
    }

    func testRequestWindowCollapseInvokesCallback() {
        let webView = BasilBoardWebView(entryPage: .conversation)
        var collapsed = false
        webView.onCollapseRequested = { collapsed = true }

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "requestWindowCollapse"])

        XCTAssertTrue(collapsed)
    }

    func testRequestWindowExpandInvokesCallback() {
        let webView = BasilBoardWebView(entryPage: .conversation)
        var expanded = false
        webView.onExpandRequested = { expanded = true }

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "requestWindowExpand"])

        XCTAssertTrue(expanded)
    }
}
