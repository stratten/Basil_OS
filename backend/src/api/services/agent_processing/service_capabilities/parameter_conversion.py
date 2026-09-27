"""Capability-aware parameter conversion helpers for service execution."""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def convert_dict_parameters_to_objects(
    parameters: Dict[str, Any],
    service_name: str,
    method_name: str,
    capability_cache: Any,
) -> Dict[str, Any]:
    """
    Generically convert dictionary parameters to object types based on service capabilities.
    Uses the method signature and data structures from capabilities to determine if
    conversion is needed and how to perform it.

    This is completely generic - no hardcoded service logic.
    """
    try:
        if not capability_cache or not capability_cache.services:
            return parameters

        # Get service capabilities
        service_info = capability_cache.services.get(service_name, {})
        capabilities = service_info.get("capabilities", {})
        methods = capabilities.get("methods", {})
        data_structures = capabilities.get("data_structures", {})

        # Get method signature
        method_info = methods.get(method_name, {})
        method_params = method_info.get("parameters", {})

        if not method_params or not data_structures:
            return parameters

        converted_params = {}

        for param_name, param_value in parameters.items():
            # Only process dictionary values that might need object conversion
            if isinstance(param_value, dict) and param_name in method_params:
                param_info = method_params[param_name]
                param_type = param_info.get("type", "")

                # Extract the object type name from the parameter type
                object_type_name = extract_object_type_name(param_type)

                # Check if this type has a data structure definition
                if object_type_name in data_structures:
                    struct_info = data_structures[object_type_name]

                    # Use dynamic object construction
                    constructed_obj = construct_object_from_dict(
                        param_value, object_type_name, struct_info
                    )

                    if constructed_obj is not None:
                        logger.info(f"🔧 CONVERTED {param_name}: dict → {object_type_name}")
                        converted_params[param_name] = constructed_obj
                    else:
                        logger.warning(f"⚠️ CONVERSION FAILED for {param_name}: {object_type_name}")
                        converted_params[param_name] = param_value
                else:
                    # No object type found, keep as dict
                    converted_params[param_name] = param_value
            else:
                # Not a dict or not in method params, keep as-is
                converted_params[param_name] = param_value

        return converted_params

    except Exception as e:
        logger.warning(f"⚠️ Object conversion failed: {e}")
        return parameters


def extract_object_type_name(param_type: str) -> str:
    """Extract the object type name from a parameter type string."""
    try:
        # Handle complex types like "api.services...EmailRequest" → "EmailRequest"
        if "." in param_type:
            type_name = param_type.split(".")[-1]
        else:
            type_name = param_type

        # Remove Optional brackets if present: "Optional[EmailRequest]" → "EmailRequest"
        if "[" in type_name and "]" in type_name:
            type_name = type_name.split("[")[1].split("]")[0]

        return type_name.strip()

    except Exception:
        return param_type


def construct_object_from_dict(
    dict_value: Dict[str, Any],
    object_type_name: str,
    struct_info: Dict[str, Any],
) -> Any:
    """
    Construct an object from a dictionary using the data structure info.
    Uses dynamic import based on module_path in struct_info.
    """
    try:
        # Get module path from struct_info
        module_path = struct_info.get("module_path")
        if not module_path:
            logger.warning(f"⚠️ No module_path for {object_type_name}")
            return None

        # Split module path to get module and class name
        module_parts = module_path.split(".")
        module_name = ".".join(module_parts[:-1])
        class_name = module_parts[-1]

        # Dynamically import the module and get the class
        module = __import__(module_name, fromlist=[class_name])
        data_class = getattr(module, class_name)

        # Construct the object with the dictionary values
        constructed_obj = data_class(**dict_value)

        logger.info(f"✅ CONSTRUCTED {object_type_name} from {dict_value}")
        return constructed_obj

    except Exception as e:
        logger.warning(f"⚠️ Failed to construct {object_type_name}: {e}")
        return None
