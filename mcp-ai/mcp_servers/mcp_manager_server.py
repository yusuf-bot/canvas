#!/usr/bin/env python
"""
MCP Manager Server - Dynamic server installation and management
"""

import json
import sys
import asyncio
import os
from pathlib import Path
from typing import Any, List
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import mcp.types as types

# Add parent directory to path to import utils
sys.path.append(str(Path(__file__).parent.parent))
from utils.config_manager import ConfigManager

server = Server("mcp_manager")
config_manager = ConfigManager()

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available MCP management tools."""
    return [
        types.Tool(
            name="search_servers_by_capability",
            description="Find MCP servers that provide specific capabilities",
            inputSchema={
                "type": "object",
                "properties": {
                    "capability": {
                        "type": "string",
                        "description": "The capability you need (e.g., 'weather', 'database', 'github')"
                    }
                },
                "required": ["capability"]
            }
        ),
        types.Tool(
            name="get_server_info",
            description="Get detailed information about a specific server including installation requirements",
            inputSchema={
                "type": "object", 
                "properties": {
                    "server_name": {
                        "type": "string",
                        "description": "Name of the server to get info about"
                    }
                },
                "required": ["server_name"]
            }
        ),
        types.Tool(
            name="list_installed_servers",
            description="List all currently installed and configured servers",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="check_installation_requirements", 
            description="Check what's needed to install a specific server (API keys, dependencies, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_name": {
                        "type": "string",
                        "description": "Name of the server to check requirements for"
                    }
                },
                "required": ["server_name"]
            }
        ),
        types.Tool(
            name="prepare_installation_plan",
            description="Create an installation plan for one or more servers including all required steps",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of server names to install"
                    }
                },
                "required": ["server_names"]
            }
        ),
        types.Tool(
            name="install_server",
            description="Install and configure a server (use only after user approval)",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_name": {
                        "type": "string",
                        "description": "Name of the server to install"
                    },
                    "skip_install": {
                        "type": "boolean", 
                        "description": "Skip package installation if already installed",
                        "default": False
                    }
                },
                "required": ["server_name"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Handle tool calls for MCP management."""
    
    if name == "search_servers_by_capability":
        capability = arguments.get("capability", "")
        matching_servers = config_manager.find_servers_by_capability(capability)
        
        if not matching_servers:
            return [types.TextContent(
                type="text",
                text=f"No servers found for capability: {capability}"
            )]
        
        # Get detailed info for each server
        server_details = []
        for server_name in matching_servers:
            info = config_manager.get_server_info(server_name)
            if info:
                server_details.append({
                    "name": server_name,
                    "description": info.get("description", ""),
                    "capabilities": info.get("capabilities", []),
                    "requires_api_key": info.get("requires_api_key", False),
                    "installed": config_manager.is_server_installed(server_name)
                })
        
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "capability_searched": capability,
                "matching_servers": server_details
            }, indent=2)
        )]
    
    elif name == "get_server_info":
        server_name = arguments.get("server_name", "")
        info = config_manager.get_server_info(server_name)
        
        if not info:
            return [types.TextContent(
                type="text",
                text=f"Server '{server_name}' not found in registry"
            )]
        
        # Add installation status
        info["installed"] = config_manager.is_server_installed(server_name)
        
        return [types.TextContent(
            type="text",
            text=json.dumps(info, indent=2)
        )]
    
    elif name == "list_installed_servers":
        all_servers = config_manager.get_all_servers()
        
        server_list = []
        for name, config in all_servers.items():
            server_list.append({
                "name": name,
                "description": config.get("description", ""),
                "type": "default" if config.get("always_load") else "dynamic",
                "command": config.get("command"),
                "env_required": list(config.get("env", {}).keys())
            })
        
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "installed_servers": server_list,
                "total_count": len(server_list)
            }, indent=2)
        )]
    
    elif name == "check_installation_requirements":
        server_name = arguments.get("server_name", "")
        info = config_manager.get_server_info(server_name)
        
        if not info:
            return [types.TextContent(
                type="text",
                text=f"Server '{server_name}' not found in registry"
            )]
        
        # Check what's missing
        requirements = {
            "server_name": server_name,
            "package": info.get("package", ""),
            "install_commands": info.get("install_commands", []),
            "requires_api_key": info.get("requires_api_key", False),
            "env_vars_needed": info.get("env_vars", []),
            "api_key_info": info.get("api_key_info", ""),
            "missing_env_vars": [],
            "already_installed": config_manager.is_server_installed(server_name)
        }
        
        # Check which environment variables are missing
        for env_var in info.get("env_vars", []):
            if not os.getenv(env_var):
                requirements["missing_env_vars"].append(env_var)
        
        return [types.TextContent(
            type="text",
            text=json.dumps(requirements, indent=2)
        )]
    
    elif name == "prepare_installation_plan":
        server_names = arguments.get("server_names", [])
        
        plan = {
            "servers_to_install": [],
            "total_commands": [],
            "api_keys_needed": [],
            "env_vars_needed": [],
            "already_installed": []
        }
        
        for server_name in server_names:
            if config_manager.is_server_installed(server_name):
                plan["already_installed"].append(server_name)
                continue
                
            info = config_manager.get_server_info(server_name)
            if not info:
                continue
            
            server_plan = {
                "name": server_name,
                "package": info.get("package", ""),
                "install_commands": info.get("install_commands", []),
                "requires_api_key": info.get("requires_api_key", False),
                "env_vars": info.get("env_vars", []),
                "api_key_info": info.get("api_key_info", "")
            }
            
            plan["servers_to_install"].append(server_plan)
            plan["total_commands"].extend(info.get("install_commands", []))
            
            if info.get("requires_api_key"):
                plan["api_keys_needed"].extend([
                    {
                        "server": server_name,
                        "vars": info.get("env_vars", []),
                        "info": info.get("api_key_info", "")
                    }
                ])
            
            plan["env_vars_needed"].extend(info.get("env_vars", []))
        
        return [types.TextContent(
            type="text",
            text=json.dumps(plan, indent=2)
        )]
    
    elif name == "install_server":
        server_name = arguments.get("server_name", "")
        skip_install = arguments.get("skip_install", False)
        
        info = config_manager.get_server_info(server_name)
        if not info:
            return [types.TextContent(
                type="text",
                text=f"Error: Server '{server_name}' not found in registry"
            )]
        
        if config_manager.is_server_installed(server_name):
            return [types.TextContent(
                type="text",
                text=f"Server '{server_name}' is already installed"
            )]
        
        # Create server configuration for dynamic servers
        server_config = {
            "command": info.get("command"),
            "args": info.get("args", []),
            "env": info.get("env", {}),
            "description": info.get("description", ""),
            "always_load": False  # Dynamic servers are not always loaded
        }
        
        # Add to dynamic servers
        config_manager.add_dynamic_server(server_name, server_config)
        
        result = {
            "action": "install_completed",
            "server": server_name,
            "config_updated": True,
            "restart_required": True,
            "message": f"Server '{server_name}' has been configured and added to dynamic servers. A restart is required to load the new server."
        }
        
        if not skip_install and info.get("install_commands"):
            result["install_commands_needed"] = info.get("install_commands")
            result["message"] += f" Run these commands first: {'; '.join(info.get('install_commands'))}"
        
        return [types.TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]
    
    else:
        raise ValueError(f"Unknown tool: {name}")

async def main():
    """Main entry point for the MCP manager server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())