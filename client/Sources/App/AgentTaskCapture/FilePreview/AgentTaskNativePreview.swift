import AppKit
import Darwin
import PDFKit

struct AgentTaskNativePreviewFrame: Equatable {
    let x: CGFloat
    let y: CGFloat
    let width: CGFloat
    let height: CGFloat

    init(x: CGFloat, y: CGFloat, width: CGFloat, height: CGFloat) {
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    }

    func clipped(to bounds: NSRect) -> NSRect? {
        guard width > 0, height > 0 else { return nil }
        let clipped = NSRect(x: x, y: y, width: width, height: height).intersection(bounds)
        guard clipped.width > 0, clipped.height > 0 else { return nil }
        return clipped
    }
}

enum AgentTaskNativePreviewGeometry {
    static func filePreviewWindowFrame(
        hostBounds: NSRect,
        chromeHeight: CGFloat,
        inset: CGFloat,
        hostIsFlipped: Bool
    ) -> AgentTaskNativePreviewFrame? {
        let width = hostBounds.width - (inset * 2)
        let height = hostBounds.height - chromeHeight - inset
        guard width > 0, height > 0 else { return nil }

        return AgentTaskNativePreviewFrame(
            x: inset,
            y: hostIsFlipped ? chromeHeight : inset,
            width: width,
            height: height
        )
    }

    static func convertInlinePreviewFrame(
        left: CGFloat,
        top: CGFloat,
        width: CGFloat,
        height: CGFloat,
        viewportWidth: CGFloat,
        viewportHeight: CGFloat,
        hostBounds: NSRect,
        hostIsFlipped: Bool
    ) -> AgentTaskNativePreviewFrame? {
        guard left.isFinite,
              top.isFinite,
              width.isFinite,
              height.isFinite,
              viewportWidth.isFinite,
              viewportHeight.isFinite,
              width > 0,
              height > 0,
              viewportWidth > 0,
              viewportHeight > 0,
              viewportWidth <= hostBounds.width,
              viewportHeight <= hostBounds.height else {
            return nil
        }

        let horizontalScale = hostBounds.width / viewportWidth
        let verticalScale = hostBounds.height / viewportHeight
        guard horizontalScale.isFinite,
              verticalScale.isFinite,
              horizontalScale > 0,
              verticalScale > 0 else {
            return nil
        }

        return AgentTaskNativePreviewFrame(
            x: left * horizontalScale,
            y: hostIsFlipped
                ? top * verticalScale
                : hostBounds.height - ((top + height) * verticalScale),
            width: width * horizontalScale,
            height: height * verticalScale
        )
    }
}

struct AgentTaskPreviewFileRevision: Equatable {
    let modificationDate: Date
    let fileSize: UInt64

    init?(url: URL) {
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
              let modificationDate = attributes[.modificationDate] as? Date,
              let fileSize = (attributes[.size] as? NSNumber)?.uint64Value else {
            return nil
        }

        self.modificationDate = modificationDate
        self.fileSize = fileSize
    }
}

final class AgentTaskPreviewFileObserver {
    private var source: DispatchSourceFileSystemObject?

    init?(url: URL, onChange: @escaping @MainActor @Sendable () -> Void) {
        let directoryURL = url.deletingLastPathComponent()
        let fileDescriptor = open(directoryURL.path, O_EVTONLY)
        guard fileDescriptor >= 0 else { return nil }

        let source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: fileDescriptor,
            eventMask: [.write, .rename, .delete],
            queue: DispatchQueue.global(qos: .utility)
        )
        source.setEventHandler {
            DispatchQueue.main.async {
                Task { @MainActor in
                    onChange()
                }
            }
        }
        source.setCancelHandler {
            close(fileDescriptor)
        }
        self.source = source
        source.resume()
    }

    func invalidate() {
        source?.cancel()
        source = nil
    }
}

@MainActor
final class AgentTaskNativePreviewOverlay {
    private weak var hostView: NSView?
    private var mountedView: NSView?

    init(hostView: NSView) {
        self.hostView = hostView
    }

    var currentView: NSView? {
        mountedView
    }

    func present(_ previewView: NSView, frame: AgentTaskNativePreviewFrame) {
        guard let hostView, let clippedFrame = frame.clipped(to: hostView.bounds) else {
            update(frame: frame)
            return
        }

        if mountedView !== previewView {
            removeMountedView()
            previewView.translatesAutoresizingMaskIntoConstraints = true
            hostView.addSubview(previewView)
            mountedView = previewView
        }

        mountedView?.frame = clippedFrame
        mountedView?.isHidden = false
    }

    func update(frame: AgentTaskNativePreviewFrame) {
        guard let hostView, let mountedView else { return }
        guard let clippedFrame = frame.clipped(to: hostView.bounds) else {
            mountedView.isHidden = true
            return
        }
        mountedView.frame = clippedFrame
        mountedView.isHidden = false
    }

    func hide() {
        removeMountedView()
    }

    func replaceDocument(_ document: PDFDocument) {
        guard let pdfView = mountedView as? PDFView else { return }
        let currentPageIndex = pdfView.currentPage.flatMap { pdfView.document?.index(for: $0) }
        pdfView.document = document
        if let currentPageIndex,
           currentPageIndex >= 0,
           currentPageIndex < document.pageCount,
           let page = document.page(at: currentPageIndex) {
            pdfView.go(to: page)
        }
    }

    private func removeMountedView() {
        guard let mountedView else { return }
        if let pdfView = mountedView as? PDFView {
            pdfView.document = nil
        }
        mountedView.removeFromSuperview()
        self.mountedView = nil
    }
}

enum AgentTaskNativePDFPreview {
    static func loadDocument(at url: URL) -> PDFDocument? {
        PDFDocument(url: url)
    }

    @MainActor
    static func makeView(document: PDFDocument, cornerRadius: CGFloat = 0) -> PDFView {
        let view = PDFView()
        view.autoScales = true
        view.displayMode = .singlePageContinuous
        view.displayDirection = .vertical
        view.backgroundColor = .clear
        view.wantsLayer = true
        view.layer?.cornerRadius = cornerRadius
        view.layer?.masksToBounds = cornerRadius > 0
        view.document = document
        return view
    }
}
