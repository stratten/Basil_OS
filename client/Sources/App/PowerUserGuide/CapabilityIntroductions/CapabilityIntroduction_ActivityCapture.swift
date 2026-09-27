import SwiftUI

@MainActor
struct CapabilityIntroduction_ActivityCapture: View {
    private let bulletSpacing: CGFloat = 6

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                // Header
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .center, spacing: 10) {
                        Image(systemName: "chart.line.uptrend.xyaxis")
                            .font(.system(size: 26))
                            .foregroundColor(AestheticSystem.Colors.primary)
                        Text("Activity Capture")
                            .font(AestheticSystem.Typography.largeTitle)
                    }

                    Text("Automatic productivity monitoring that builds a searchable timeline of your work — never lose track of what you were doing")
                        .font(AestheticSystem.Typography.title3)
                        .foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                // How it works
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Your automatic work timeline").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Takes periodic screenshots of your active window (every 30 seconds to 24 hours)")
                        OnboardingBulletStyles.bullet("Extracts all visible text using OCR technology")
                        OnboardingBulletStyles.bullet("Records app names, window titles, and timestamps")
                        OnboardingBulletStyles.bullet("Builds a searchable database of your work activities")
                        OnboardingBulletStyles.bullet("Runs quietly in the background — no interruptions")
                    }
                }

                // Privacy and control
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Your data stays private").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Activity data never leaves your Mac permanently — even when using cloud AI")
                        OnboardingBulletStyles.bullet("Screenshots are processed locally with OCR")
                        OnboardingBulletStyles.bullet("You control capture frequency and can pause anytime")
                        OnboardingBulletStyles.bullet("Delete your activity history whenever you want")
                    }
                }

                // Practical benefits
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Never lose your work again").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Searchable timeline of all your work activities")
                        OnboardingBulletStyles.bullet("Recreate context: \"What was I working on yesterday afternoon?\"")
                        OnboardingBulletStyles.bullet("Track productivity: See how you actually spend your time")
                        OnboardingBulletStyles.bullet("Automatic backup: Your work context is always preserved")
                    }
                }

                // Configuration options
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Flexible configuration").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Frequency: Every 30 seconds to once per day (Settings → Activity Capture)")
                        OnboardingBulletStyles.bullet("Processing: Choose local models for privacy or cloud models for enhanced analysis")
                        OnboardingBulletStyles.bullet("Status: See capture status in your menu bar")
                        OnboardingBulletStyles.bullet("History: Browse and search captures in Settings → Activity History")
                    }
                }

                // How to use your data
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Query your work history").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Browse your timeline in Settings → Activity History")
                        OnboardingBulletStyles.bullet("Ask about recent work: \"What did I work on last Tuesday?\"")
                        OnboardingBulletStyles.bullet("Search by app or window title for specific activities")
                        OnboardingBulletStyles.bullet("Note: Advanced semantic search is actively being refined")
                    }
                }

                // Getting started
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Getting started").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Start with longer intervals (15-30 minutes) to see how it works")
                        OnboardingBulletStyles.bullet("Try querying your data after a day or two of captures")
                        OnboardingBulletStyles.bullet("Adjust frequency based on your comfort and needs")
                        OnboardingBulletStyles.bullet("Remember: you can pause, adjust, or delete data anytime")
                    }
                }
            }
            .padding(32)
        }
    }
}

struct CapabilityIntroduction_ActivityCapture_Previews: PreviewProvider {
    static var previews: some View {
        CapabilityIntroduction_ActivityCapture()
            .frame(width: 680, height: 520)
    }
}
