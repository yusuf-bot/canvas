#!/usr/bin/env python3
"""Configuration management for MCP servers"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List
from mcp import StdioServerParameters

class ConfigManager:
    def __init__(self, config_path: str = "mcp_config.json", registry_path: str = "server_registry.json"):
        self.config_path = Path(config_path)
        self.registry_path = Path(registry_path)
        self._config = None
        self._registry = None
    
    def load_config(self) -> Dict[str, Any]:
        """Load MCP configuration"""
        if self._config is None:
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    self._config = json.load(f)
            else:
                self._config = {"default_servers": {}, "dynamic_servers": {}, "installation_log": []}
        return self._config
    
    def load_registry(self) -> Dict[str, Any]:
        """Load server registry"""
        if self._registry is None:
            if self.registry_path.exists():
                with open(self.registry_path, 'r') as f:
                    self._registry = json.load(f)
            else:
                self._registry = {"servers": {}, "capability_mapping": {}}
        return self._registry
    
    def save_config(self):
        """Save configuration to file"""
        with open(self.config_path, 'w') as f:
            json.dump(self._config, f, indent=2)
    
    def get_all_servers(self) -> Dict[str, Dict[str, Any]]:
        """Get all servers (default + dynamic)"""
        config = self.load_config()
        all_servers = {}
        all_servers.update(config.get("default_servers", {}))
        all_servers.update(config.get("dynamic_servers", {}))
        return all_servers
    
    def add_dynamic_server(self, name: str, server_config: Dict[str, Any]):
        """Add a new dynamic server"""
        config = self.load_config()
        config["dynamic_servers"][name] = server_config
        
        # Log the installation
        config["installation_log"].append({
            "server": name,
            "action": "installed",
            "timestamp": str(Path().cwd()),
            "config": server_config
        })
        
        self._config = config
        self.save_config()
    
    def remove_dynamic_server(self, name: str):
        """Remove a dynamic server"""
        config = self.load_config()
        if name in config["dynamic_servers"]:
            del config["dynamic_servers"][name]
            
            # Log the removal
            config["installation_log"].append({
                "server": name,
                "action": "removed",
                "timestamp": str(Path().cwd())
            })
            
            self._config = config
            self.save_config()
            return True
        return False
    
    def create_server_params(self, server_config: Dict[str, Any]) -> StdioServerParameters:
        """Create StdioServerParameters from config"""
        # Resolve environment variables
        env = {}
        for key, value in server_config.get("env", {}).items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]  # Remove ${ and }
                env[key] = os.getenv(env_var)
            else:
                env[key] = value
        
        # Remove None values from env
        env = {k: v for k, v in env.items() if v is not None}
        
        return StdioServerParameters(
            command=server_config["command"],
            args=server_config["args"],
            env=env if env else None,
        )
    
    def find_servers_by_capability(self, capability: str) -> List[str]:
        """Find servers that provide a specific capability"""
        registry = self.load_registry()
        matching_servers = []
        
        # Check capability mapping
        capability_mapping = registry.get("capability_mapping", {})
        for cap, servers in capability_mapping.items():
            if capability.lower() in cap.lower():
                matching_servers.extend(servers)
        
        # Also check server capabilities directly
        for server_name, server_info in registry.get("servers", {}).items():
            server_capabilities = server_info.get("capabilities", [])
            if any(capability.lower() in cap.lower() for cap in server_capabilities):
                matching_servers.append(server_name)
        
        return list(set(matching_servers))  # Remove duplicates
    
    def get_server_info(self, server_name: str) -> Dict[str, Any]:
        """Get detailed information about a server from registry"""
        registry = self.load_registry()
        return registry.get("servers", {}).get(server_name, {})
    
    def is_server_installed(self, server_name: str) -> bool:
        """Check if a server is already installed/configured"""
        all_servers = self.get_all_servers()
        return server_name in all_servers