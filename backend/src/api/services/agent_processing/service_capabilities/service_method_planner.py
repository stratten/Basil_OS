"""
Service Method Planner

Performs upfront analysis of available services and caches their method signatures,
parameters, and capabilities during the planning phase. This eliminates the need
to repeatedly discover service capabilities during todo execution.

Key responsibilities:
1. Retrieve all service capabilities once during planning
2. Cache method signatures and parameter requirements  
3. Provide cached capability data to todo construction
4. Enable efficient execution without repeated capability discovery
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ServiceMethodSignature:
    """Cached signature information for a service method."""
    service_name: str
    method_name: str
    parameters: Dict[str, Any]  # Parameter definitions from introspection
    signature_string: str
    documentation: str
    execution_principles: List[str] = field(default_factory=list)


@dataclass
class ServiceCapabilityCache:
    """Complete cached capability information for all available services."""
    services: Dict[str, Dict[str, Any]]  # Full service definitions
    method_signatures: Dict[str, List[ServiceMethodSignature]]  # Methods by service
    retrieval_timestamp: float
    total_services: int
    total_methods: int


class ServiceMethodPlanner:
    """
    Handles upfront service capability discovery and caching to eliminate 
    repeated capability retrieval during todo execution.
    """
    
    def __init__(self, service_capability_analyzer):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.service_capability_analyzer = service_capability_analyzer
        self._capability_cache: Optional[ServiceCapabilityCache] = None
        
    async def plan_service_capabilities(self) -> ServiceCapabilityCache:
        """
        Perform upfront discovery of all service capabilities and cache them.
        This is the main entry point that eliminates repeated capability discovery.
        
        Returns:
            ServiceCapabilityCache with all service method signatures
        """
        self.logger.info("🔧 PLANNING SERVICE CAPABILITIES...")
        
        # Discover all available services and their capabilities
        services = self.service_capability_analyzer.discover_available_services()
        
        # Extract and cache method signatures
        method_signatures = self._extract_method_signatures(services)
        
        # Create capability cache
        import time
        self._capability_cache = ServiceCapabilityCache(
            services=services,
            method_signatures=method_signatures,
            retrieval_timestamp=time.time(),
            total_services=len(services),
            total_methods=sum(len(methods) for methods in method_signatures.values())
        )
        
        self.logger.info(f"✅ CACHED CAPABILITIES: {self._capability_cache.total_services} services, {self._capability_cache.total_methods} methods")
        
        return self._capability_cache
    
    def get_cached_capabilities(self) -> Optional[ServiceCapabilityCache]:
        """Get the current capability cache if available."""
        return self._capability_cache
    
    def get_service_methods(self, service_name: str) -> List[ServiceMethodSignature]:
        """Get cached method signatures for a specific service."""
        if not self._capability_cache:
            return []
        
        return self._capability_cache.method_signatures.get(service_name, [])
    
    def get_method_signature(self, service_name: str, method_name: str) -> Optional[ServiceMethodSignature]:
        """Get a specific cached method signature."""
        service_methods = self.get_service_methods(service_name)
        
        for method_sig in service_methods:
            if method_sig.method_name == method_name:
                return method_sig
        
        return None
    
    def get_all_available_services(self) -> Dict[str, Dict[str, Any]]:
        """Get all cached service definitions."""
        if not self._capability_cache:
            return {}
        
        return self._capability_cache.services
    
    def _extract_method_signatures(self, services: Dict[str, Any]) -> Dict[str, List[ServiceMethodSignature]]:
        """Extract method signatures from service capability data."""
        method_signatures = {}
        
        for service_name, service_info in services.items():
            signatures = []
            capabilities = service_info.get("capabilities", {})
            # Try both "supported_methods" (AppleScript) and "methods" (other services) for compatibility
            methods = capabilities.get("supported_methods", capabilities.get("methods", {}))
            execution_principles = capabilities.get("execution_principles", [])
            
            self.logger.info(f"🔍 EXTRACTING SIGNATURES: {service_name} ({len(methods)} methods)")
            
            for method_name, method_info in methods.items():
                signature = ServiceMethodSignature(
                    service_name=service_name,
                    method_name=method_name,
                    parameters=method_info.get("parameters", {}),
                    signature_string=method_info.get("signature", ""),
                    documentation=method_info.get("doc", ""),
                    execution_principles=execution_principles
                )
                signatures.append(signature)
                
                self.logger.debug(f"   📝 {method_name}: {signature.signature_string}")
            
            method_signatures[service_name] = signatures
        
        return method_signatures
    
    def format_capabilities_for_planning(self) -> str:
        """Format cached capabilities for use in LLM planning prompts."""
        if not self._capability_cache:
            return "No service capabilities cached"
        
        formatted_sections = []
        
        for service_name, signatures in self._capability_cache.method_signatures.items():
            service_info = self._capability_cache.services.get(service_name, {})
            
            section = f"## {service_name}\n"
            section += f"Description: {service_info.get('description', 'No description')}\n"
            
            if signatures:
                section += "Methods:\n"
                for sig in signatures:
                    section += f"  - {sig.method_name}{sig.signature_string}\n"
                    if sig.documentation and sig.documentation != "No documentation available":
                        section += f"    {sig.documentation}\n"
            
            # Add execution principles if available
            capabilities = service_info.get("capabilities", {})
            execution_principles = capabilities.get("execution_principles", [])
            if execution_principles:
                section += "Execution Principles:\n"
                for principle in execution_principles:
                    section += f"  - {principle}\n"
            
            formatted_sections.append(section)
        
        return "\n".join(formatted_sections)
    
    def is_cache_valid(self, max_age_seconds: int = 300) -> bool:
        """Check if the current cache is still valid (not too old)."""
        if not self._capability_cache:
            return False
        
        import time
        age = time.time() - self._capability_cache.retrieval_timestamp
        return age < max_age_seconds
    
    def invalidate_cache(self):
        """Manually invalidate the capability cache."""
        self.logger.info("🗑️ INVALIDATING SERVICE CAPABILITY CACHE")
        self._capability_cache = None 