import SwiftUI

/// Shared bullet point styles for onboarding capability introduction screens.
/// Provides consistent visual styling across all capability introductions.
struct OnboardingBulletStyles {
    
    /// Standard bullet point for all onboarding content.
    /// Uses AestheticSystem for consistent text color throughout the app.
    @ViewBuilder
    static func bullet(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 6) {
            Text("•")
                .font(AestheticSystem.Typography.caption)
                .foregroundColor(AestheticSystem.Colors.textPrimary)
            Text(text)
                .font(AestheticSystem.Typography.caption)
                .foregroundColor(AestheticSystem.Colors.textPrimary)
        }
    }
}
