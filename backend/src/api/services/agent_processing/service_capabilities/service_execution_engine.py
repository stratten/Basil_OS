"""
Service Execution Engine for Enhanced Agent Processing

This module handles service method execution with clean error handling and parameter
validation for the enhanced agent processing system. Replaces the deprecated version
in @/agent folder with a more elegant and focused implementation.

Key responsibilities:
1. Service registration and management
2. Service method execution with proper parameter handling  
3. Parameter validation and method signature compliance
4. Clean error handling and logging
5. Integration with ServiceCapabilityAnalyzer for validation
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from .service_capability_analyzer import ServiceCapabilityAnalyzer
from .service_execution_ledger_capture import capture_normalized_service_result
from api.services.agent_processing.tools.direct_application_interactions.file_system.text_file_write import (
    select_direct_text_write_artifact,
)

logger = logging.getLogger(__name__)


def redact_text_parameters_for_log(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Remove direct text bodies from execution-engine log contexts."""
    return {
        key: (
            f"<redacted text:{len(value.encode('utf-8'))} bytes>"
            if key == "content" and isinstance(value, str)
            else value
        )
        for key, value in parameters.items()
    }


@dataclass
class ExecutionResult:
    """Structured result from service method execution with normalized data field."""
    success: bool
    result: Any = None
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    service: Optional[str] = None
    method: Optional[str] = None
    parameters_used: Optional[Dict[str, Any]] = None
    execution_time: Optional[float] = None
    agent_task_artifact: Optional[Dict[str, Any]] = None


