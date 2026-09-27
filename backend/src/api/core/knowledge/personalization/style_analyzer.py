"""
Writing Style Analyzer - LLM-Based

Uses an LLM to analyze writing samples and extract nuanced communication style patterns.
This replaces the primitive regex-based approach with intelligent analysis.
"""

import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class StyleAnalyzer:
    """Analyzes writing samples using LLM to extract communication style patterns."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def analyze_samples(
        self, 
        samples: List[Dict[str, Any]],
        context_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze a collection of writing samples to extract style patterns.
        
        Args:
            samples: List of writing sample dicts with 'content' field
            context_type: Optional context type to focus analysis
            
        Returns:
            Dict containing extracted style attributes
        """
        if not samples:
            self.logger.warning("No samples provided for analysis")
            return self._get_default_style()
        
        self.logger.info(f"Analyzing {len(samples)} writing samples for context: {context_type or 'all'}")
        
        # Extract all content
        contents = [s.get('content', '') for s in samples if s.get('content')]
        
        if not contents:
            self.logger.warning("No content found in samples")
            return self._get_default_style()
        
        # Use LLM to analyze style
        try:
            style_analysis = await self._analyze_with_llm(contents, context_type)
            
            # Calculate confidence based on sample size
            confidence = self._calculate_confidence(len(samples))
            
            self.logger.info(
                f"Style analysis complete: formality={style_analysis.get('formality_level', 0.5):.2f}, "
                f"confidence={confidence:.2f}"
            )
            
            return {
                'style_attributes': style_analysis,
                'confidence': confidence,
                'sample_count': len(samples),
                'analyzed_at': datetime.utcnow().isoformat() + "Z"
            }
        except Exception as e:
            self.logger.error(f"Error during LLM analysis: {e}", exc_info=True)
            # Fallback to basic analysis
            return self._fallback_analysis(contents, len(samples))
    
    async def _analyze_with_llm(
        self,
        contents: List[str],
        context_type: Optional[str]
    ) -> Dict[str, Any]:
        """
        Use LLM to analyze writing style.
        
        Args:
            contents: List of writing sample contents
            context_type: Context type for focused analysis
            
        Returns:
            Dict of style attributes
        """
        from api.services.model_usage_service import ModelUsageService
        from api.dependencies import get_model_service
        from api.core.models.model_types import ModelCapability
        from api.core.models.preferences import Preferences
        
        # Get user's preferred reasoning model
        preferences = Preferences.load()
        preferred_model_id = preferences.models.reasoning_model if preferences else None
        
        # Prepare samples for analysis (limit to prevent token overflow)
        sample_texts = contents[:10]  # Analyze up to 10 samples
        combined_text = "\n\n---SAMPLE---\n\n".join(sample_texts)
        
        # Truncate if too long
        max_chars = 8000
        if len(combined_text) > max_chars:
            combined_text = combined_text[:max_chars] + "\n\n[...truncated]"
        
        context_description = {
            'email_reply': 'email replies',
            'email_compose': 'email compositions',
            'social_media': 'social media posts',
            'document': 'document writing',
            'slack': 'Slack messages'
        }.get(context_type, 'general writing')
        
        prompt = f"""Analyze the following writing samples from {context_description} and extract the author's communication style.

WRITING SAMPLES:
{combined_text}

Analyze these samples and provide a detailed style profile in JSON format with the following structure:

{{
  "formality_level": <float 0.0-1.0, where 0.0=very casual, 0.5=professional, 1.0=very formal>,
  "avg_sentence_length": <float, average words per sentence>,
  "greeting_patterns": [<list of common greetings used, max 5>],
  "closing_patterns": [<list of common closings used, max 5>],
  "common_phrases": [<list of frequently used phrases, max 10>],
  "vocabulary_complexity": "<simple|conversational|professional|advanced>",
  "uses_contractions": <boolean>,
  "uses_emojis": <boolean>,
  "paragraph_structure": "<short|varied|long>",
  "tone_markers": [<list of 2-4 tone descriptors like "concise", "warm", "technical", "friendly", "direct">],
  "avg_word_length": <float, average characters per word>,
  "style_summary": "<2-3 sentence natural language summary of the writing style>"
}}

ANALYSIS GUIDELINES:
- Be precise with formality_level based on actual language use, not assumptions
- Identify actual patterns from the samples, not generic descriptions
- Focus on what makes this person's writing distinctive
- Consider sentence structure, word choice, punctuation, and flow
- Return ONLY valid JSON, no explanations or markdown"""

        # Get model service
        model_service = get_model_service()
        model_usage_service = ModelUsageService(model_service)
        
        # Use user's preferred reasoning model for analysis
        model = await model_usage_service.get_model_for_task(
            capabilities={ModelCapability.REASONING},
            explicit_model_id=preferred_model_id
        )
        
        if not model:
            raise Exception("No reasoning model available for style analysis")
        
        # Generate analysis
        metadata = model.get_metadata()
        self.logger.info(f"Using {metadata.name} for style analysis (user preference: {preferred_model_id or 'default'})")
        response = await model.generate_async(prompt=prompt, max_tokens=1000)
        
        # Parse JSON response
        try:
            # Extract JSON from response (handle markdown code blocks)
            response_text = response.strip()
            if response_text.startswith('```'):
                # Remove markdown code blocks
                lines = response_text.split('\n')
                response_text = '\n'.join(lines[1:-1]) if len(lines) > 2 else response_text
                if response_text.startswith('json'):
                    response_text = response_text[4:].strip()
            
            style_data = json.loads(response_text)
            
            # Validate and clean the response
            return self._validate_style_data(style_data)
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse LLM response as JSON: {e}")
            self.logger.debug(f"Response was: {response[:500]}")
            raise
    
    def _validate_style_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and clean style data from LLM."""
        # Ensure required fields exist with defaults
        validated = {
            'formality_level': max(0.0, min(1.0, float(data.get('formality_level', 0.5)))),
            'avg_sentence_length': float(data.get('avg_sentence_length', 15.0)),
            'greeting_patterns': data.get('greeting_patterns', [])[:5],
            'closing_patterns': data.get('closing_patterns', [])[:5],
            'common_phrases': data.get('common_phrases', [])[:10],
            'vocabulary_complexity': data.get('vocabulary_complexity', 'professional'),
            'uses_contractions': bool(data.get('uses_contractions', True)),
            'uses_emojis': bool(data.get('uses_emojis', False)),
            'paragraph_structure': data.get('paragraph_structure', 'varied'),
            'tone_markers': data.get('tone_markers', [])[:4],
            'avg_word_length': float(data.get('avg_word_length', 5.0)),
        }
        
        # Add style summary if provided
        if 'style_summary' in data:
            validated['style_summary'] = data['style_summary']
        
        return validated
    
    def _fallback_analysis(self, contents: List[str], sample_count: int) -> Dict[str, Any]:
        """
        Fallback to basic statistical analysis if LLM fails.
        
        This is a simplified version that doesn't try to be smart about style,
        just provides basic metrics.
        """
        self.logger.warning("Using fallback analysis (LLM unavailable)")
        
        total_words = 0
        total_sentences = 0
        total_chars = 0
        
        for content in contents:
            words = content.split()
            total_words += len(words)
            total_chars += sum(len(w) for w in words)
            
            # Simple sentence count
            sentences = content.count('.') + content.count('!') + content.count('?')
            total_sentences += max(sentences, 1)
        
        avg_sentence_length = total_words / max(total_sentences, 1)
        avg_word_length = total_chars / max(total_words, 1)
        
        confidence = self._calculate_confidence(sample_count)
        
        return {
            'style_attributes': {
                'formality_level': 0.5,  # Neutral
                'avg_sentence_length': avg_sentence_length,
                'greeting_patterns': [],
                'closing_patterns': [],
                'common_phrases': [],
                'vocabulary_complexity': 'professional',
                'uses_contractions': True,
                'uses_emojis': False,
                'paragraph_structure': 'varied',
                'tone_markers': [],
                'avg_word_length': avg_word_length,
                'style_summary': 'Basic statistical analysis only (LLM analysis unavailable)'
            },
            'confidence': confidence * 0.5,  # Lower confidence for fallback
            'sample_count': sample_count,
            'analyzed_at': datetime.utcnow().isoformat() + "Z"
        }
    
    def _calculate_confidence(self, sample_count: int) -> float:
        """
        Calculate confidence score based on sample size.
        
        Confidence increases with more samples:
        - 1-2 samples: 0.3 confidence
        - 3-5 samples: 0.5 confidence
        - 6-10 samples: 0.7 confidence
        - 11-20 samples: 0.85 confidence
        - 21+ samples: 0.95 confidence
        """
        if sample_count <= 2:
            return 0.3
        elif sample_count <= 5:
            return 0.5
        elif sample_count <= 10:
            return 0.7
        elif sample_count <= 20:
            return 0.85
        else:
            return 0.95
    
    def _get_default_style(self) -> Dict[str, Any]:
        """Return default style attributes when no samples available."""
        return {
            'style_attributes': {
                'formality_level': 0.5,
                'avg_sentence_length': 15.0,
                'greeting_patterns': [],
                'closing_patterns': [],
                'common_phrases': [],
                'vocabulary_complexity': 'professional',
                'uses_contractions': True,
                'uses_emojis': False,
                'paragraph_structure': 'varied',
                'tone_markers': [],
                'avg_word_length': 5.0,
            },
            'confidence': 0.0,
            'sample_count': 0,
            'analyzed_at': datetime.utcnow().isoformat() + "Z"
        }
