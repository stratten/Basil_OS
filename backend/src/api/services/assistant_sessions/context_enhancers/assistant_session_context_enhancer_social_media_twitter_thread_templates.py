"""
Twitter Thread Templates and Detection System

This module provides viral thread templates and smart detection for when
users are likely creating thread content, without requiring explicit keywords.
"""

import re
from typing import Dict, List, Tuple, Optional

class TwitterThreadTemplates:
    """Handles detection and template application for viral Twitter threads."""
    
    def __init__(self):
        self.thread_indicators = {
            # Content structure indicators
            'numbered_points': r'\b(\d+[\)\.]\s|first|second|third|fourth|fifth)',
            'thread_language': r'\b(thread|tweets?|viral|hook|engagement)\b',
            'list_structure': r'(\n\s*[-•]\s|\bhow to\b|\btips?\b|\bsteps?\b)',
            'storytelling': r'\b(story|happened|reveals?|turns out|secret)\b',
            'audience_building': r'\b(followers?|audience|viral|share|retweet)\b',
            
            # Content themes that work well as threads
            'contrarian': r'\b(everyone thinks|turns out|actually|truth is|real reason)\b',
            'revelation': r'\b(discovered|revealed|exposed|found out|nobody talks about)\b',
            'authority': r'\b(years? of|expert|research|study|data shows)\b',
            'urgency': r'\b(just happened|breaking|urgent|immediate|crisis)\b'
        }
        
    def detect_thread_intent(self, content: str, instruction: str) -> Dict[str, any]:
        """
        Analyze context to determine if user likely wants thread content.
        Uses multiple signals to avoid fragile string matching.
        """
        combined_text = f"{content} {instruction}".lower()
        
        signals = {}
        confidence = 0.0
        
        # Check each indicator pattern
        for signal_type, pattern in self.thread_indicators.items():
            matches = len(re.findall(pattern, combined_text, re.IGNORECASE))
            if matches > 0:
                signals[signal_type] = matches
                confidence += min(matches * 0.15, 0.3)  # Cap individual contribution
        
        # Bonus points for combinations
        if len(signals) >= 3:
            confidence += 0.2
        if 'numbered_points' in signals and 'storytelling' in signals:
            confidence += 0.3
        if 'contrarian' in signals and 'revelation' in signals:
            confidence += 0.2
            
        # Content length indicator (threads typically longer)
        if len(combined_text) > 200:
            confidence += 0.1
            
        # Multiple sentences/paragraphs
        if combined_text.count('.') >= 3 or combined_text.count('\n') >= 2:
            confidence += 0.1
            
        confidence = min(confidence, 1.0)  # Cap at 100%
        
        thread_type = self._determine_thread_type(signals, combined_text)
        hook_type = self._suggest_hook_type(combined_text)
        
        return {
            'is_likely_thread': confidence >= 0.4,
            'confidence': confidence,
            'detected_signals': list(signals.keys()),
            'suggested_thread_type': thread_type,
            'suggested_hook_type': hook_type,
            'thread_guidance': self._get_thread_guidance(thread_type, hook_type) if confidence >= 0.4 else None
        }
    
    def _determine_thread_type(self, signals: Dict[str, int], text: str) -> Optional[str]:
        """Determine which thread structure would work best."""
        if 'numbered_points' in signals and 'authority' in signals:
            return 'countdown_revelation'
        elif 'contrarian' in signals and 'revelation' in signals:
            return 'problem_agitation_solution'
        elif 'urgency' in signals or 'breaking' in text:
            return 'fear_to_solution'
        elif len(signals) >= 2:
            return 'problem_agitation_solution'  # Default versatile structure
        return None
    
    def _suggest_hook_type(self, text: str) -> Optional[str]:
        """Suggest which hook template would work best."""
        if re.search(r'\b(everyone|people) (thinks?|believes?|blames?)', text):
            return 'contrarian_revelation'
        elif re.search(r'\b(just|recently|hours?|days?) (ago|happened)', text):
            return 'breaking_news_controversy'
        elif re.search(r'\bmost (powerful|successful|wealthy)', text):
            return 'unexpected_authority'
        elif re.search(r'\b\d+%|\b\d+x (more|less|higher|lower)', text):
            return 'statistical_shock'
        return 'contrarian_revelation'  # Good default
    
    def _get_thread_guidance(self, thread_type: str, hook_type: str) -> str:
        """Generate specific guidance for the detected thread type."""
        
        hook_templates = {
            'contrarian_revelation': {
                'pattern': 'Every [demographic] blames [common belief] for [problem]. Turns out it\'s not [belief]... it\'s [real cause]',
                'approach': 'Challenge universal beliefs, create \'aha moment\', promise hope'
            },
            'breaking_news_controversy': {
                'pattern': '[New Technology/Event] dropped [timeframe] ago. Turns out, it [shocking behavior] to [avoid consequence]',
                'approach': 'Create urgency, trigger fear/curiosity, position as insider knowledge'
            },
            'unexpected_authority': {
                'pattern': 'The most [superlative] [category] in the world today isn\'t [expected answer]... It\'s [unexpected reveal]',
                'approach': 'Challenge conventional wisdom, create mystery, promise exclusive knowledge'
            },
            'statistical_shock': {
                'pattern': '[Unexpected group] has [shocking statistic] compared to [mainstream group]. Their secret? Not [expected solutions] but [simple alternative]',
                'approach': 'Provide stark contrast, challenge modern assumptions, offer simple hope'
            }
        }
        
        thread_structures = {
            'problem_agitation_solution': [
                '1. Hook with controversy/revelation',
                '2. Agitate the problem with specifics',
                '3. Explain the real cause', 
                '4. Promise solution with timeframe',
                '5. Deliver actionable tips (8-10 points)',
                '6. Include specific examples/stories',
                '7. Close with transformation promise',
                '8. Call-to-action for engagement'
            ],
            'countdown_revelation': [
                '1. Mystery hook (hint at #1 without revealing)',
                '2. Build anticipation with countdown (10-1)',
                '3. Each point: position + story + current impact',
                '4. Reveal #1 with maximum detail',
                '5. Connect patterns across all points',
                '6. Bridge to expertise/credibility',
                '7. Standard engagement CTA'
            ],
            'fear_to_solution': [
                '1. Shocking revelation hook',
                '2. Escalate with worse implications',
                '3. Provide alarming but credible statistics',
                '4. Question if others share concerns',
                '5. Position as expert with solution',
                '6. Provide actionable steps',
                '7. Soft reassurance with path forward',
                '8. Standard CTA'
            ]
        }
        
        hook_info = hook_templates.get(hook_type, hook_templates['contrarian_revelation'])
        structure_info = thread_structures.get(thread_type, thread_structures['problem_agitation_solution'])
        
        return f"""
VIRAL THREAD GUIDANCE DETECTED:

SUGGESTED HOOK PATTERN ({hook_type}):
Pattern: {hook_info['pattern']}
Approach: {hook_info['approach']}

SUGGESTED THREAD STRUCTURE ({thread_type}):
{chr(10).join(structure_info)}

KEY VIRAL ELEMENTS TO INCLUDE:
• Use specific statistics and exact numbers (not "many" or "most")
• Include personal stories or case studies for credibility
• Create curiosity gaps that demand resolution
• Position yourself as having insider knowledge or expertise
• Make controversial claims that spark discussion
• Provide actionable takeaways readers can bookmark
• End with clear engagement ask (follow, share, comment)

PSYCHOLOGICAL TRIGGERS:
• Authority signals: Specific data, historical context, insider knowledge
• Curiosity gaps: Cliffhanger questions, mystery reveals, unexpected connections
• Social proof: Name-drop companies/figures, quantify impact, show community size
• Fear/urgency: Technology concerns, being left behind, hidden dangers

Remember: Viral threads challenge assumptions, provide unexpected insights, and leave readers feeling smarter or more informed than before reading.
""" 