class ServiceExecutionEngine:
    """
    Elegant service execution engine for the enhanced agent processing system.
    
    Focuses on clean service method execution with proper validation and error handling.
    Works with any service that can be registered and provides a clean execution interface.
    """
    
    def __init__(self, service_capability_analyzer: Optional[ServiceCapabilityAnalyzer] = None, 
                 cached_capabilities: Optional[Dict[str, Any]] = None):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.service_capability_analyzer = service_capability_analyzer
        self.cached_capabilities = cached_capabilities  # Store cached capabilities to avoid redundant discovery
        
        # Clean service registry
        self.services: Dict[str, Any] = {}

    def set_cached_capabilities(self, cached_capabilities: Dict[str, Any]) -> None:
        """
        Set cached service capabilities to avoid redundant discovery during execution.
        
        Args:
            cached_capabilities: Pre-cached service capabilities from planning phase
        """
        self.cached_capabilities = cached_capabilities
        self.logger.debug(f"🔧 Injected cached capabilities for {len(cached_capabilities)} services")
        
    def register_service(self, service_name: str, service_instance: Any) -> None:
        """
        Register a service instance for execution.
        
        Args:
            service_name: Unique name for the service
            service_instance: The service instance to register
        """
        self.services[service_name] = service_instance
        self.logger.info(f"🔧 REGISTERED SERVICE: {service_name}")
        
    def get_service(self, service_name: str) -> Optional[Any]:
        """Get a registered service instance."""
        return self.services.get(service_name)
    
    def get_registered_services(self) -> List[str]:
        """Get list of all registered service names."""
        return list(self.services.keys())
    
    async def _execute_service_method(self, service: str, method: str, parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a service method - compatible with upfront data retriever."""
        try:
            self.logger.info(f"🔧 EXECUTING: {service}.{method}")
            self.logger.info(
                "🔧 PARAMETERS: %s",
                redact_text_parameters_for_log(parameters),
            )
            
            # Use the clean execution method
            result = await self.execute_service_method(service, method, parameters)
            
            if result.success:
                return {
                    "success": True,
                    "result": result.result,
                    "service": service,
                    "method": method
                }
            else:
                return {
                    "success": False,
                    "error": result.error,
                    "service": service,
                    "method": method
                }
                
        except Exception as e:
            self.logger.error(f"❌ SERVICE METHOD EXECUTION FAILED: {e}")
            return {
                "success": False,
                "error": str(e),
                "service": service,
                "method": method
            }
    
    async def execute_service_method(self, service_name: str, method_name: str, 
                                   parameters: Dict[str, Any]) -> ExecutionResult:
        """
        Execute a service method with validation and clean error handling.
        
        Args:
            service_name: Name of the registered service
            method_name: Method to call on the service
            parameters: Parameters to pass to the method
            
        Returns:
            ExecutionResult with success status and result/error information
        """
        import time
        start_time = time.time()
        
        try:
            self.logger.info(f"🎯 EXECUTING: {service_name}.{method_name}")
            self.logger.info(f"📋 PARAMETERS: {list(parameters.keys())}")
            
            # Get service instance
            service_instance = self.get_service(service_name)
            if not service_instance:
                return ExecutionResult(
                    success=False,
                    error=f"Service '{service_name}' not registered. Available: {self.get_registered_services()}",
                    service=service_name,
                    method=method_name
                )
            
            # Validate method exists and parameters if capability analyzer available
            validated_method, validated_params = await self._validate_execution(
                service_name, method_name, parameters, service_instance
            )
            
            # Execute the method
            result = await self._call_service_method(
                service_instance, validated_method, validated_params
            )
            agent_task_artifact = (
                select_direct_text_write_artifact(
                    result.result if isinstance(result, ExecutionResult) else result
                )
                if service_name == "file_service" and validated_method == "write_text_file"
                else None
            )

            execution_time = time.time() - start_time

            if isinstance(result, ExecutionResult):
                result.service = service_name
                result.method = validated_method
                if result.agent_task_artifact is None:
                    result.agent_task_artifact = agent_task_artifact
                if result.parameters_used is None:
                    result.parameters_used = validated_params
                if result.execution_time is None:
                    result.execution_time = execution_time

                if result.success:
                    self.logger.info(f"✅ EXECUTION SUCCESS: {service_name}.{validated_method} ({execution_time:.3f}s)")
                else:
                    self.logger.warning(
                        f"⚠️ EXECUTION FAILED: {service_name}.{validated_method} - {result.error} "
                        f"({execution_time:.3f}s)"
                    )
                await self._capture_normalized_result(result, validated_params)
                return result
            
            # Determine success based on method result
            # For boolean return values, False indicates failure
            method_success = True  # Default to success for non-boolean returns
            if isinstance(result, bool):
                method_success = result
                self.logger.info(f"🔍 Boolean result detected: {result} -> Success: {method_success}")
            
            if method_success:
                self.logger.info(f"✅ EXECUTION SUCCESS: {service_name}.{validated_method} ({execution_time:.3f}s)")
            else:
                self.logger.warning(f"⚠️ EXECUTION FAILED: {service_name}.{validated_method} returned {result} ({execution_time:.3f}s)")
            
            # Normalize dict results into data for consistent downstream access
            normalized_data = result if isinstance(result, dict) else None
            normalized_result = ExecutionResult(
                success=method_success,
                result=result,
                data=normalized_data,
                service=service_name,
                method=validated_method,
                parameters_used=validated_params,
                execution_time=execution_time,
                agent_task_artifact=agent_task_artifact,
            )
            await self._capture_normalized_result(normalized_result, validated_params)
            return normalized_result
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)
            
            self.logger.error(f"❌ EXECUTION FAILED: {service_name}.{method_name} - {error_msg}")
            
            normalized_result = ExecutionResult(
                success=False,
                error=error_msg,
                service=service_name,
                method=method_name,
                parameters_used=parameters,
                execution_time=execution_time
            )
            await self._capture_normalized_result(normalized_result, parameters)
            return normalized_result

    async def _capture_normalized_result(
        self,
        result: ExecutionResult,
        parameters: Optional[Dict[str, Any]],
    ) -> None:
        """Capture a completed real invocation without changing its result."""
        await capture_normalized_service_result(result, parameters, self.logger)
    
    async def _validate_execution(self, service_name: str, method_name: str, 
                                parameters: Dict[str, Any], service_instance: Any) -> Tuple[str, Dict[str, Any]]:
        """
        Validate method exists and parameters are correct.
        
        Returns:
            Tuple of (validated_method_name, validated_parameters)
        """
        try:
            # If we have a capability analyzer, use it for validation with cached capabilities
            if self.service_capability_analyzer:
                validated_method, validated_params = self.service_capability_analyzer.validate_service_method(
                    service_name, method_name, parameters, self.cached_capabilities
                )
                return validated_method, validated_params
            
            # Fallback: basic method existence check
            if not hasattr(service_instance, method_name):
                available_methods = [
                    m for m in dir(service_instance) 
                    if not m.startswith('_') and callable(getattr(service_instance, m))
                ]
                raise Exception(f"Method '{method_name}' not found. Available: {available_methods}")
            
            return method_name, parameters
            
        except Exception as e:
            self.logger.warning(f"Validation failed: {e}")
            # Return original values if validation fails
            return method_name, parameters
    
    async def _call_service_method(self, service_instance: Any, method_name: str, 
                                 parameters: Dict[str, Any]) -> Any:
        """
        Call the service method with proper async/sync handling.
        
        Args:
            service_instance: The service instance
            method_name: Method to call
            parameters: Parameters to pass
            
        Returns:
            The result from the service method
        """
        import time
        
        try:
            # Get the method
            method = getattr(service_instance, method_name)
            
            # Clean parameters - remove any internal processing parameters
            clean_params = self._clean_parameters(parameters)
            
            self.logger.info(f"🔧 CALLING: {method_name} with {len(clean_params)} parameters")
            self.logger.info(f"🔧 SERVICE TYPE: {type(service_instance).__name__}")
            self.logger.info(f"🔧 METHOD TYPE: {'async' if asyncio.iscoroutinefunction(method) else 'sync'}")
            self.logger.info(
                "🔧 PARAMETERS: %s",
                redact_text_parameters_for_log(clean_params),
            )
            
            start_time = time.time()
            
            # Handle async/sync methods appropriately
            if asyncio.iscoroutinefunction(method):
                self.logger.info(f"🔧 Calling async method {method_name}...")
                result = await method(**clean_params)
            else:
                self.logger.info(f"🔧 Calling sync method {method_name}...")
                result = method(**clean_params)
            
            execution_time = time.time() - start_time
            self.logger.info(f"🔧 METHOD COMPLETED: {method_name} in {execution_time:.3f}s")
            
            # Log result summary
            if result is not None:
                if isinstance(result, list):
                    self.logger.info(f"🔧 RESULT: List with {len(result)} items")
                elif isinstance(result, dict):
                    self.logger.info(f"🔧 RESULT: Dict with keys: {list(result.keys())}")
                else:
                    self.logger.info(f"🔧 RESULT: {type(result).__name__}")
            else:
                self.logger.info("🔧 RESULT: None")
            
            # Wrap result with execution context for agent visibility
            return self._wrap_execution_result(
                service_name=type(service_instance).__name__,
                method_name=method_name,
                result=result,
                parameters=clean_params,
                execution_time=execution_time
            )
            
        except Exception as e:
            execution_time = time.time() - start_time if 'start_time' in locals() else 0
            self.logger.error(f"❌ METHOD CALL FAILED: {method_name} after {execution_time:.3f}s - {e}")
            self.logger.error(f"❌ Exception type: {type(e).__name__}")
            import traceback
            self.logger.error(f"❌ Traceback: {traceback.format_exc()}")
            
            # Enhance error message with execution context for the agent
            error_msg = str(e)
            error_type = type(e).__name__
            
            # Build context summary (limit parameter values for readability)
            context_summary = {
                "service": type(service_instance).__name__,
                "method": method_name,
                "execution_time": f"{execution_time:.2f}s"
            }
            
            # Add key parameters (limit to avoid huge messages)
            clean_params = clean_params if 'clean_params' in locals() else parameters
            for key, value in redact_text_parameters_for_log(clean_params).items():
                if isinstance(value, (str, int, float, bool, type(None))):
                    context_summary[key] = value
                elif isinstance(value, dict):
                    context_summary[key] = f"<dict with {len(value)} keys>"
                elif isinstance(value, list):
                    context_summary[key] = f"<list with {len(value)} items>"
                else:
                    context_summary[key] = f"<{type(value).__name__}>"
            
            # Provide actionable suggestions based on error patterns
            suggestion = None
            if "timeout" in error_msg.lower():
                suggestion = "Operation timed out. Try: 1) Reduce data size/scope, 2) Check if target application is responding, 3) Increase timeout if appropriate"
            elif "permission" in error_msg.lower() or "access" in error_msg.lower() or "denied" in error_msg.lower():
                suggestion = "Permission denied. Check: 1) System Preferences → Security & Privacy → Automation, 2) Grant required permissions to the application"
            elif "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                suggestion = "Resource not found. Verify: 1) Path/identifier is correct, 2) Resource exists and is accessible"
            elif "attribute" in error_msg.lower() and "has no" in error_msg.lower():
                suggestion = "Invalid parameter structure. Check: 1) Parameter format matches expected type, 2) All required fields are present"
            
            # Construct enhanced error message
            enhanced_error = f"{error_type}: {error_msg}"
            if context_summary:
                enhanced_error += f"\n\nExecution Context: {context_summary}"
            if suggestion:
                enhanced_error += f"\n\nSuggestion: {suggestion}"
            
            # Raise enhanced exception
            raise Exception(enhanced_error) from e
    
    def _wrap_execution_result(
        self, 
        service_name: str, 
        method_name: str, 
        result: Any, 
        parameters: Dict[str, Any], 
        execution_time: float
    ) -> ExecutionResult:
        """
        Wrap raw service result with execution context for agent visibility.
        
        Provides structured metadata about what was executed and what was returned,
        enabling the agent to make better decisions about next steps.
        
        CRITICAL: Preserves success/failure status from result objects like AppleScriptResult
        so the agent can see failures and recalibrate.
        """
        # Check if result has its own success indicator (e.g., AppleScriptResult)
        actual_success = True
        error_message = None
        
        if hasattr(result, 'success'):
            actual_success = getattr(result, 'success')
            if not actual_success and hasattr(result, 'error'):
                error_message = getattr(result, 'error')
        elif isinstance(result, dict) and isinstance(result.get("success"), bool):
            actual_success = result["success"]
            if not actual_success:
                error_message = (
                    result.get("error")
                    or result.get("stderr")
                    or result.get("message")
                    or f"{method_name} returned success=false"
                )
        
        # Generate result summary
        result_count = None
        result_type = None
        
        if result is None:
            result_type = "None"
            summary = f"Completed {method_name}"
        elif isinstance(result, bool):
            result_type = "bool"
            summary = f"{'Success' if result else 'Failed'}: {method_name}"
        elif isinstance(result, list):
            result_count = len(result)
            result_type = f"list[{result_count}]"
            summary = f"Retrieved {result_count} item{'s' if result_count != 1 else ''} from {method_name}"
        elif isinstance(result, dict):
            result_count = len(result)
            result_type = f"dict[{result_count} keys]"
            if actual_success:
                summary = f"Retrieved data from {method_name} with {result_count} field{'s' if result_count != 1 else ''}"
            else:
                summary = f"Failed: {method_name}"
                if error_message:
                    summary += f" - {error_message}"
        elif isinstance(result, str):
            result_type = "str"
            summary = f"Completed {method_name} (returned text)"
        elif isinstance(result, (int, float)):
            result_type = type(result).__name__
            summary = f"Completed {method_name} -> {result}"
        else:
            result_type = type(result).__name__
            # Check for AppleScriptResult or similar objects
            if hasattr(result, 'success'):
                summary = f"{'Success' if actual_success else 'Failed'}: {method_name}"
                if not actual_success and error_message:
                    summary += f" - {error_message}"
            else:
                summary = f"Completed {method_name}"
        
        # Build parameter summary (truncate for readability)
        param_summary = {}
        for key, value in parameters.items():
            if key == "content" and isinstance(value, str):
                param_summary[key] = f"<redacted text:{len(value.encode('utf-8'))} bytes>"
            elif isinstance(value, (str, int, float, bool, type(None))):
                param_summary[key] = value
            elif isinstance(value, dict):
                param_summary[key] = f"<dict:{len(value)}>"
            elif isinstance(value, list):
                param_summary[key] = f"<list:{len(value)}>"
            else:
                param_summary[key] = f"<{type(value).__name__}>"
        
        return ExecutionResult(
            success=actual_success,  # Preserve actual success/failure status
            result=result,
            data={
                "summary": summary,
                "result_type": result_type,
                "result_count": result_count,
                "execution_time_ms": int(execution_time * 1000)
            },
            error=error_message,  # Include error message if operation failed
            service=service_name,
            method=method_name,
            parameters_used=param_summary,
            execution_time=execution_time
        )
    
    def _clean_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Remove common internal processing parameters that shouldn't be passed to service methods."""
        # Remove common internal processing parameters
        internal_keys = {
            'working_memory', 'step_id', 'todo_context', 
            'previous_results', '_retry_reasoning', '_alternative_method'
        }
        
        return {k: v for k, v in parameters.items() if k not in internal_keys}
    
    def _format_service_summary(self) -> str:
        """Format a summary of registered services for logging."""
        if not self.services:
            return "No services registered"
        
        summary_lines = [f"📋 REGISTERED SERVICES ({len(self.services)}):"]
        for service_name, service_instance in self.services.items():
            service_type = type(service_instance).__name__
            summary_lines.append(f"   🔧 {service_name}: {service_type}")
        
        return "\n".join(summary_lines)
    
    async def execute_batch_operations(self, operations: List[Dict[str, Any]]) -> List[ExecutionResult]:
        """
        Execute multiple service operations in sequence.
        
        Args:
            operations: List of operation dictionaries with 'service', 'method', 'parameters'
            
        Returns:
            List of ExecutionResult objects
        """
        self.logger.info(f"🔄 EXECUTING BATCH: {len(operations)} operations")
        
        results = []
        for i, operation in enumerate(operations, 1):
            self.logger.info(f"🎯 BATCH OPERATION {i}/{len(operations)}")
            
            service_name = operation.get('service')
            method_name = operation.get('method')
            parameters = operation.get('parameters', {})
            
            if not service_name or not method_name:
                results.append(ExecutionResult(
                    success=False,
                    error="Missing service or method in operation",
                    service=service_name,
                    method=method_name
                ))
                continue
            
            result = await self.execute_service_method(service_name, method_name, parameters)
            results.append(result)
            
            # Stop on first failure if configured to do so
            if not result.success:
                self.logger.warning(f"⚠️ BATCH OPERATION {i} FAILED, continuing...")
        
        successful = sum(1 for r in results if r.success)
        self.logger.info(f"✅ BATCH COMPLETE: {successful}/{len(results)} successful")
        
        return results
    
    async def test_service_connectivity(self) -> Dict[str, bool]:
        """
        Test connectivity to all registered services.
        
        Returns:
            Dictionary mapping service names to connectivity status
        """
        self.logger.info("🔍 TESTING SERVICE CONNECTIVITY")
        
        connectivity = {}
        
        for service_name, service_instance in self.services.items():
            try:
                # Try to call a basic method or check if service is available
                if hasattr(service_instance, 'health_check'):
                    # Service provides health check
                    if asyncio.iscoroutinefunction(service_instance.health_check):
                        await service_instance.health_check()
                    else:
                        service_instance.health_check()
                elif hasattr(service_instance, 'get_service_capabilities'):
                    # Try getting capabilities
                    service_instance.get_service_capabilities()
                else:
                    # Basic existence check
                    str(service_instance)
                
                connectivity[service_name] = True
                self.logger.info(f"✅ {service_name}: Connected")
                
            except Exception as e:
                connectivity[service_name] = False
                self.logger.warning(f"❌ {service_name}: Failed - {e}")
        
        return connectivity
    
    def get_execution_stats(self) -> Dict[str, Any]:
        """Get basic execution statistics."""
        return {
            "registered_services": len(self.services),
            "service_names": list(self.services.keys()),
            "capabilities_analyzer_available": self.service_capability_analyzer is not None
        } 