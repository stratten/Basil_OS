"""
Service Capability Analyzer for Enhanced Agent Processing

This module handles service discovery, capability analysis, and service introspection
for the enhanced agent processing system. Replaces the deprecated version in @/agent folder.

Key responsibilities:
1. Dynamic service discovery (email service, router services)
2. Method signature introspection using Python's inspect module
3. Service capability extraction and caching
4. Router method discovery and analysis
5. Parameter validation and method correction
"""

import logging
import inspect
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ServiceCapabilityAnalyzer:
    """
    Manages service discovery and capability analysis for the enhanced agent processing system.
    
    This is a clean replacement for the deprecated service capability analyzer that fits
    with the new agent processing architecture.
    """
    
    def __init__(self, email_service=None, router=None, file_service=None, applescript_service=None, shell_service=None):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.email_service = email_service
        self.router = router
        self.file_service = file_service
        self.applescript_service = applescript_service
        self.shell_service = shell_service
        
    def discover_available_services(self) -> Dict[str, Any]:
        """
        Main entry point for service discovery. Dynamically discovers all available 
        services and their capabilities using actual introspection.
        
        Returns:
            Dictionary with service names as keys and capability info as values
        """
        self.logger.info("🔍 STARTING SERVICE DISCOVERY...")
        services = {}
        
        # Email service discovery
        if self.email_service:
            self.logger.info("📧 DISCOVERING EMAIL SERVICE...")
            capabilities = self._get_email_service_capabilities()
            if capabilities:
                services["email_service"] = {
                    "description": "Email operations (read, search, compose, send, organize)",
                    "methods": list(capabilities.get("methods", {}).keys()),
                    "capabilities": capabilities
                }
                self.logger.info(f"✅ EMAIL SERVICE DISCOVERED: {len(capabilities.get('methods', {}))} methods")
            else:
                self.logger.warning("⚠️ EMAIL SERVICE CAPABILITIES NOT AVAILABLE")
        else:
            self.logger.warning("⚠️ EMAIL SERVICE NOT AVAILABLE")

        # File service discovery (if available)
        if self.file_service:
            self.logger.info("📁 DISCOVERING FILE SERVICE...")
            file_capabilities = self._get_file_service_capabilities()
            if file_capabilities:
                services["file_service"] = {
                    "description": "File system operations (search, retrieval, context detection)",
                    "methods": list(file_capabilities.get("methods", {}).keys()),
                    "capabilities": file_capabilities
                }
                self.logger.info(f"✅ FILE SERVICE DISCOVERED: {len(file_capabilities.get('methods', {}))} methods")
            else:
                self.logger.warning("⚠️ FILE SERVICE CAPABILITIES NOT AVAILABLE")
        else:
            self.logger.warning("⚠️ FILE SERVICE NOT AVAILABLE")
        
        # AppleScript service discovery (if available)
        if self.applescript_service:
            self.logger.info("🍎 DISCOVERING APPLESCRIPT SERVICE...")
            applescript_capabilities = self._get_applescript_service_capabilities()
            if applescript_capabilities:
                # Extract methods from supported_methods key (not "methods")
                supported_methods = applescript_capabilities.get("supported_methods", {})
                services["applescript_service"] = {
                    "description": "Dynamic AppleScript generation and execution for unlimited macOS automation",
                    "methods": list(supported_methods.keys()),
                    "capabilities": applescript_capabilities
                }
                self.logger.info(f"✅ APPLESCRIPT SERVICE DISCOVERED: {len(supported_methods)} methods")
            else:
                self.logger.warning("⚠️ APPLESCRIPT SERVICE CAPABILITIES NOT AVAILABLE")
        else:
            self.logger.warning("⚠️ APPLESCRIPT SERVICE NOT AVAILABLE")

        # Shell service discovery (if available)
        if self.shell_service:
            self.logger.info("🐚 DISCOVERING SHELL SERVICE...")
            shell_capabilities = self._get_shell_service_capabilities()
            if shell_capabilities:
                services["shell_service"] = {
                    "description": "Secure shell execution (non-interactive CLI)",
                    "methods": list(shell_capabilities.get("methods", {}).keys()),
                    "capabilities": shell_capabilities
                }
                self.logger.info(f"✅ SHELL SERVICE DISCOVERED: {len(shell_capabilities.get('methods', {}))} methods")
            else:
                self.logger.warning("⚠️ SHELL SERVICE CAPABILITIES NOT AVAILABLE")
        else:
            self.logger.warning("⚠️ SHELL SERVICE NOT AVAILABLE")
        
        # Router services discovery
        if self.router:
            self.logger.info("🔀 DISCOVERING ROUTER SERVICES...")
            router_services = self._discover_router_services()
            services.update(router_services)
        else:
            self.logger.info("Router service discovery disabled; agent tasks route directly to agent")
        
        self.logger.info(f"🔍 DISCOVERED SERVICES: {list(services.keys())}")
        for service_name, service_info in services.items():
            self.logger.info(f"   {service_name}: {service_info.get('methods', [])}")
        
        # Service discovery complete
        
        return services

    def _get_file_service_capabilities(self) -> Dict[str, Any]:
        """Get file service capabilities by calling the service's capability method and normalizing the format."""
        try:
            if not self.file_service:
                return {}

            capabilities = self.file_service.get_service_capabilities()
            self.logger.info("📋 FILE SERVICE CAPABILITIES RETRIEVED")

            # Convert methods list (from FileSystemService) into analyzer's mapping format
            normalized_methods: Dict[str, Any] = {}
            for method_info in capabilities.get("methods", []):
                method_name = method_info.get("name")
                if not method_name:
                    continue

                # Convert parameter list into mapping
                parameters: Dict[str, Any] = {}
                for param in method_info.get("parameters", []):
                    param_name = param.get("name")
                    if not param_name:
                        continue
                    parameters[param_name] = {
                        "type": param.get("type", "Any"),
                        "required": param.get("required", False),
                        "description": param.get("description", "")
                    }

                # Build a readable signature
                try:
                    signature_params = ", ".join([
                        f"{p.get('name')}: {p.get('type', 'Any')}" for p in method_info.get("parameters", [])
                    ])
                except Exception:
                    signature_params = "..."

                normalized_methods[method_name] = {
                    "signature": f"{method_name}({signature_params})",
                    "parameters": parameters,
                    "doc": method_info.get("description", ""),
                    "slim_doc": method_info.get("slim_doc", ""),
                    "returns": method_info.get("returns", ""),
                    "use_cases": method_info.get("use_cases", [])
                }

            return {
                "methods": normalized_methods,
                "description": capabilities.get("description", ""),
                "features": capabilities.get("features", []),
                "supported_applications": capabilities.get("supported_applications", ""),
                "execution_principles": [
                    "File paths are automatically resolved from search results",
                ]
            }

        except Exception as e:
            self.logger.error(f"❌ ERROR GETTING FILE SERVICE CAPABILITIES: {e}", exc_info=True)
            return {}

    def _get_shell_service_capabilities(self) -> Dict[str, Any]:
        """Get shell service capabilities by calling the service's capability method."""
        try:
            if not self.shell_service:
                return {}

            capabilities = self.shell_service.get_service_capabilities()
            self.logger.info("📋 SHELL SERVICE CAPABILITIES RETRIEVED")

            # Shell service already returns analyzer-friendly mapping under 'methods'
            # Ensure structure is present
            methods = capabilities.get("methods", {})
            if not isinstance(methods, dict):
                self.logger.warning("⚠️ SHELL SERVICE methods not in expected mapping format; skipping")
                return {}

            return capabilities

        except Exception as e:
            self.logger.error(f"❌ ERROR GETTING SHELL SERVICE CAPABILITIES: {e}", exc_info=True)
            return {}
    
    def _get_email_service_capabilities(self) -> Dict[str, Any]:
        """Get email service capabilities by calling the service's capability method."""
        try:
            if not self.email_service:
                return {}
            
            capabilities = self.email_service.get_service_capabilities()
            self.logger.info(f"📋 EMAIL SERVICE CAPABILITIES RETRIEVED:")
            self.logger.info(f"   Methods: {list(capabilities.get('methods', {}).keys())}")
            self.logger.info(f"   Data Structures: {list(capabilities.get('data_structures', {}).keys())}")
            
            # Log detailed method information
            methods = capabilities.get('methods', {})
            for method_name, method_info in methods.items():
                if isinstance(method_info, dict):
                    signature = method_info.get('signature', f"{method_name}(...)")
                    parameters = method_info.get('parameters', {})
                    self.logger.info(f"   📋 METHOD: {method_name}{signature[signature.find('('):]}")
                    for param_name, param_info in parameters.items():
                        param_type = param_info.get('type', 'Any')
                        required = param_info.get('required', False)
                        default = param_info.get('default', None)
                        self.logger.info(f"     🔧 PARAM: {param_name}: {param_type} (required={required}, default={default})")
            
            # Log execution principles
            execution_principles = capabilities.get('execution_principles', [])
            for principle in execution_principles:
                self.logger.info(f"   🚨 EXECUTION PRINCIPLE: {principle}")
            
            return capabilities
            
        except Exception as e:
            self.logger.error(f"❌ ERROR GETTING EMAIL SERVICE CAPABILITIES: {e}", exc_info=True)
            return {}
    
    def _get_applescript_service_capabilities(self) -> Dict[str, Any]:
        """Get AppleScript service capabilities by calling the service's capability method."""
        try:
            if not self.applescript_service:
                return {}
            
            capabilities = self.applescript_service.get_service_capabilities()
            self.logger.info(f"🍎 APPLESCRIPT SERVICE CAPABILITIES RETRIEVED:")
            self.logger.info(f"   Methods: {list(capabilities.get('supported_methods', {}).keys())}")
            
            # Log detailed method information
            methods = capabilities.get('supported_methods', {})
            for method_name, method_info in methods.items():
                if isinstance(method_info, dict):
                    self.logger.info(f"   🍎 METHOD: {method_name}")
                    parameters = method_info.get('parameters', {})
                    for param_name, param_info in parameters.items():
                        param_type = param_info.get('type', 'Any')
                        required = param_info.get('required', False)
                        self.logger.info(f"     🔧 PARAM: {param_name}: {param_type} (required={required})")
            
            # Log automation capabilities
            automation_capabilities = capabilities.get('automation_capabilities', [])
            for capability in automation_capabilities:
                self.logger.info(f"   🍎 AUTOMATION: {capability}")
            
            # Log execution principles
            execution_principles = capabilities.get('execution_principles', [])
            for principle in execution_principles:
                self.logger.info(f"   🚨 EXECUTION PRINCIPLE: {principle}")
            
            return capabilities
            
        except Exception as e:
            self.logger.error(f"❌ ERROR GETTING APPLESCRIPT SERVICE CAPABILITIES: {e}", exc_info=True)
            return {}
    
    def _discover_router_services(self) -> Dict[str, Any]:
        """Discover router services by introspecting router methods."""
        router_services = {}
        
        try:
            # Get available services from router
            available_services = self.router._get_available_services()
            self.logger.info(f"📋 ROUTER REPORTS AVAILABLE SERVICES: {list(available_services.keys())}")
            
            # Create a single comprehensive router service with all methods
            router_service_capabilities = {
                "description": "Comprehensive router service for all operations",
                "methods": {},
                "execution_principles": [],
                "usage_examples": {}
            }
            
            service_operation_mapping = {
                "suggestion_generation": "_execute_suggestions",
                "screen_operations": "_execute_screen_capture",
                "activity_queries": "_execute_activity_query",
                # NOTE: "knowledge_queries" removed - no longer exposed as a service/tool
                "conversation_analysis": "_execute_conversation_analysis",
                "agent_suggestions": "generate_agent_suggestion"  # New simple entry point for agents
            }
            
            # Discover all router methods and combine them into one service
            discovered_methods = 0
            for service_key, service_info in available_services.items():
                if service_key in service_operation_mapping:
                    execution_method_name = service_operation_mapping[service_key]
                    
                    # Check if the router actually has this method
                    if hasattr(self.router, execution_method_name):
                        execution_method = getattr(self.router, execution_method_name)
                        
                        # Introspect the method to discover its capabilities
                        method_capabilities = self._introspect_router_method(
                            execution_method, service_info.get("description", "Router operation")
                        )
                        
                        # Add this method to the combined router service
                        method_info = method_capabilities.get("methods", {})
                        for method_name, method_details in method_info.items():
                            router_service_capabilities["methods"][method_name] = method_details
                        
                        discovered_methods += 1
                        self.logger.info(f"✅ ROUTER METHOD DISCOVERED: {execution_method_name} for {service_key}")
                    else:
                        self.logger.warning(f"⚠️ Router method {execution_method_name} not found for {service_key}")
            
            # Add the combined router service if we found any methods
            if discovered_methods > 0:
                router_services["router_service"] = {
                    "description": f"Router service with {discovered_methods} operations",
                    "methods": list(router_service_capabilities["methods"].keys()),
                    "capabilities": router_service_capabilities
                }
                self.logger.info(f"✅ ROUTER_SERVICE CREATED with {len(router_service_capabilities['methods'])} methods")
            else:
                self.logger.warning("⚠️ No router methods discovered")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to discover router services: {e}", exc_info=True)
            # Log warnings for missing services
            for service_name in ["router_service"]:
                self.logger.warning(f"⚠️ {service_name.upper()} NOT AVAILABLE")
        
        return router_services
    
    def _introspect_router_method(self, method, description: str) -> Dict[str, Any]:
        """Introspect a router method to discover its capabilities."""
        capabilities = {
            "description": description,
            "methods": {},
            "execution_principles": [],
            "usage_examples": {}
        }
        
        try:
            signature = inspect.signature(method)
            parameters = {}
            
            for param_name, param in signature.parameters.items():
                if param_name != 'self':
                    parameters[param_name] = {
                        "type": str(param.annotation) if param.annotation != inspect.Parameter.empty else "Any",
                        "default": str(param.default) if param.default != inspect.Parameter.empty else None,
                        "required": param.default == inspect.Parameter.empty
                    }
            
            capabilities["methods"][method.__name__] = {
                "signature": str(signature),
                "parameters": parameters,
                "doc": method.__doc__ or "No documentation available"
            }
            
            self.logger.info(f"🔍 INTROSPECTED ROUTER METHOD: {method.__name__}{signature}")
            
        except Exception as e:
            self.logger.warning(f"   ⚠️ Could not introspect router method {method.__name__}: {e}")
        
        return capabilities
    
    def validate_service_method(self, service_name: str, method: str, 
                               parameters: Dict[str, Any], cached_services: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any]]:
        """
        Validate service method before execution and suggest corrections if needed.
        
        Args:
            service_name: Name of the service
            method: Method name to validate
            parameters: Method parameters
            cached_services: Pre-cached service capabilities (preferred) or None to discover fresh
            
        Returns:
            Tuple of (corrected_method_name, validated_parameters)
        """
        try:
            # Use cached capabilities if provided, otherwise discover fresh (fallback)
            if cached_services is not None:
                services = cached_services
                self.logger.debug(f"🔧 Using cached capabilities for {service_name}.{method}")
            else:
                self.logger.info(f"🔧 Discovering fresh capabilities for {service_name}.{method} (no cache provided)")
                services = self.discover_available_services()
            
            if service_name not in services:
                self.logger.warning(f"🔧 Service {service_name} not found")
                return method, parameters
            
            service_info = services[service_name]
            capabilities = service_info.get("capabilities", {})
            methods = capabilities.get("methods", {})
            
            if method in methods:
                # Method exists - validate parameters
                self.logger.info(f"✅ METHOD VALIDATED: {service_name}.{method}")
                return method, parameters
            else:
                # Method doesn't exist - try to find correct method
                available_methods = list(methods.keys())
                self.logger.warning(f"🔧 METHOD CORRECTION NEEDED: {service_name}.{method}")
                self.logger.warning(f"🔧 AVAILABLE METHODS: {available_methods}")
                
                # Method name correction was removed - return as-is
                self.logger.error(f"❌ METHOD NOT FOUND: {method} in {available_methods}")
                return method, parameters
                    
        except Exception as e:
            self.logger.warning(f"Method validation failed: {e}")
            return method, parameters
    

    def get_object_construction_info(self, param_type: str, cached_services: Dict[str, Any]) -> str:
        """
        Get object construction information for complex parameter types.
        
        Args:
            param_type: The parameter type string (e.g., 'EmailRequest', 'api.services...EmailRequest')
            cached_services: Cached service capabilities containing data structure info
            
        Returns:
            Object construction guidance string, or empty string if not needed
        """
        try:
            # Extract the actual type name from complex type strings
            # Handle cases like 'api.services...EmailRequest' -> 'EmailRequest'
            if '.' in param_type:
                type_name = param_type.split('.')[-1]
            else:
                type_name = param_type
                
            # Remove generic brackets if present (e.g., 'List[EmailRequest]' -> 'EmailRequest')
            if '[' in type_name:
                type_name = type_name.split('[')[1].split(']')[0]
                
            # Check if this is a basic type that doesn't need construction guidance
            basic_types = ['str', 'int', 'float', 'bool', 'list', 'dict', 'Any', 'Optional']
            if type_name in basic_types or type_name.startswith('typing.'):
                return ""
                
            # Look for object construction info in cached services
            if not cached_services:
                self.logger.warning(f"No cached services provided for {param_type}")
                return ""
                
            # Search through all services for data structure information
            for service_name, service_info in cached_services.items():
                capabilities = service_info.get("capabilities", {})
                data_structures = capabilities.get("data_structures", {})
                
                if type_name in data_structures:
                    struct_info = data_structures[type_name]
                    
                    # Build construction guidance
                    guidance = f"Parameter Type '{type_name}' Construction:\n"
                    
                    # Add field information
                    fields = struct_info.get("fields", {})
                    if fields:
                        guidance += f"  Required fields for {type_name}:\n"
                        for field_name, field_info in fields.items():
                            field_type = field_info.get("type", "Any")
                            required = field_info.get("required", False)
                            description = field_info.get("description", "")
                            req_indicator = "REQUIRED" if required else "OPTIONAL"
                            guidance += f"    - {field_name}: {field_type} ({req_indicator})"
                            if description:
                                guidance += f" - {description}"
                            guidance += "\n"
                    
                    # Add construction example if available
                    example = struct_info.get("construction_example", "")
                    if example:
                        guidance += f"  Construction example: {example}\n"
                        
                    self.logger.info(f"🔧 OBJECT CONSTRUCTION INFO FOUND for {type_name}")
                    return guidance
                    
            self.logger.debug(f"🔧 No object construction info found for {param_type}")
            return ""
            
        except Exception as e:
            self.logger.warning(f"Failed to get object construction info for {param_type}: {e}")
            return "" 