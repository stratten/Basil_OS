import Foundation

/// Conformed by every live Agent Task Result surface
/// (`AgentTaskResultWidgetController`, `AgentTaskResultEmbeddedHost`) so
/// `DetachedAgentTaskWindowManager` can push detached-root-id changes to
/// whichever surfaces currently exist, instead of a single hardcoded
/// `AgentTaskResultWidgetController.shared` reference.
@MainActor
protocol AgentTaskResultDetachedRootsObserver: AnyObject {
    func updateDetachedRoots(_ ids: [String])
}
