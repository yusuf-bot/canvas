#!/usr/bin/env python3
"""
MCP STDIO server that provides screenshot capture and analysis using Mistral Vision models.
"""

import asyncio
import base64
import json
import os
import sys
import tempfile
from io import BytesIO
from typing import Any, Dict, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    CallToolRequestParams,
)


from mistralai import Mistral
from PIL import Image
from dotenv import load_dotenv
load_dotenv()
# Create server instance
server = Server("mistral-vision-server")

# Initialize Mistral client
def get_mistral_client():
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise ValueError("MISTRAL_API_KEY environment variable is required")
    return Mistral(api_key=api_key)

def encode_image_to_base64(image_path: str) -> str:
    """Encode image to base64 string."""
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        raise Exception(f"Error encoding image: {e}")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
  
        Tool(
            name="analyze_existing_image",
            description="Analyze an existing image file using Mistral Vision",
            inputSchema={
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "Path to the image file to analyze"
                    },
                    "prompt": {
                        "type": "string",
                        "description": "What to analyze in the image"
                    },
                    "model": {
                        "type": "string",
                        "description": "Mistral vision model to use",
                        "enum": ["pixtral-12b-latest", "pixtral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
                        "default": "pixtral-12b-latest"
                    }
                },
                "required": ["image_path", "prompt"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any] | None) -> list[TextContent]:
    """Handle tool calls."""
    if arguments is None:
        arguments = {}
    
    try:
        client = get_mistral_client()
    except Exception as e:
        return [TextContent(type="text", text=f"Error initializing Mistral client: {e}")]
    
    
    
    if name == "analyze_existing_image":
        try:
            image_path = arguments.get("image_path")
            prompt = arguments.get("prompt", "What's in this image?")
            model = arguments.get("model", "pixtral-12b-latest")
            
            if not os.path.exists(image_path):
                return [TextContent(type="text", text=f"Image file not found: {image_path}")]
            
            # Encode image
            base64_image = encode_image_to_base64(image_path)
            
            # Analyze with Mistral
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": f"data:image/png;base64,{base64_image}"
                        }
                    ]
                }
            ]
            
            response = client.chat.complete(
                model=model,
                messages=messages
            )
            
            result = response.choices[0].message.content
            return [TextContent(type="text", text=result)]
            
        except Exception as e:
            return [TextContent(type="text", text=f"Error in image analysis: {e}")]
    
   
    
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    """Main entry point for the server."""
    # Check for required environment variabl
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())