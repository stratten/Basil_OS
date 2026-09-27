import SwiftUI

/// The third header control (next to close + dock-minimize) that collapses a
/// floating window upward to its header strip and expands it back. Styled to
/// match the existing palette circle icons used for close and minimize so it
/// reads as part of the same control cluster.
struct WindowCollapseToggleButton: View {
    let isCollapsed: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            // The arrow reflects the current state, not the action: collapsed
            // points right (content is tucked away), expanded points down
            // (content is revealed below).
            Image(systemName: isCollapsed ? "chevron.right.circle.fill" : "chevron.down.circle.fill")
                .symbolRenderingMode(.palette)
                .foregroundStyle(AestheticSystem.Colors.secondary, AestheticSystem.Colors.primary.opacity(0.15))
                .font(.title2)
        }
        .buttonStyle(.plain)
        .help(isCollapsed ? "Expand" : "Collapse")
    }
}
