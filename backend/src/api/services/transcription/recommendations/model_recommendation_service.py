"""Service for recommending models based on user preferences and system capabilities."""

import logging
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

from ....core.models.models_registry import (
    get_transcription_models,
    get_local_reasoning_models,
)
from ....core.models.gpu_manager import GPUManager
from ....core.runtime.hardware_capability_service import (
    HardwareCapabilityProfile,
    HardwareCapabilityService,
)


class UserPreference(Enum):
    """User preference for speed vs accuracy tradeoff."""
    SPEED_FOCUSED = "speed"      # Prioritize fast response times
    BALANCED = "balanced"        # Balance between speed and accuracy
    ACCURACY_FOCUSED = "accuracy"  # Prioritize highest accuracy
    PRIVACY_FOCUSED = "privacy"   # Prioritize local models for privacy


class ModelRecommendation:
    """Represents a model recommendation with reasoning."""
    
    def __init__(
        self,
        model_type: str,
        variant: str,
        model_info: Dict[str, Any],
        score: float,
        reasoning: List[str]
    ):
        self.model_type = model_type
        self.variant = variant
        self.model_info = model_info
        self.score = score
        self.reasoning = reasoning
        
    @property
    def model_id(self) -> str:
        """Get the full model ID in format 'ModelType/variant'."""
        return f"{self.model_type}/{self.variant}"
        
    @property
    def display_name(self) -> str:
        """Get the display name of the model."""
        return self.model_info.get("name", f"{self.model_type} {self.variant}")
        
    @property
    def size(self) -> str:
        """Get the model size."""
        return self.model_info.get("size", "Unknown")
        
    @property
    def description(self) -> str:
        """Get the model description."""
        return self.model_info.get("description", "")
        
    @property
    def speed_rating(self) -> int:
        """Get the speed rating (1-10, higher is faster)."""
        return self.model_info.get("speed_rating", 5)
        
    @property
    def accuracy_rating(self) -> int:
        """Get the accuracy rating (1-10, higher is more accurate)."""
        return self.model_info.get("accuracy_rating", 5)
        
    @property
    def recommended_ram(self) -> str:
        """Get the recommended RAM requirement."""
        return self.model_info.get("recommended_ram", "Unknown")


