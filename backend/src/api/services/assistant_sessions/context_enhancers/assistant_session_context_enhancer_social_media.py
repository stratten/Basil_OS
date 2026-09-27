"""
AssistantSession Context Enhancer for Social Media Platforms

This module provides intelligent context enhancement for social media posts across
different platforms, with special viral thread detection capabilities for Twitter.
"""

import re
import logging
from typing import Dict, Any, Optional
from .assistant_session_context_enhancer_social_media_twitter_thread_templates import TwitterThreadTemplates

logger = logging.getLogger(__name__)

class AssistantSessionSocialMediaEnhancer:
    """
    Specialized context enhancer for social media platform AssistantSession suggestions.
    Handles platform-specific constraints, tone, and formatting requirements.
    """
    
    def __init__(self, coordinator=None):
        self.coordinator = coordinator  # Reference to AssistantSessionContextEnhancer for shared methods
        # Platform-specific detection patterns.
        # Patterns must be discriminating signals — strong domain markers, UI text,
        # or platform-specific affordances. Generic English words (post, comment,
        # share, business, professional, friends, etc.) are intentionally excluded
        # because they appear across all social platforms and cause misdetection.
        self.platform_patterns = {
            "twitter": [
                r"\btwitter\.com\b",
                r"\bx\.com\b",
                r"What's happening\?",
                r"\bRetweet\b",
                r"\bRetweets\b",
                r"\bQuote Tweet\b",
                r"\bRepost\b",
                r"\b280 characters?\b",
                r"\bTrending\b",
                r"\bWho to follow\b"
            ],
            "linkedin": [
                r"\blinkedin\.com\b",
                r"\bLinkedIn\b",
                r"\bMy Network\b",
                r"\bAdd to your feed\b",
                r"\bConnections\b",
                r"\bRecommended for you\b",
                r"\bPeople you may know\b",
                r"\b1st\b\s*\u00b7|\b2nd\b\s*\u00b7|\b3rd\b\s*\u00b7"
            ],
            "facebook": [
                r"\bfacebook\.com\b",
                r"\bfb\.com\b",
                r"\bFacebook\b",
                r"\bNews Feed\b",
                r"\bWhat's on your mind\b",
                r"\bMarketplace\b",
                r"\bFriend Requests\b"
            ],
            "reddit": [
                r"\breddit\.com\b",
                r"\br/\w+\b",
                r"\bsubreddit\b",
                r"\bupvote\b",
                r"\bdownvote\b",
                r"\bu/\w+\b",
                r"\bOP\b",
                r"\bcrosspost\b",
                r"\bAsk Reddit\b",
                r"\bModerator\b\s*of\s*r/"
            ],
            "instagram": [
                r"\binstagram\.com\b",
                r"\bInstagram\b",
                r"\bReels\b",
                r"\bExplore\b",
                r"\bSuggested for you\b",
                r"\bIGTV\b",
                r"\bView all \d+ comments\b"
            ]
        }
        
        # Initialize Twitter thread detection
        self.thread_detector = TwitterThreadTemplates()
        
        # Social media app detection
        self.social_apps = [
            "twitter", "x.com", "tweetdeck", "hootsuite",
            "linkedin", "facebook", "instagram", "reddit",
            "buffer", "sprout social", "later"
        ]

    def enhance(self, content: str, instruction: str, personalization_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Enhance social media-specific AssistantSession suggestions with personalization support.
        
        Args:
            content: Raw OCR text from social media interface
            instruction: User's voice instruction
            personalization_context: Optional personalization data from orchestrator
            
        Returns:
            Enhancement result with social media-specific processing
        """
        try:
            # Detect specific platform
            platform = self._detect_platform(content)
            
            if platform == "twitter":
                return self._enhance_twitter_post(content, instruction, personalization_context)
            elif platform == "linkedin":
                return self._enhance_linkedin_post(content, instruction, personalization_context)
            elif platform == "facebook":
                return self._enhance_facebook_post(content, instruction, personalization_context)
            elif platform == "reddit":
                return self._enhance_reddit_post(content, instruction, personalization_context)
            elif platform == "instagram":
                return self._enhance_instagram_post(content, instruction, personalization_context)
            else:
                # Generic social media context
                return self._enhance_generic_social(content, instruction, personalization_context)
                
        except Exception as e:
            logger.error(f"Error in social media enhancement: {e}")
            return {
                "context_type": "social_media_generic",
                "filtered_content": content,
                "enhanced_prompt": self._build_fallback_prompt(content, instruction),
                "metadata": {"error": str(e), "enhancer": "social_media"}
            }

    def _detect_platform(self, content: str) -> str:
        """Detect specific social media platform from content using a confidence score.

        Counts how many discriminating patterns each platform matches. The
        platform with the highest score wins, but only if it has at least 2
        matches OR a single very strong match (a domain pattern). Otherwise
        falls back to ``generic_social`` to avoid stamping a wrong label that
        the model would later try to reconcile out loud.
        """
        # Patterns that are strong enough on their own to lock a platform in
        strong_single_match_patterns = {
            "twitter": [r"\btwitter\.com\b", r"\bx\.com\b"],
            "linkedin": [r"\blinkedin\.com\b"],
            "facebook": [r"\bfacebook\.com\b", r"\bfb\.com\b"],
            "reddit": [r"\breddit\.com\b", r"\br/\w+\b"],
            "instagram": [r"\binstagram\.com\b"],
        }

        scores: Dict[str, int] = {}
        for platform, patterns in self.platform_patterns.items():
            score = sum(
                1
                for pattern in patterns
                if re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
            )
            if score > 0:
                scores[platform] = score

        if not scores:
            return "generic_social"

        best_platform = max(scores, key=scores.get)
        best_score = scores[best_platform]

        # Two or more matches is enough confidence
        if best_score >= 2:
            return best_platform

        # Single match is only enough if it's a strong domain-level pattern
        for pattern in strong_single_match_patterns.get(best_platform, []):
            if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
                return best_platform

        return "generic_social"

    def _enhance_twitter_post(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Enhance Twitter posts with platform-specific guidance and thread detection."""
        # Detect if this might be thread content
        thread_analysis = self.thread_detector.detect_thread_intent(content, instruction)
        
        metadata = self._extract_twitter_metadata(content)
        
        # Add thread analysis to metadata if detected
        if thread_analysis['is_likely_thread']:
            metadata.update({
                'thread_detected': True,
                'thread_confidence': thread_analysis['confidence'],
                'thread_type': thread_analysis['suggested_thread_type'],
                'hook_type': thread_analysis['suggested_hook_type'],
                'thread_signals': thread_analysis['detected_signals']
            })
        
        enhanced_prompt = self._build_twitter_prompt(content, instruction, metadata, thread_analysis, personalization)
        
        return {
            "enhanced_prompt": enhanced_prompt,
            "context_type": "social_media_twitter",
            "platform": "twitter",
            "metadata": metadata
        }

    def _enhance_linkedin_post(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle LinkedIn-specific enhancement."""
        metadata = self._extract_linkedin_metadata(content)
        metadata["enhancer"] = "social_media"
        metadata["platform"] = "linkedin"
        
        enhanced_prompt = self._build_linkedin_prompt(content, instruction, metadata, personalization)
        
        return {
            "context_type": "social_media_linkedin",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _enhance_facebook_post(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle Facebook-specific enhancement."""
        metadata = self._extract_facebook_metadata(content)
        metadata["enhancer"] = "social_media"
        metadata["platform"] = "facebook"
        
        enhanced_prompt = self._build_facebook_prompt(content, instruction, metadata, personalization)
        
        return {
            "context_type": "social_media_facebook",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _enhance_reddit_post(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle Reddit-specific enhancement."""
        metadata = self._extract_reddit_metadata(content)
        metadata["enhancer"] = "social_media"
        metadata["platform"] = "reddit"
        
        enhanced_prompt = self._build_reddit_prompt(content, instruction, metadata, personalization)
        
        return {
            "context_type": "social_media_reddit",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _enhance_instagram_post(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle Instagram-specific enhancement."""
        metadata = self._extract_instagram_metadata(content)
        metadata["enhancer"] = "social_media"
        metadata["platform"] = "instagram"
        
        enhanced_prompt = self._build_instagram_prompt(content, instruction, metadata, personalization)
        
        return {
            "context_type": "social_media_instagram",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _enhance_generic_social(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle generic social media enhancement."""
        metadata = {"enhancer": "social_media", "platform": "generic_social"}
        enhanced_prompt = self._build_generic_social_prompt(content, instruction, personalization)
        
        return {
            "context_type": "social_media_generic",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _extract_twitter_metadata(self, content: str) -> Dict[str, Any]:
        """Extract Twitter-specific metadata."""
        metadata = {}
        
        # Check for character limit context
        char_limit_match = re.search(r"(\d+)\s*characters?\s*remaining", content, re.IGNORECASE)
        if char_limit_match:
            remaining = int(char_limit_match.group(1))
            metadata["characters_remaining"] = remaining
            metadata["characters_used"] = 280 - remaining
        
        # Check for mentions and hashtags in existing content
        mentions = re.findall(r"@[a-zA-Z0-9_]+", content)
        hashtags = re.findall(r"#[a-zA-Z0-9_]+", content)
        
        if mentions:
            metadata["existing_mentions"] = mentions
        if hashtags:
            metadata["existing_hashtags"] = hashtags
            
        # Check for reply context
        if re.search(r"Replying to|Reply to", content, re.IGNORECASE):
            metadata["is_reply"] = True
        
        return metadata

    def _extract_linkedin_metadata(self, content: str) -> Dict[str, Any]:
        """Extract LinkedIn-specific metadata."""
        metadata = {}
        
        # Check for article vs. post context
        if re.search(r"LinkedIn Article|Long.form", content, re.IGNORECASE):
            metadata["post_type"] = "article"
        else:
            metadata["post_type"] = "post"
            
        # Check for professional keywords
        professional_terms = re.findall(
            r"\b(?:industry|career|business|professional|network|achievement|leadership|innovation)\b", 
            content, re.IGNORECASE
        )
        if professional_terms:
            metadata["professional_context"] = professional_terms
            
        return metadata

    def _extract_facebook_metadata(self, content: str) -> Dict[str, Any]:
        """Extract Facebook-specific metadata."""
        metadata = {}
        
        # Check for page vs. personal profile
        if re.search(r"Facebook Page|Page|Business", content, re.IGNORECASE):
            metadata["context_type"] = "page"
        else:
            metadata["context_type"] = "personal"
            
        return metadata

    def _extract_reddit_metadata(self, content: str) -> Dict[str, Any]:
        """Extract Reddit-specific metadata."""
        metadata = {}
        
        # Extract subreddit if visible
        subreddit_match = re.search(r"r/(\w+)", content)
        if subreddit_match:
            metadata["subreddit"] = subreddit_match.group(1)
            
        # Check for post type
        if re.search(r"Submit.*link|URL", content, re.IGNORECASE):
            metadata["post_type"] = "link"
        elif re.search(r"Submit.*text|Text post", content, re.IGNORECASE):
            metadata["post_type"] = "text"
        elif re.search(r"Reply|Comment", content, re.IGNORECASE):
            metadata["post_type"] = "comment"
            
        return metadata

    def _extract_instagram_metadata(self, content: str) -> Dict[str, Any]:
        """Extract Instagram-specific metadata."""
        metadata = {}
        
        # Check for content type
        if re.search(r"Story|Add to story", content, re.IGNORECASE):
            metadata["content_type"] = "story"
        elif re.search(r"Reel", content, re.IGNORECASE):
            metadata["content_type"] = "reel"
        else:
            metadata["content_type"] = "post"
            
        return metadata

    def _build_twitter_prompt(self, content: str, instruction: str, metadata: Dict[str, Any], thread_analysis: Dict[str, Any], personalization: Optional[Dict[str, Any]] = None) -> str:
        """Build Twitter-specific prompt."""
        char_info = ""
        if "characters_remaining" in metadata:
            char_info = f"\n- You have {metadata['characters_remaining']} characters remaining (280 character limit)"
        
        reply_context = ""
        if metadata.get("is_reply", False):
            reply_context = "\n- This is a reply to another tweet - be conversational and engaging"
        
        base_prompt = f"""You are a senior ghostwriter for a Twitter creator who excels at mimicking someone's vocabulary, diction, writing style, tweet structure, and the way they communicate. Your specialty is mirroring someone's content so perfectly that no one in the world can tell it was written by you and not the original person.

CORE GHOSTWRITING PRINCIPLES:
- Write so authentically that NO ONE can tell it was written by AI or anyone else besides the person you're ghostwriting for
- Notice and mirror small details: writing style, vocabulary, diction, tweet structure, line spacing - mirror it all to a tee
- The content must sound exactly like something this person would naturally write and post
- Avoid any AI-like phrasing, corporate speak, or generic social media language

AUDIENCE ANALYSIS & ADAPTATION:
- Analyze the context and content to understand the likely audience and their technical background
- If the audience appears technical: maintain appropriate technical language while ensuring clarity
- If the audience appears non-technical: break down technical concepts using everyday analogies and simple language
- If discussing AI/tech topics: explain them relative to the audience's likely assistant_sessionity (business tools, consumer apps, etc.)
- Make complex ideas feel accessible and not intimidating for the intended audience

TECHNICAL CONTENT APPROACH:
- When technical concepts arise: translate them to language appropriate for the detected audience context
- Use analogies and examples that resonate with the apparent community or audience
- Connect new concepts to things the audience likely already understands
- Make expertise accessible without being condescending or oversimplifying inappropriately

TWITTER-SPECIFIC EXECUTION:
- Keep within character limits and Twitter's conversational style{char_info}{reply_context}
- Use natural line breaks and spacing that matches the creator's style
- Include hashtags and mentions only if they fit the creator's natural posting pattern
- Focus on authentic engagement over optimization
"""

        # Add personalization section if available
        if personalization and self.coordinator:
            base_prompt += self.coordinator.build_personalization_section(personalization)
        
        base_prompt += f"""
SCREEN CONTENT:
{content}

USER INSTRUCTION: {instruction}

Create a tweet that perfectly mirrors this creator's authentic voice while making any technical concepts appropriately clear for the intended audience."""

        # Add thread guidance if detected
        if thread_analysis['is_likely_thread'] and thread_analysis['thread_guidance']:
            thread_guidance = thread_analysis['thread_guidance']
            base_prompt += f"\n\n{thread_guidance}\n\nApply this viral thread guidance to create content that captures attention and drives engagement while maintaining authentic voice."
        
        return base_prompt

    def _build_linkedin_prompt(self, content: str, instruction: str, metadata: Dict[str, Any], personalization: Optional[Dict[str, Any]] = None) -> str:
        """Build LinkedIn-specific prompt."""
        post_type_info = ""
        if metadata.get("post_type") == "article":
            post_type_info = "\n- This appears to be a LinkedIn article - use a more formal, detailed approach"
        else:
            post_type_info = "\n- This is a LinkedIn post - balance professionalism with engagement"
        
        professional_context = ""
        if "professional_context" in metadata:
            professional_context = f"\n- Professional context detected: {', '.join(metadata['professional_context'])}"
        
        base_prompt = f"""You are a senior ghostwriter specializing in professional LinkedIn content who excels at mimicking someone's professional voice, vocabulary, and communication style. Your specialty is creating content that sounds exactly like the original person wrote it - no one can tell it was ghostwritten.

CORE GHOSTWRITING PRINCIPLES:
- Write so authentically that colleagues and connections can't tell it wasn't written by the person themselves
- Mirror their professional vocabulary, tone, and way of structuring thoughts
- Maintain their unique perspective and voice while ensuring professional appropriateness
- Avoid generic LinkedIn corporate speak or AI-like phrasing

AUDIENCE ANALYSIS & ADAPTATION:
- Analyze the context, content, and apparent professional community to understand the audience
- If the audience appears highly technical: maintain appropriate technical depth while ensuring accessibility
- If the audience appears business-focused: translate technical concepts to business outcomes and practical applications
- If mixed audience: balance technical accuracy with broader accessibility
- Adapt complexity and terminology to match the professional context and community norms

PROFESSIONAL CONTENT APPROACH:
- When complex topics arise: break them down appropriately for the detected professional audience
- Use analogies and frameworks relevant to the apparent professional community
- Connect abstract concepts to practical outcomes meaningful to the audience
- Make expertise approachable and implementable for the intended professional context

LINKEDIN-SPECIFIC EXECUTION:
- Use professional formatting with strategic line breaks for readability{post_type_info}{professional_context}
- Balance thought leadership with personal authenticity
- Include hashtags and mentions only if they fit this person's natural posting style
- Focus on providing genuine value over viral content
"""

        # Add personalization section if available
        if personalization and self.coordinator:
            base_prompt += self.coordinator.build_personalization_section(personalization)
        
        base_prompt += f"""
SCREEN CONTENT:
{content}

USER INSTRUCTION: {instruction}

Create LinkedIn content that perfectly captures this person's professional voice while making complex concepts appropriately clear and actionable for the intended professional audience:"""
        
        return base_prompt

    def _build_facebook_prompt(self, content: str, instruction: str, metadata: Dict[str, Any], personalization: Optional[Dict[str, Any]] = None) -> str:
        """Build Facebook-specific prompt."""
        context_info = ""
        if metadata.get("context_type") == "page":
            context_info = "\n- This appears to be a business page - maintain brand voice and professionalism"
        else:
            context_info = "\n- This is a personal profile - use a more casual, personal tone"
        
        base_prompt = f"""You are a skilled ghostwriter who specializes in authentic Facebook content, perfectly mimicking someone's personal voice and communication style. Your expertise is creating posts that sound exactly like the person wrote them - friends and family would never suspect otherwise.

CORE GHOSTWRITING PRINCIPLES:
- Write with complete authenticity - mirror their personality, humor, and way of expressing themselves
- Capture their unique voice, vocabulary, and storytelling style
- Sound like a real person sharing genuine thoughts, not a content creator or AI
- Avoid social media marketing language or overly polished content

AUDIENCE AWARENESS:
- The audience includes friends, family, and personal connections who are NOT technical
- Many are everyday people with minimal tech experience beyond basic apps
- Explain any complex topics like you're talking to a friend over coffee
- Use relatable examples from daily life and common experiences
- Keep explanations warm, personal, and conversational

PERSONAL CONTENT APPROACH:
- If discussing work topics: make them relatable to personal experience
- If sharing insights: frame them as personal discoveries or lessons learned
- Use storytelling and personal anecdotes when appropriate
- Make content feel like genuine sharing, not teaching or promoting

FACEBOOK-SPECIFIC EXECUTION:
- Use natural, conversational formatting that matches how this person typically posts{context_info}
- Include personal touches, emotions, and authentic reactions
- Use hashtags sparingly and only if they naturally fit this person's posting style
- Focus on genuine connection and conversation over engagement metrics
"""

        # Add personalization section if available
        if personalization and self.coordinator:
            base_prompt += self.coordinator.build_personalization_section(personalization)
        
        base_prompt += f"""
SCREEN CONTENT:
{content}

USER INSTRUCTION: {instruction}

Create Facebook content that perfectly mirrors this person's authentic personal voice while keeping any complex topics relatable and conversational:"""
        
        return base_prompt

    def _build_reddit_prompt(self, content: str, instruction: str, metadata: Dict[str, Any], personalization: Optional[Dict[str, Any]] = None) -> str:
        """Build Reddit-specific prompt."""
        subreddit_info = ""
        if "subreddit" in metadata:
            subreddit_info = f"\n- This is for r/{metadata['subreddit']} - tailor content to that community"
        
        post_type_info = ""
        if metadata.get("post_type") == "comment":
            post_type_info = "\n- This is a comment reply - be conversational and add value to the discussion"
        elif metadata.get("post_type") == "text":
            post_type_info = "\n- This is a text post - provide detailed, valuable content"
        
        base_prompt = f"""You are an expert ghostwriter who specializes in authentic Reddit content, perfectly capturing someone's natural communication style and personality. Your skill is creating posts and comments that sound exactly like the person wrote them - no one in the community can tell it was ghostwritten.

CORE GHOSTWRITING PRINCIPLES:
- Write with genuine authenticity - mirror their personality, humor, and way of contributing to discussions
- Capture their unique voice, perspective, and style of engaging with communities
- Sound like a real community member sharing honest thoughts and experiences
- Avoid corporate speak, marketing language, or AI-like responses

AUDIENCE AWARENESS:
- Reddit communities value authentic, knowledgeable contributions from real people
- Many users are tech-savvy but expertise varies widely across different topics
- Explain complex topics clearly but respect the community's intelligence
- Use examples and analogies that resonate with the specific community culture
- Be helpful and informative without being condescending

COMMUNITY CONTENT APPROACH:
- If sharing expertise: frame it as personal experience and lessons learned
- If discussing complex topics: break them down clearly but maintain the person's natural teaching style
- Use specific examples and practical insights that add real value
- Engage genuinely with the community's interests and concerns

REDDIT-SPECIFIC EXECUTION:
- Use formatting that matches Reddit culture and this person's style{subreddit_info}{post_type_info}
- Focus on adding genuine value to the discussion
- Use proper Reddit conventions (u/username, r/subreddit) naturally
- Maintain the person's authentic way of engaging with online communities
"""

        # Add personalization section if available
        if personalization and self.coordinator:
            base_prompt += self.coordinator.build_personalization_section(personalization)
        
        base_prompt += f"""
SCREEN CONTENT:
{content}

USER INSTRUCTION: {instruction}

Create Reddit content that perfectly captures this person's authentic community voice while making complex topics accessible and valuable to the discussion:"""
        
        return base_prompt

    def _build_instagram_prompt(self, content: str, instruction: str, metadata: Dict[str, Any], personalization: Optional[Dict[str, Any]] = None) -> str:
        """Build Instagram-specific prompt."""
        content_type_info = ""
        if metadata.get("content_type") == "story":
            content_type_info = "\n- This is for Instagram Stories - keep it casual and immediate"
        elif metadata.get("content_type") == "reel":
            content_type_info = "\n- This is for Instagram Reels - focus on entertainment and engagement"
        
        base_prompt = f"""You are a talented ghostwriter who specializes in authentic Instagram content, perfectly mimicking someone's personal style, voice, and visual storytelling approach. Your expertise is creating captions that sound exactly like the person wrote them - followers would never suspect otherwise.

CORE GHOSTWRITING PRINCIPLES:
- Write with complete authenticity - mirror their personality, energy, and way of sharing life
- Capture their unique voice, aesthetic, and storytelling style
- Sound like genuine personal sharing, not influencer content or AI-generated posts
- Avoid generic social media language or overly polished marketing speak

AUDIENCE AWARENESS:
- Instagram audiences follow for personal connection and authentic content
- Followers range from close friends to casual connections, mostly non-technical
- Explain any complex topics through personal experience and visual storytelling
- Use relatable language and experiences that connect with their specific audience
- Keep content warm, personal, and visually-minded

PERSONAL CONTENT APPROACH:
- If sharing insights: frame them through personal stories and experiences
- If discussing work topics: make them relatable to personal journey and growth
- Use authentic emotions and reactions that match this person's personality
- Connect content to the visual elements they're sharing

INSTAGRAM-SPECIFIC EXECUTION:
- Use natural formatting and line breaks that match this person's caption style{content_type_info}
- Include personal touches, emotions, and authentic storytelling
- Use hashtags and mentions strategically but only if they fit this person's natural style
- Focus on genuine connection and personal expression over viral content
"""

        # Add personalization section if available
        if personalization and self.coordinator:
            base_prompt += self.coordinator.build_personalization_section(personalization)
        
        base_prompt += f"""
SCREEN CONTENT:
{content}

USER INSTRUCTION: {instruction}

Create Instagram content that perfectly mirrors this person's authentic personal voice while making any complex topics feel personal and relatable:"""
        
        return base_prompt

    def _build_generic_social_prompt(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> str:
        """Build prompt for generic social media contexts."""
        base_prompt = f"""You are an AI assistant helping with social media content.

SOCIAL MEDIA BEST PRACTICES:
- Use an authentic, engaging tone appropriate for social platforms
- Keep it concise and scannable
- Encourage interaction and engagement
- Be authentic and avoid overly promotional language
- Consider your audience and the platform's culture

HASHTAG AND MENTION FORMATTING:
- Format hashtags as #HashtagName (proper capitalization, no spaces)
- Use @ for mentions: @username or @company
- Place hashtags based on platform norms (end for LinkedIn, natural integration for others)
- Convert mentioned topics to hashtags when user's request suggests it or context indicates
- Ensure all tags are properly formatted and platform-appropriate
"""

        # Add personalization section if available
        if personalization and self.coordinator:
            base_prompt += self.coordinator.build_personalization_section(personalization)
        
        base_prompt += f"""
SCREEN CONTENT:
{content}

USER INSTRUCTION: {instruction}

Generate complete, ready-to-post social media content with proper formatting:"""
        
        return base_prompt

    def _build_fallback_prompt(self, content: str, instruction: str) -> str:
        """Build fallback prompt when enhancement fails."""
        return f"""You are an AI assistant helping with a social media task.

CONTENT:
{content}

USER INSTRUCTION: {instruction}

Response:""" 