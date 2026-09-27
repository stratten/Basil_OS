import SwiftUI

@MainActor
struct CapabilityIntroduction_AssistantSession: View {
    private let bulletSpacing: CGFloat = 6

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                // Header
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .center, spacing: 10) {
                        Image(systemName: "wand.and.stars")
                            .font(.system(size: 26))
                            .foregroundColor(AestheticSystem.Colors.primary)
                        Text(BasilTeamIdentity.assistantSession.displayName)
                            .font(AestheticSystem.Typography.largeTitle)
                    }

                    Text("The smartest way to draft replies, summaries, and content — just tell Basil what you want")
                        .font(AestheticSystem.Typography.title3)
                        .foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                // How it works
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Here's the magic").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Hit your suggestions hotkey — a widget pops up")
                        OnboardingBulletStyles.bullet("Say what you want: \"Draft a reply saying yes to Tuesday\" or \"Summarize this in 3 bullets\"")
                        OnboardingBulletStyles.bullet("While you speak, Basil reads what's on your screen and pairs it with your request")
                        OnboardingBulletStyles.bullet("Behind the scenes, Basil enhances your request to be clearer and more specific")
                        OnboardingBulletStyles.bullet("Watch your perfect draft appear in real-time")
                        OnboardingBulletStyles.bullet("One click to insert it exactly where you need it")
                    }
                }

                // Why permissions
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("About those permissions").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Microphone: So you can speak naturally instead of typing")
                        OnboardingBulletStyles.bullet("Accessibility: Lets Basil paste your drafts seamlessly into any app")
                    }
                }

                // Practical examples section (NEW)
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Perfect for quick tasks").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("\"Draft a quick reply to this email accepting the meeting\"")
                        OnboardingBulletStyles.bullet("\"Summarize these bullet points into one sentence\"")
                        OnboardingBulletStyles.bullet("\"Make this paragraph more professional\"")
                        OnboardingBulletStyles.bullet("\"Translate this text to Spanish\"")
                    }
                }

                // Tips
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Tips for amazing results").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Basil automatically reads your current app — no selection needed")
                        OnboardingBulletStyles.bullet("Unlike other tools, you never have to highlight text for Basil to understand context")
                        OnboardingBulletStyles.bullet("But it you want to narrow the focus, you can highlight specific text and it will prioritize that")
                        OnboardingBulletStyles.bullet("Be specific with your request: \"Write a friendly reply accepting the Tuesday meeting\"")
                    }
                }

                // Hotkey guidance
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("About the hotkey").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Default hotkey: ⌥+⌥ (double-tap Option)")
                        OnboardingBulletStyles.bullet("Quick and ergonomic - no awkward key combos")
                        OnboardingBulletStyles.bullet("Customize anytime in Settings → Hotkeys")
                    }
                }

                // Models / API note
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Local vs. cloud models").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Local models keep everything private and work without internet")
                        OnboardingBulletStyles.bullet("Cloud models (optional) know more about the world and stay up-to-date")
                        OnboardingBulletStyles.bullet("You can switch anytime in Settings — cloud usage goes to your own API account")
                    }
                }

                // Future enhancement note
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Getting even smarter").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Soon: Basil will learn from your past activities to match your natural writing tone")
                        OnboardingBulletStyles.bullet("The more you use it, the better it gets at sounding like you")
                    }
                }
            }
            .padding(32)
        }
    }
}

struct CapabilityIntroduction_AssistantSession_Previews: PreviewProvider {
    static var previews: some View {
        CapabilityIntroduction_AssistantSession()
            .frame(width: 680, height: 520)
    }
}


