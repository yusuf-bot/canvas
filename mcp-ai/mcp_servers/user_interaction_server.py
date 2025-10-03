#!/usr/bin/env python
"""
User Interaction MCP Server
Allows the agent to pause execution and ask the user questions
"""

import json
import sys
import asyncio
from typing import Any, Sequence
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel,
)
import mcp.types as types

# Global state for user interaction
pending_questions = []
user_responses = {}

server = Server("user_interaction")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available user interaction tools."""
    return [
        types.Tool(
            name="ask_user",
            description="Ask the user a question and wait for their response. Use this when you need clarification or user input during task execution.",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user"
                    },
                    "context": {
                        "type": "object",
                        "description": "Any context information that should be preserved for resuming the task",
                        "additionalProperties": True
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of suggested responses/options for the user"
                    }
                },
                "required": ["question"]
            }
        ),
        types.Tool(
            name="confirm_action",
            description="Ask the user to confirm an action before proceeding",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "The action you want to confirm"
                    },
                    "details": {
                        "type": "string",
                        "description": "Additional details about the action"
                    },
                    "context": {
                        "type": "object",
                        "description": "Context to preserve",
                        "additionalProperties": True
                    }
                },
                "required": ["action"]
            }
        ),
        types.Tool(
            name="request_choice",
            description="Present the user with multiple choices and get their selection",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question asking for a choice"
                    },
                    "choices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of choices to present to the user"
                    },
                    "context": {
                        "type": "object",
                        "description": "Context to preserve",
                        "additionalProperties": True
                    }
                },
                "required": ["question", "choices"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Handle tool calls for user interaction."""
    
    if name == "ask_user":
        question = arguments.get("question", "")
        context = arguments.get("context", {})
        options = arguments.get("options", [])
        
        # Format the question
        formatted_question = question
        if options:
            formatted_question += f"\nOptions: {', '.join(options)}"
        
        # This is a special response that signals the main loop to pause and ask the user
        response = {
            "type": "user_input_required",
            "question": formatted_question,
            "context": context,
            "original_question": question,
            "options": options
        }
        
        return [types.TextContent(
            type="text", 
            text=json.dumps(response)
        )]
    
    elif name == "confirm_action":
        action = arguments.get("action", "")
        details = arguments.get("details", "")
        context = arguments.get("context", {})
        
        question = f"Do you want me to {action}?"
        if details:
            question += f" ({details})"
        question += " (yes/no)"
        
        response = {
            "type": "user_input_required",
            "question": question,
            "context": context,
            "action": action,
            "details": details,
            "options": ["yes", "no"]
        }
        
        return [types.TextContent(
            type="text", 
            text=json.dumps(response)
        )]
    
    elif name == "request_choice":
        question = arguments.get("question", "")
        choices = arguments.get("choices", [])
        context = arguments.get("context", {})
        
        formatted_question = question
        if choices:
            formatted_choices = "\n".join([f"{i+1}. {choice}" for i, choice in enumerate(choices)])
            formatted_question += f"\n{formatted_choices}\nEnter your choice (1-{len(choices)}) or the text:"
        
        response = {
            "type": "user_input_required",
            "question": formatted_question,
            "context": context,
            "choices": choices,
            "original_question": question
        }
        
        return [types.TextContent(
            type="text", 
            text=json.dumps(response)
        )]
    
    else:
        raise ValueError(f"Unknown tool: {name}")

async def main():
    # Run the server using stdin/stdout streams
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="user_interaction",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())