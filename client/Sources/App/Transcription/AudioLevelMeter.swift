import SwiftUI

@MainActor
struct AudioLevelMeter: View {
    let level: Float

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                Rectangle().fill(AestheticSystem.Colors.textTertiary.opacity(0.1))
                Rectangle()
                    .fill(
                        LinearGradient(
                            gradient: Gradient(colors: [
                                AestheticSystem.Colors.secondary.opacity(0.5),
                                AestheticSystem.Colors.secondary
                            ]),
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                    .frame(width: geometry.size.width * CGFloat(level))
                    .animation(.easeOut(duration: 0.12), value: level)
            }
            .clipShape(RoundedRectangle(cornerRadius: AestheticSystem.Layout.cornerRadiusSmall))
            .overlay(
                RoundedRectangle(cornerRadius: AestheticSystem.Layout.cornerRadiusSmall)
                    .stroke(AestheticSystem.Colors.secondary.opacity(0.3), lineWidth: AestheticSystem.Layout.borderThin)
            )
        }
    }
}
