import SwiftUI

/// A text field style with a clearly visible border, used for the meeting
/// information entry fields. The system `RoundedBorderTextFieldStyle` bezel is
/// too faint to read on bright external displays, so this draws an explicit
/// rounded outline using `AestheticSystem.Colors.fieldBorder`.
struct BasilBorderedTextFieldStyle: TextFieldStyle {
    func _body(configuration: TextField<Self._Label>) -> some View {
        configuration
            .textFieldStyle(.plain)
            .padding(.horizontal, AestheticSystem.Layout.paddingS)
            .padding(.vertical, 5)
            .background(AestheticSystem.Colors.backgroundTertiary)
            .clipShape(RoundedRectangle(cornerRadius: AestheticSystem.Layout.cornerRadiusSmall))
            .overlay(
                RoundedRectangle(cornerRadius: AestheticSystem.Layout.cornerRadiusSmall)
                    .stroke(AestheticSystem.Colors.fieldBorder, lineWidth: 1)
            )
    }
}
