import SwiftUI

/// Drop-in toolbar that wires up to a `RichTextEditorController` and renders the
/// active state from a `RichTextFormattingState`. Consumers can use this directly
/// or build their own toolbar around the same controller -- the controller is the contract.
struct RichTextEditorToolbar: View {
    @ObservedObject var controller: RichTextEditorController
    let formattingState: RichTextFormattingState
    var disabled: Bool = false

    var body: some View {
        HStack(spacing: 2) {
            ToolbarTextButton(label: "B", weight: .bold, isActive: formattingState.isBold, help: "Bold (Cmd+B)") {
                controller.toggleBold()
            }
            ToolbarTextButton(label: "I", weight: .regular, italic: true, isActive: formattingState.isItalic, help: "Italic (Cmd+I)") {
                controller.toggleItalic()
            }
            ToolbarTextButton(label: "U", weight: .regular, underline: true, isActive: formattingState.isUnderline, help: "Underline (Cmd+U)") {
                controller.toggleUnderline()
            }

            divider

            ToolbarSymbolButton(systemName: "chevron.left.forwardslash.chevron.right", isActive: formattingState.isInlineCode, help: "Inline code") {
                controller.toggleInlineCode()
            }
            ToolbarSymbolButton(systemName: "curlybraces", isActive: formattingState.isCodeBlock, help: "Code block") {
                controller.toggleCodeBlock()
            }

            divider

            ToolbarSymbolButton(systemName: "list.bullet", isActive: formattingState.isBulletList, help: "Bullet list") {
                controller.toggleBulletList()
            }
            ToolbarSymbolButton(systemName: "list.number", isActive: formattingState.isNumberedList, help: "Numbered list") {
                controller.toggleNumberedList()
            }
        }
        .disabled(disabled)
        .opacity(disabled ? 0.4 : 1.0)
    }

    private var divider: some View {
        Rectangle()
            .fill(AestheticSystem.Colors.separatorColor)
            .frame(width: 1, height: 12)
            .padding(.horizontal, 2)
    }
}

private struct ToolbarTextButton: View {
    let label: String
    var weight: Font.Weight = .regular
    var italic: Bool = false
    var underline: Bool = false
    let isActive: Bool
    let help: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            styledLabel
                .foregroundColor(isActive ? AestheticSystem.Colors.primary : AestheticSystem.Colors.textSecondary)
                .frame(width: 18, height: 18)
                .background(
                    RoundedRectangle(cornerRadius: 4)
                        .fill(isActive ? AestheticSystem.Colors.primary.opacity(0.12) : Color.clear)
                )
        }
        .buttonStyle(PlainButtonStyle())
        .help(help)
    }

    private var styledLabel: Text {
        var text = Text(label).font(.system(size: 11, weight: weight))
        if italic { text = text.italic() }
        if underline { text = text.underline() }
        return text
    }
}

private struct ToolbarSymbolButton: View {
    let systemName: String
    let isActive: Bool
    let help: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 10, weight: .medium))
                .foregroundColor(isActive ? AestheticSystem.Colors.primary : AestheticSystem.Colors.textSecondary)
                .frame(width: 18, height: 18)
                .background(
                    RoundedRectangle(cornerRadius: 4)
                        .fill(isActive ? AestheticSystem.Colors.primary.opacity(0.12) : Color.clear)
                )
        }
        .buttonStyle(PlainButtonStyle())
        .help(help)
    }
}
