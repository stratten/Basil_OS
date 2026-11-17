import Foundation

/// What `SettingsShellWindowController.show()` must do with the Settings web content.
///
/// Reloading the page throws away the tab, sub-tab, scroll position and any half-typed field, so it is done only when the page was just built. A window that is already open (visible, minimized, or on another Space) keeps its content, and a pending navigation request is sent straight to it once the page has reported ready.
enum SettingsShellShowPlan: Equatable {
    /// No live window. Build it and load the page. The first ready event sends any pending navigation.
    case buildAndLoad
    /// The window exists and its page is ready. Bring it forward and send any pending navigation directly. Never reload.
    case reuseLoadedPage
    /// The window exists but its page is still loading. Bring it forward only. The ready event that is already coming sends any pending navigation.
    case reuseLoadingPage

    static func resolve(hasLiveWindow: Bool, pageIsReady: Bool) -> SettingsShellShowPlan {
        guard hasLiveWindow else { return .buildAndLoad }
        return pageIsReady ? .reuseLoadedPage : .reuseLoadingPage
    }
}
