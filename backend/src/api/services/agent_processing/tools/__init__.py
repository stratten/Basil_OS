"""
Agent Tools Module

Central location for all agent tools, organized by their purpose:
- internal_basil_tools: Tools that work with Basil's internal data (activities, conversations, checkpoints, etc.)
- external_services: Tools that broker access to connected external services
- direct_application_interactions: Tools that interact with local applications, the OS, files, browser state, shell execution, and email clients

This organizational structure makes tool discovery straightforward and maintains clear boundaries
between internal Basil capabilities, connected external services, and local application automation.
"""

__all__ = ['internal_basil_tools']

