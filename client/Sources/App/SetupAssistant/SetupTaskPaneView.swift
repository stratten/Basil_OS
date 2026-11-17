import AppKit

/// The card that sits to the right of the setup flow while a task launched from setup is on screen. It has a native title bar (which also drags the window, like the setup flow's own header) with a Close button, and a body view the embedded task web view fills.
@MainActor
final class SetupTaskPaneView: NSView {
    static let barHeight: CGFloat = SetupWindowDragAreaInstaller.headerHeight

    /// The embedded task view is installed into this view.
    let bodyView = NSView()
    var onCloseRequested: (() -> Void)?

    private let titleLabel = NSTextField(labelWithString: "Task from setup")
    private let closeButton = NSButton(title: "Close task pane", target: nil, action: nil)

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        configure()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    private func configure() {
        wantsLayer = true
        layer?.backgroundColor = NSColor.white.cgColor
        layer?.cornerRadius = WebKitWindowChromeAppearance.cornerRadius
        layer?.masksToBounds = true
        layer?.borderWidth = 1.5
        layer?.borderColor = NSColor.systemBlue.cgColor

        let dragArea = WindowDragAreaView(leadingInteractiveWidth: 0, trailingInteractiveWidth: 150)
        titleLabel.font = .systemFont(ofSize: 13, weight: .semibold)
        titleLabel.textColor = .black
        titleLabel.lineBreakMode = .byTruncatingTail
        closeButton.bezelStyle = .rounded
        closeButton.controlSize = .small
        closeButton.target = self
        closeButton.action = #selector(closeTapped)
        closeButton.setAccessibilityLabel("Close task pane")

        for view in [dragArea, titleLabel, closeButton, bodyView] {
            view.translatesAutoresizingMaskIntoConstraints = false
            addSubview(view)
        }
        // The drag area is added first, so the title label and button sit above it and the button stays clickable.

        NSLayoutConstraint.activate([
            dragArea.topAnchor.constraint(equalTo: topAnchor),
            dragArea.leadingAnchor.constraint(equalTo: leadingAnchor),
            dragArea.trailingAnchor.constraint(equalTo: trailingAnchor),
            dragArea.heightAnchor.constraint(equalToConstant: Self.barHeight),

            titleLabel.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 16),
            titleLabel.centerYAnchor.constraint(equalTo: topAnchor, constant: Self.barHeight / 2),
            titleLabel.trailingAnchor.constraint(lessThanOrEqualTo: closeButton.leadingAnchor, constant: -8),

            closeButton.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),
            closeButton.centerYAnchor.constraint(equalTo: topAnchor, constant: Self.barHeight / 2),

            bodyView.topAnchor.constraint(equalTo: topAnchor, constant: Self.barHeight),
            bodyView.leadingAnchor.constraint(equalTo: leadingAnchor),
            bodyView.trailingAnchor.constraint(equalTo: trailingAnchor),
            bodyView.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])
    }

    @objc private func closeTapped() {
        onCloseRequested?()
    }
}