class ModelRecommendationService:
    """Service for recommending models based on user preferences and system capabilities."""
    
    def __init__(self, hardware_service: Optional[HardwareCapabilityService] = None):
        self.logger = logging.getLogger(__name__)
        self.hardware_service = hardware_service or HardwareCapabilityService(
            gpu_manager_factory=GPUManager
        )
        self.hardware_profile = self.hardware_service.get_profile()
        self.system_capabilities = self._detect_system_capabilities()
        
    def _detect_system_capabilities(self) -> Dict[str, Any]:
        """Detect system capabilities including RAM and GPU."""
        capabilities = {
            "total_ram_gb": self.hardware_profile.total_ram_gb,
            "is_apple_silicon": self.hardware_profile.is_apple_silicon,
            "gpu_available": self.hardware_profile.gpu_available,
            "gpu_backend": self.hardware_profile.gpu_backend,
        }
        self.logger.info(f"Detected system capabilities: {capabilities}")
        return capabilities
        
    def _parse_ram_requirement(self, ram_str: str) -> int:
        """Parse RAM requirement string to GB integer."""
        try:
            # Extract number from strings like "8GB", "16 GB", etc.
            import re
            match = re.search(r'(\d+)', ram_str)
            if match:
                return int(match.group(1))
        except Exception:
            pass
        return 16  # Default fallback
        
    def _calculate_model_score(
        self, 
        model_info: Dict[str, Any], 
        preference: UserPreference,
        system_compatible: bool
    ) -> Tuple[float, List[str]]:
        """Calculate a score for how well a model matches preferences and capabilities."""
        speed_rating = model_info.get("speed_rating", 5)
        accuracy_rating = model_info.get("accuracy_rating", 5)
        reasoning = []
        
        # Base score calculation based on preference
        if preference == UserPreference.SPEED_FOCUSED:
            # Heavily weight speed, some accuracy consideration
            base_score = (speed_rating * 0.8) + (accuracy_rating * 0.2)
            reasoning.append(f"Speed-focused: speed={speed_rating}/10, accuracy={accuracy_rating}/10")
        elif preference == UserPreference.ACCURACY_FOCUSED:
            # Heavily weight accuracy, some speed consideration
            base_score = (accuracy_rating * 0.8) + (speed_rating * 0.2)
            reasoning.append(f"Accuracy-focused: accuracy={accuracy_rating}/10, speed={speed_rating}/10")
        elif preference == UserPreference.PRIVACY_FOCUSED:
            # For privacy, we need additional context about whether this is a local or API model
            # This will be handled in the specific recommendation methods
            base_score = (speed_rating * 0.3) + (accuracy_rating * 0.7)
            reasoning.append(f"Privacy-focused: prioritizing local models")
        else:  # BALANCED
            # Equal weight to both
            base_score = (speed_rating * 0.5) + (accuracy_rating * 0.5)
            reasoning.append(f"Balanced: speed={speed_rating}/10, accuracy={accuracy_rating}/10")
            
        # System compatibility adjustments
        if not system_compatible:
            base_score *= 0.3  # Heavily penalize incompatible models
            reasoning.append("⚠️ May not be compatible with your system")
        else:
            reasoning.append("✅ Compatible with your system")
            
        # GPU acceleration bonus
        supports_gpu = model_info.get("supports_gpu", False)
        if supports_gpu and self.system_capabilities["gpu_available"]:
            base_score *= 1.1  # 10% bonus for GPU acceleration
            reasoning.append(f"🚀 GPU acceleration available ({self.system_capabilities['gpu_backend']})")

        profile: Optional[HardwareCapabilityProfile] = getattr(self, "hardware_profile", None)
        if profile:
            handler = str(model_info.get("handler", ""))
            provider = str(model_info.get("provider", ""))
            if handler == "parakeet" and profile.prefer_coreml_onnx:
                base_score *= 1.15
                reasoning.append("CoreML acceleration is available for Parakeet on this Apple Silicon Mac")
            if handler == "whisper" and profile.prefer_mlx_whisper:
                base_score *= 1.1
                reasoning.append("MLX Whisper is available for Apple Silicon transcription acceleration")
            if (
                handler == "whisper"
                and profile.is_apple_silicon
                and profile.faster_whisper_available
                and not profile.mlx_whisper_available
            ):
                reasoning.append(
                    "Faster-Whisper is available, but it is CPU-bound on Apple Silicon without MLX Whisper"
                )
            
        return base_score, reasoning
        
    def _is_model_system_compatible(self, model_info: Dict[str, Any]) -> bool:
        """Check if a model is compatible with the current system."""
        required_ram = self._parse_ram_requirement(model_info.get("recommended_ram", "16GB"))
        available_ram = self.system_capabilities["total_ram_gb"]
        
        # Allow models that require up to 90% of available RAM
        ram_compatible = required_ram <= (available_ram * 0.9)
        
        return ram_compatible
        
    def recommend_transcription_models(
        self, 
        preference: UserPreference,
        max_recommendations: int = 3
    ) -> List[ModelRecommendation]:
        """
        Recommend transcription models based on user preference and system capabilities.
        
        Args:
            preference: User preference for speed vs accuracy tradeoff
            max_recommendations: Maximum number of recommendations to return
            
        Returns:
            List of ModelRecommendation objects, sorted by score (best first)
        """
        recommendations = []
        
        self.logger.info(f"Generating recommendations for preference: {preference.value}")
        self.logger.info(f"System capabilities: {self.system_capabilities}")
        
        # Iterate through all transcription models from the registry.
        for model_id, model_info in get_transcription_models().items():
            # Parse model_id to extract provider and variant.
            if "-" in model_id:
                provider, variant = model_id.split("-", 1)
            else:
                provider = model_id
                variant = model_id
            
            # Build legacy-compatible model_info for recommendation.
            compat_model_info = {
                "name": model_info.get("display_name", model_id),
                "size": model_info.get("size", "Unknown"),
                "description": model_info.get("description", ""),
                "speed_rating": model_info.get("speed_rating", 5),
                "accuracy_rating": model_info.get("accuracy_rating", 5),
                "recommended_ram": model_info.get("recommended_ram", "8GB"),
                "supports_gpu": "gpu_acceleration" in model_info.get("features", []),
                "handler": model_info.get("handler", ""),
                "provider": model_info.get("provider", ""),
            }
                
            # Skip models without speed/accuracy ratings.
            if "speed_rating" not in model_info or "accuracy_rating" not in model_info:
                continue
                
            # Check system compatibility.
            system_compatible = self._is_model_system_compatible(compat_model_info)
            
            # Calculate score.
            score, reasoning = self._calculate_model_score(
                compat_model_info, preference, system_compatible
            )
            
            # Special handling for privacy preference.
            if preference == UserPreference.PRIVACY_FOCUSED:
                # All transcription models in registry are local models.
                score *= 1.2  # 20% bonus for being local.
                reasoning.append("✅ Completely private - all processing happens locally")
                reasoning.append("✅ No data sent to external servers")
                reasoning.append("✅ Works offline")
            
            # Create recommendation.
            recommendation = ModelRecommendation(
                model_type=provider,
                variant=variant,
                model_info=compat_model_info,
                score=score,
                reasoning=reasoning
            )
            recommendations.append(recommendation)
            self.logger.debug(
                f"Model {recommendation.model_id}: score={score:.2f}, "
                f"speed={recommendation.speed_rating}, accuracy={recommendation.accuracy_rating}"
            )
        
        # Sort by score (highest first) and limit results
        recommendations.sort(key=lambda x: x.score, reverse=True)
        top_recommendations = recommendations[:max_recommendations]
        
        self.logger.info(f"Top {len(top_recommendations)} recommendations:")
        for i, rec in enumerate(top_recommendations, 1):
            self.logger.info(
                f"{i}. {rec.display_name} (score: {rec.score:.2f}, "
                f"speed: {rec.speed_rating}, accuracy: {rec.accuracy_rating})"
            )
            
        return top_recommendations
        
    def recommend_reasoning_models(
        self, 
        preference: UserPreference,
        max_recommendations: int = 3
    ) -> List[ModelRecommendation]:
        """
        Recommend reasoning models based on user preference and system capabilities.
        
        Args:
            preference: User preference for speed vs accuracy tradeoff
            max_recommendations: Maximum number of recommendations to return
            
        Returns:
            List of ModelRecommendation objects, sorted by score (best first)
        """
        recommendations = []
        
        self.logger.info(f"Generating reasoning model recommendations for preference: {preference.value}")
        self.logger.info(f"System capabilities: {self.system_capabilities}")
        
        # Iterate through all local reasoning models from the registry.
        for model_id, model_info in get_local_reasoning_models().items():
            # Parse model_id to extract provider and variant.
            if "-" in model_id:
                provider, variant = model_id.split("-", 1)
            else:
                provider = model_id
                variant = model_id
            
            # Build legacy-compatible model_info for recommendation.
            compat_model_info = {
                "name": model_info.get("display_name", model_id),
                "size": model_info.get("size", "Unknown"),
                "description": model_info.get("description", ""),
                "speed_rating": model_info.get("speed_rating", 5),
                "accuracy_rating": model_info.get("accuracy_rating", 5),
                "recommended_ram": model_info.get("recommended_ram", "8GB"),
                "supports_gpu": "gpu_acceleration" in model_info.get("features", []),
                "handler": model_info.get("handler", ""),
                "provider": model_info.get("provider", ""),
            }
                
            # Skip models without speed/accuracy ratings.
            if "speed_rating" not in model_info or "accuracy_rating" not in model_info:
                continue
                
            # Check system compatibility.
            system_compatible = self._is_model_system_compatible(compat_model_info)
            
            # Calculate score with privacy consideration.
            score, reasoning = self._calculate_model_score(
                compat_model_info, preference, system_compatible
            )
            
            # Special handling for privacy preference.
            if preference == UserPreference.PRIVACY_FOCUSED:
                # All local reasoning models in registry are local.
                score *= 1.2  # 20% bonus for being local.
                reasoning.append("✅ Completely private - all processing happens locally")
                reasoning.append("✅ No data sent to external servers")
                reasoning.append("✅ Works offline")
            
            # Create recommendation.
            recommendation = ModelRecommendation(
                model_type=provider,
                variant=variant,
                model_info=compat_model_info,
                score=score,
                reasoning=reasoning
            )
            recommendations.append(recommendation)
            self.logger.debug(
                f"Model {recommendation.model_id}: score={score:.2f}, "
                f"speed={recommendation.speed_rating}, accuracy={recommendation.accuracy_rating}"
            )
        
        # Sort by score (highest first) and limit results
        recommendations.sort(key=lambda x: x.score, reverse=True)
        top_recommendations = recommendations[:max_recommendations]
        
        self.logger.info(f"Top {len(top_recommendations)} reasoning recommendations:")
        for i, rec in enumerate(top_recommendations, 1):
            self.logger.info(
                f"{i}. {rec.display_name} (score: {rec.score:.2f}, "
                f"speed: {rec.speed_rating}, accuracy: {rec.accuracy_rating})"
            )
            
        return top_recommendations
        
    def get_system_info(self) -> Dict[str, Any]:
        """Get system information for display in onboarding."""
        return self.hardware_profile.as_legacy_system_info()
        
    def explain_recommendation(self, recommendation: ModelRecommendation) -> str:
        """Generate a human-readable explanation for why a model was recommended."""
        explanation_parts = [
            f"**{recommendation.display_name}** is recommended because:"
        ]
        
        explanation_parts.extend([f"• {reason}" for reason in recommendation.reasoning])
        
        # Add additional context
        explanation_parts.extend([
            f"• Model size: {recommendation.size}",
            f"• RAM requirement: {recommendation.recommended_ram}",
            f"• Speed rating: {recommendation.speed_rating}/10",
            f"• Accuracy rating: {recommendation.accuracy_rating}/10"
        ])
        
        return "\n".join(explanation_parts) 