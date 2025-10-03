#!/usr/bin/env python
import asyncio
import os
import json
from typing import Optional
from pathlib import Path

from mistralai import Mistral
from mistralai.extra.run.context import RunContext
from mcp import StdioServerParameters
from mistralai.extra.mcp.stdio import MCPClientSTDIO
from mistralai.models import ToolFileChunk

class MistralChatClient:
    def __init__(self, api_key: str):
        self.client = Mistral(api_key=api_key)
        self.conversation_id: Optional[str] = None
        self.main_agent = None
        self.handoff_agent = None
        
    async def initialize_agents(self):
        """Initialize the main agent and handoff agent"""
        # Main agent with all connectors
        self.main_agent = self.client.beta.agents.create(
            model="mistral-medium-latest",
            name="Multi-Tool Assistant",
            description="Assistant with web search, code interpreter, image generation, and handoff capabilities",
            instructions="""You are a helpful assistant with access to multiple tools:
- Use web_search for current information and research
- Use code_interpreter for calculations, data analysis, and programming tasks
- Use image_generation for creating images
- You can handoff conversations to yourself for complex multi-step tasks or different perspectives
- Be concise and helpful in your responses""",
            tools=[
                {"type": "web_search"},
                {"type": "code_interpreter"},
                {"type": "image_generation"}
            ]
        )
        
        # Handoff agent (same capabilities but can be used for different context)
        self.handoff_agent = self.client.beta.agents.create(
            model="mistral-medium-latest",
            name="Handoff Assistant",
            description="Secondary assistant for handoff scenarios and complex task decomposition",
            instructions="""You are a secondary assistant that can be called upon for:
- Breaking down complex problems
- Providing different perspectives
- Handling specialized subtasks
- Continuing conversations with fresh context
Use the same tools as needed for your tasks.""",
            tools=[
                {"type": "web_search"},
                {"type": "code_interpreter"},
                {"type": "image_generation"}
            ]
        )
        
        # Set up handoffs between agents
        self.main_agent = self.client.beta.agents.update(
            agent_id=self.main_agent.id,
            handoffs=[self.handoff_agent.id]
        )
        
        self.handoff_agent = self.client.beta.agents.update(
            agent_id=self.handoff_agent.id,
            handoffs=[self.main_agent.id]
        )

    async def setup_mcp_context(self):
        """Set up MCP context with filesystem server"""
        # MCP server parameters for filesystem
        server_params = StdioServerParameters(
            command="node",
            args=["/mnt/bigvolume/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js", "/mnt/bigvolume/webapp/mcp-ai"],
            env={},
        )
        
        # Create run context
        run_ctx = RunContext(
            agent_id=self.main_agent.id,
            continue_on_fn_error=True,
        )
        
        # Create and register MCP client
        mcp_client = MCPClientSTDIO(stdio_params=server_params)
        await run_ctx.register_mcp_client(mcp_client=mcp_client)
        
        return run_ctx

    async def send_message(self, message: str, use_mcp: bool = False):
        """Send a message and get response"""
        try:
            if use_mcp:
                # Use MCP context for filesystem operations
                run_ctx = await self.setup_mcp_context()
                async with run_ctx:
                    if self.conversation_id:
                        # Continue existing conversation with MCP
                        events = await self.client.beta.conversations.run_stream_async(
                            run_ctx=run_ctx,
                            conversation_id=self.conversation_id,
                            inputs=message,
                        )
                        
                        async for event in events:
                            if hasattr(event, 'output_entries'):
                                self.conversation_id = event.conversation_id if hasattr(event, 'conversation_id') else self.conversation_id
                                return await self.process_response(event.output_entries)
                    else:
                        # Start new conversation with MCP
                        events = await self.client.beta.conversations.run_stream_async(
                            run_ctx=run_ctx,
                            inputs=message,
                        )
                        
                        async for event in events:
                            if hasattr(event, 'output_entries'):
                                self.conversation_id = event.conversation_id if hasattr(event, 'conversation_id') else None
                                return await self.process_response(event.output_entries)
            else:
                # Regular conversation without MCP
                if self.conversation_id:
                    response = self.client.beta.conversations.append(
                        conversation_id=self.conversation_id,
                        inputs=message
                    )
                else:
                    response = self.client.beta.conversations.start(
                        agent_id=self.main_agent.id,
                        inputs=message
                    )
                
                self.conversation_id = response.conversation_id
                return await self.process_response(response.outputs)
                
        except Exception as e:
            return f"Error: {str(e)}"

    async def process_response(self, outputs):
        """Process response outputs and handle file downloads"""
        response_text = ""
        files_downloaded = []
        
        for output in outputs:
            if hasattr(output, 'content'):
                if isinstance(output.content, list):
                    for chunk in output.content:
                        if hasattr(chunk, 'text'):
                            response_text += chunk.text
                        elif isinstance(chunk, ToolFileChunk):
                            # Download generated files
                            try:
                                file_bytes = self.client.files.download(file_id=chunk.file_id).read()
                                filename = f"{chunk.file_name}.{chunk.file_type}"
                                with open(filename, "wb") as file:
                                    file.write(file_bytes)
                                files_downloaded.append(filename)
                                response_text += f"\n[File saved: {filename}]"
                            except Exception as e:
                                response_text += f"\n[Error downloading file: {str(e)}]"
                elif isinstance(output.content, str):
                    response_text += output.content
        
        return response_text

    def reset_conversation(self):
        """Reset the current conversation"""
        self.conversation_id = None

async def main():
    # Get API key from environment
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        print("Error: MISTRAL_API_KEY environment variable not set")
        return

    # Initialize chat client
    chat_client = MistralChatClient(api_key)
    
    print("Initializing agents...")
    await chat_client.initialize_agents()
    print("Chat client ready. Type 'quit' to exit, 'reset' to start new conversation, '/mcp' prefix for filesystem operations")
    print()

    while True:
        try:
            user_input = input("You: ").strip()
            
            if user_input.lower() == 'quit':
                break
            elif user_input.lower() == 'reset':
                chat_client.reset_conversation()
                print("Conversation reset.")
                continue
            elif not user_input:
                continue
            
            # Check if user wants to use MCP filesystem
            use_mcp = user_input.startswith('/mcp ')
            if use_mcp:
                user_input = user_input[5:]  # Remove /mcp prefix
                
            print("Assistant: ", end="", flush=True)
            response = await chat_client.send_message(user_input, use_mcp=use_mcp)
            print(response)
            print()
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {str(e)}")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(main())