import SwiftUI

@MainActor
struct CapabilityIntroduction_Transcription: View {
    var onContinue: (() -> Void)? = nil

    private let chipPadding: EdgeInsets = EdgeInsets(top: 4, leading: 10, bottom: 4, trailing: 10)
    private let sectionSpacing: CGFloat = 14
    private let bulletSpacing: CGFloat = 6

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                // Header with personality
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .center, spacing: 10) {
                        Image(systemName: "mic.fill")
                            .font(.system(size: 26))
                            .foregroundColor(AestheticSystem.Colors.primary)
                        Text("Voice Transcription")
                            .font(AestheticSystem.Typography.largeTitle)
                    }
                    
                    Text("Transform your voice into text instantly, anywhere on your Mac")
                        .font(AestheticSystem.Typography.title3)
                        .foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                // What it's like to use (experience-focused)
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Here's how it works").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Press your transcription hotkey to start recording your voice")
                        OnboardingBulletStyles.bullet("Speak naturally — say whatever you want to type")
                        OnboardingBulletStyles.bullet("Press the same key again when you're done")
                        OnboardingBulletStyles.bullet("Your words appear as text in a handy little window")
                        OnboardingBulletStyles.bullet("Click to copy it, or let Basil paste it automatically")
                    }
                }

                // Permission explanation (reassuring)
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    HStack(spacing: 8) {
                        Text("Why we need microphone access").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                        Text("Required")
                            .font(AestheticSystem.Typography.caption)
                            .foregroundColor(.white)
                            .padding(EdgeInsets(top: 3, leading: 8, bottom: 3, trailing: 8))
                            .background(AestheticSystem.Colors.primary.opacity(0.85))
                            .cornerRadius(8)
                    }
                    Group {
                        OnboardingBulletStyles.bullet("Your voice stays private — everything happens on your Mac")
                        OnboardingBulletStyles.bullet("We can't transcribe without hearing you speak")
                        OnboardingBulletStyles.bullet("You control exactly when recording starts and stops")
                    }
                }

                // Model selection (practical guidance)
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Choosing your transcription model").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Faster models: Great for quick notes and casual use")
                        OnboardingBulletStyles.bullet("Larger models: Better accuracy for important documents")
                        OnboardingBulletStyles.bullet("Don't worry — you can always change this later")
                    }
                }

                // Tips for success
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Getting the best results").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Find a quiet spot when possible")
                        OnboardingBulletStyles.bullet("Speak at your normal pace — no need to talk slowly")
                        OnboardingBulletStyles.bullet("Turn on auto-paste in Settings to save clicks")
                    }
                }

                // Hotkey guidance
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("About the hotkey").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Default hotkey: ⌘+⌘ (double-tap Command, hold to record)")
                        OnboardingBulletStyles.bullet("Push-to-talk: hold after double-tap, release to transcribe")
                        OnboardingBulletStyles.bullet("Customize anytime in Settings → Hotkeys")
                    }
                }

                // Navigation handled by the global Next button in the onboarding footer
            }
            .padding(32)
        }
    }

}

struct CapabilityIntroduction_Transcription_Previews: PreviewProvider {
    static var previews: some View {
        CapabilityIntroduction_Transcription()
            .frame(width: 560, height: 480)
    }
}


