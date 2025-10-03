#!/usr/bin/env python
"""
Enhanced Terminal Server with batch command approval
"""

import json
import asyncio
import subprocess
import os
from typing import Any, List
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import mcp.types as types

server = Server("terminal")

# Store pending command batches
pending_batches = {}
batch_counter = 0

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available terminal tools."""
    return [
        types.Tool(
            name="execute_command",
            description="Execute a single terminal command (will require approval)",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command to execute"
                    },
                    "description": {
                        "type": "string", 
                        "description": "Human-readable description of what this command does"
                    },
                    "working_directory": {
                        "type": "string",
                        "description": "Working directory for the command (optional)",
                        "default": ""
                    }
                },
                "required": ["command"]
            }
        ),
        types.Tool(
            name="prepare_command_batch",
            description="Prepare a batch of commands for approval before execution",
            inputSchema={
                "type": "object",
                "properties": {
                    "commands": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string"},
                                "description": {"type": "string"},
                                "working_directory": {"type": "string", "default": ""}
                            },
                            "required": ["command", "description"]
                        },
                        "description": "List of commands with descriptions"
                    },
                    "batch_description": {
                        "type": "string",
                        "description": "Overall description of what this batch accomplishes"
                    }
                },
                "required": ["commands", "batch_description"]
            }
        ),
        types.Tool(
            name="execute_approved_batch",
            description="Execute a previously approved command batch",
            inputSchema={
                "type": "object",
                "properties": {
                    "batch_id": {
                        "type": "string",
                        "description": "ID of the approved batch to execute"
                    },
                    "approved_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of command indices that were approved (1-based)"
                    }
                },
                "required": ["batch_id", "approved_indices"]
            }
        ),
        types.Tool(
            name="get_current_directory",
            description="Get the current working directory",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Handle terminal tool calls."""
    global batch_counter
    
    if name == "execute_command":
        command = arguments.get("command", "")
        description = arguments.get("description", command)
        working_dir = arguments.get("working_directory", "")
        
        # This is a single command that needs approval
        approval_request = {
            "type": "command_approval_required",
            "commands": [
                {
                    "index": 1,
                    "command": command,
                    "description": description,
                    "working_directory": working_dir
                }
            ],
            "batch_description": f"Execute single command: {description}",
            "total_commands": 1
        }
        
        return [types.TextContent(
            type="text",
            text=json.dumps(approval_request, indent=2)
        )]
    
    elif name == "prepare_command_batch":
        commands = arguments.get("commands", [])
        batch_description = arguments.get("batch_description", "")
        
        batch_counter += 1
        batch_id = f"batch_{batch_counter}"
        
        # Store the batch for later execution
        pending_batches[batch_id] = {
            "commands": commands,
            "batch_description": batch_description,
            "created_at": "now"  # You might want to use actual timestamp
        }
        
        # Prepare approval request
        approval_request = {
            "type": "command_approval_required", 
            "batch_id": batch_id,
            "batch_description": batch_description,
            "commands": [
                {
                    "index": i + 1,
                    "command": cmd.get("command", ""),
                    "description": cmd.get("description", ""),
                    "working_directory": cmd.get("working_directory", "")
                }
                for i, cmd in enumerate(commands)
            ],
            "total_commands": len(commands),
            "instructions": "Review the commands above. Respond with the command numbers you approve (e.g., '1,3,5' or 'all' or 'none')"
        }
        
        return [types.TextContent(
            type="text",
            text=json.dumps(approval_request, indent=2)
        )]
    
    elif name == "execute_approved_batch":
        batch_id = arguments.get("batch_id", "")
        approved_indices = arguments.get("approved_indices", [])
        
        if batch_id not in pending_batches:
            return [types.TextContent(
                type="text", 
                text=f"Error: Batch {batch_id} not found or expired"
            )]
        
        batch = pending_batches[batch_id]
        commands = batch["commands"]
        
        results = []
        for i, index in enumerate(approved_indices):
            if index < 1 or index > len(commands):
                results.append({
                    "index": index,
                    "error": "Invalid command index"
                })
                continue
            
            cmd = commands[index - 1]  # Convert to 0-based
            command = cmd.get("command", "")
            working_dir = cmd.get("working_directory", "") or os.getcwd()
            description = cmd.get("description", "")
            
            try:
                # Execute the command
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=working_dir
                )
                
                stdout, stderr = await process.communicate()
                
                result = {
                    "index": index,
                    "command": command,
                    "description": description,
                    "working_directory": working_dir,
                    "return_code": process.returncode,
                    "stdout": stdout.decode('utf-8') if stdout else "",
                    "stderr": stderr.decode('utf-8') if stderr else "",
                    "success": process.returncode == 0
                }
                
                results.append(result)
                
            except Exception as e:
                results.append({
                    "index": index,
                    "command": command,
                    "error": str(e),
                    "success": False
                })
        
        # Clean up the batch
        del pending_batches[batch_id]
        
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "batch_id": batch_id,
                "batch_description": batch["batch_description"],
                "executed_commands": len(results),
                "results": results
            }, indent=2)
        )]
    
    elif name == "get_current_directory":
        try:
            cwd = os.getcwd()
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "current_directory": cwd,
                    "exists": os.path.exists(cwd),
                    "is_directory": os.path.isdir(cwd)
                })
            )]
        except Exception as e:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "error": str(e)
                })
            )]
    
    else:
        raise ValueError(f"Unknown tool: {name}")

async def main():
    """Main entry point for the terminal server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())