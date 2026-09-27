import AppKit

private struct WeakDetachedRootsObserver {
    weak var value: AgentTaskResultDetachedRootsObserver?
    init(_ value: AgentTaskResultDetachedRootsObserver) { self.value = value }
}

@MainActor
final class DetachedAgentTaskWindowManager {
    static let shared = DetachedAgentTaskWindowManager()

    private var controllers: [String: DetachedAgentTaskWindowController] = [:]
    private var observers: [ObjectIdentifier: WeakDetachedRootsObserver] = [:]

    var detachedRootTaskIds: [String] {
        Array(controllers.keys)
    }

    func addObserver(_ observer: AgentTaskResultDetachedRootsObserver) {
        observers[ObjectIdentifier(observer)] = WeakDetachedRootsObserver(observer)
    }

    func removeObserver(_ observer: AgentTaskResultDetachedRootsObserver) {
        observers.removeValue(forKey: ObjectIdentifier(observer))
    }

    func open(rootTaskId: String, originatingWindow: NSWindow? = nil) {
        guard !rootTaskId.isEmpty else { return }
        if let controller = controllers[rootTaskId] {
            controller.bringToFront()
            broadcastDetachedRoots()
            return
        }

        let fallbackVisibleFrame = NSScreen.main?.visibleFrame
            ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let sourceFrame = originatingWindow?.frame
            ?? NSRect(
                x: fallbackVisibleFrame.midX - 280,
                y: fallbackVisibleFrame.midY - 200,
                width: 560,
                height: 400
            )
        let visibleFrame = DetachedAgentTaskWindowPlacement.resolvedVisibleFrame(
            originatingScreenVisibleFrame: originatingWindow?.screen?.visibleFrame,
            sourceFrame: sourceFrame,
            screenVisibleFrames: NSScreen.screens.map(\.visibleFrame),
            fallbackVisibleFrame: fallbackVisibleFrame
        )
        let initialFrame = DetachedAgentTaskWindowPlacement.frame(
            windowSize: NSSize(width: 560, height: 400),
            sourceFrame: sourceFrame,
            visibleFrame: visibleFrame,
            occupiedFrames: controllers.values.compactMap(\.placementFrame)
        )

        let controller = DetachedAgentTaskWindowController(
            rootTaskId: rootTaskId,
            initialFrame: initialFrame
        ) { [weak self] closedRootTaskId in
            self?.controllers.removeValue(forKey: closedRootTaskId)
            self?.broadcastDetachedRoots()
        }
        controllers[rootTaskId] = controller
        controller.show()
        broadcastDetachedRoots()
    }

    func close(rootTaskId: String) {
        controllers[rootTaskId]?.close()
    }

    func requestValidationRunState(rootTaskId: String, requestId: String) {
        controllers[rootTaskId]?.requestValidationRunState(requestId: requestId)
    }

    func focusValidationRun(rootTaskId: String, requestId: String, runId: String) {
        controllers[rootTaskId]?.focusValidationRun(requestId: requestId, runId: runId)
    }

    private func broadcastDetachedRoots() {
        AgentTaskResultWidgetController.shared?.updateDetachedRoots(detachedRootTaskIds)
        for (id, box) in observers {
            guard let observer = box.value else {
                observers.removeValue(forKey: id)
                continue
            }
            observer.updateDetachedRoots(detachedRootTaskIds)
        }
    }
}
