#!/usr/bin/env python
import asyncio
import os
import json
import threading
import queue
from datetime import datetime
from mistralai import Mistral
from mistralai.extra.run.context import RunContext
from mistralai.extra.mcp.stdio import MCPClientSTDIO
from pathlib import Path
from mistralai.types import BaseModel
from dotenv import load_dotenv

# Import our config manager
from utils.config_manager import ConfigManager

load_dotenv()

# Set the current working directory and model to use
cwd = Path(__file__).parent
MODEL = "mistral-medium-latest"
LOG_FILE = "chat_log.log"

class TaskResult(BaseModel):
    task: str
    result: str
    success: bool
    needs_user_input: bool = False
    question_for_user: str = ""
    context: dict = {}

class UserInteraction:
    def __init__(self):
        self.input_queue = queue.Queue()
        self.response_queue = queue.Queue()
        self.waiting_for_input = False
        self.lock = threading.Lock()
    
    def request_user_input(self, question: str) -> str:
        """Request input from user and wait for response"""
        with self.lock:
            self.waiting_for_input = True
            self.input_queue.put(question)
            
        # Wait for user response
        response = self.response_queue.get()
        
        with self.lock:
            self.waiting_for_input = False
            
        return response
    
    def provide_user_response(self, response: str):
        """Provide user response"""
        self.response_queue.put(response)
    
    def has_pending_question(self) -> tuple[bool, str]:
        """Check if there's a pending question"""
        with self.lock:
            if self.waiting_for_input and not self.input_queue.empty():
                try:
                    question = self.input_queue.get_nowait()
                    return True, question
                except queue.Empty:
                    pass
        return False, ""

# Global instances
user_interaction = UserInteraction()
config_manager = ConfigManager()

def log_interaction(user_prompt, tools_used, response_data):
    """Log the interaction to a file."""
    timestamp = datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "user_prompt": user_prompt,
        "tools_used": tools_used,
        "response": response_data
    }
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

def extract_tools_used(run_result):
    """Extract list of tools used from run result."""
    tools = []
    for entry in run_result.output_entries:
        if hasattr(entry, 'type') and entry.type == 'function.call' and hasattr(entry, 'name'):
            tools.append(entry.name)
    return list(set(tools))

def extract_response_content(run_result):
    """Extract the actual response content from run result."""
    response_content = []
    for entry in run_result.output_entries:
        if hasattr(entry, 'type') and entry.type == 'message.output':
            if hasattr(entry, 'content'):
                try:
                    json_data = json.loads(entry.content)
                    # Special handling for reasoning responses
                    if json_data.get('type') in ['reasoning_initiated', 'reasoning_continued', 'reasoning_completed']:
                        return f"🧠 Self-Reasoning: {json_data.get('message', json_data.get('status', 'Processing...'))}"
                    if 'result' in json_data:
                        return json_data['result']
                except:
                    pass
                response_content.append(entry.content)
    
    return '\n'.join(response_content) if response_content else "No response found"

async def setup_mcp_clients(run_ctx):
    """Setup all MCP clients from configuration."""
    print("Loading MCP servers from configuration...")
    
    all_servers = config_manager.get_all_servers()
    clients = []
    failed_servers = []
    
    for server_name, server_config in all_servers.items():
        try:
            # Create server parameters from config
            server_params = config_manager.create_server_params(server_config)
            
            # Create and register client
            client = MCPClientSTDIO(stdio_params=server_params)
            await run_ctx.register_mcp_client(mcp_client=client)
            clients.append(server_name)
            
        except Exception as e:
            print(f"Warning: Failed to load server '{server_name}': {e}")
            failed_servers.append(f"{server_name} ({str(e)})")
            continue
    
    print(f"MCP Clients loaded: {', '.join(clients)}")
    if failed_servers:
        print(f"Failed to load: {', '.join(failed_servers)}")
    
    return len(clients), len(failed_servers)

def check_for_user_interaction_request(run_result):
    """Check if the run result contains a user interaction request"""
    try:
        # Check output entries for user interaction requests
        for entry in run_result.output_entries:
            if hasattr(entry, 'content') and entry.content:
                try:
                    content = json.loads(entry.content)
                    if content.get("type") in ["user_input_required", "command_approval_required"]:
                        return True, content
                except json.JSONDecodeError:
                    # Check if it's a text response that indicates need for user input
                    if any(marker in entry.content.lower() for marker in [
                        "user_input_required", "ask_user", "confirm_action", "request_choice", 
                        "command_approval_required"
                    ]):
                        return True, {"question": entry.content, "type": "user_input_required"}
        
        # Check the main response
        response_text = extract_response_content(run_result)
        if response_text:
            try:
                response_json = json.loads(response_text)
                if response_json.get("type") in ["user_input_required", "command_approval_required"]:
                    return True, response_json
            except json.JSONDecodeError:
                pass
        
        return False, {}
    except Exception as e:
        print(f"Error checking for user interaction: {e}")
        return False, {}

def handle_command_approval(interaction_data):
    """Handle command approval requests"""
    print(f"\n{interaction_data.get('batch_description', 'Command Execution Request')}")
    print("=" * 60)
    
    commands = interaction_data.get("commands", [])
    for cmd in commands:
        index = cmd.get("index", 0)
        command = cmd.get("command", "")
        description = cmd.get("description", "")
        working_dir = cmd.get("working_directory", "")
        
        print(f"{index}. {description}")
        print(f"   Command: {command}")
        if working_dir:
            print(f"   Directory: {working_dir}")
        print()
    
    print("Which commands do you approve?")
    print("Enter: 'all', 'none', or comma-separated numbers (e.g., '1,3,5')")
    
    while True:
        user_input = input("Your choice: ").strip().lower()
        
        if user_input == "all":
            approved = list(range(1, len(commands) + 1))
            break
        elif user_input == "none":
            approved = []
            break
        else:
            try:
                approved = [int(x.strip()) for x in user_input.split(",") if x.strip().isdigit()]
                # Validate indices
                valid_indices = [i for i in approved if 1 <= i <= len(commands)]
                if len(valid_indices) != len(approved):
                    print("Some invalid indices found. Please try again.")
                    continue
                approved = valid_indices
                break
            except ValueError:
                print("Invalid input. Please try again.")
                continue
    
    if approved:
        print(f"Approved commands: {approved}")
        # Return the execution command
        batch_id = interaction_data.get("batch_id", "single_command")
        return f"Execute the approved commands from batch {batch_id}: {approved}"
    else:
        print("No commands approved.")
        return "User declined to execute any commands."

async def handle_task_with_interruption(client, run_ctx, user_input):
    """Handle a task that might need user interruption"""
    current_context = {}
    conversation_history = []
    
    while True:
        try:
            # Run the task
            run_result = await client.beta.conversations.run_async(
                run_ctx=run_ctx,
                inputs=user_input,
            )
            
            # Check if the agent is requesting user input
            needs_input, interaction_data = check_for_user_interaction_request(run_result)
            
            if needs_input:
                interaction_type = interaction_data.get("type", "user_input_required")
                
                if interaction_type == "command_approval_required":
                    # Handle command approval
                    user_response = handle_command_approval(interaction_data)
                else:
                    # Handle general user input
                    question = interaction_data.get("question", "Do you want to continue?")
                    context = interaction_data.get("context", {})
                    options = interaction_data.get("options", [])
                    choices = interaction_data.get("choices", [])
                    
                    # Update current context
                    current_context.update(context)
                    
                    # Display the question
                    print(f"\nAgent asks: {question}")
                    
                    # Handle different types of interactions
                    if choices:
                        print(f"Choices: {', '.join(f'{i+1}. {choice}' for i, choice in enumerate(choices))}")
                    elif options:
                        print(f"Suggested options: {', '.join(options)}")
                    
                    # Get user response
                    user_response = input("Your response: ").strip()
                
                # Add to conversation history
                conversation_history.append({
                    "interaction_type": interaction_type,
                    "agent_question": interaction_data.get("question", ""),
                    "user_response": user_response,
                    "context": current_context.copy()
                })
                
                # Prepare the continuation input
                context_summary = json.dumps(current_context) if current_context else "previous interaction"
                history_summary = f"Conversation history: {json.dumps(conversation_history[-3:])}" if conversation_history else ""
                
                user_input = (
                    f"Based on {context_summary} and {history_summary}, "
                    f"the user responded: '{user_response}'. Continue the task accordingly."
                )
                continue
            else:
                # Task completed successfully or no user input needed
                return run_result
                    
        except Exception as e:
            print(f"Error during task execution: {e}")
            raise

async def main() -> None:
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        print("Error: MISTRAL_API_KEY not found in environment variables")
        return
        
    client = Mistral(api_key)

    agent_instructions = """
You are an intelligent AI assistant with dynamic server management and self-reasoning capabilities. 

CORE CAPABILITIES:
- Web automation, search, file operations, git, memory, vision, user interaction
- Dynamic server installation and management
- Terminal command execution with user approval
- Self-prompting and iterative reasoning for complex tasks

DYNAMIC SERVER BEHAVIOR:
1. When you lack capabilities for a user request, use the mcp_manager tools to:
   - Search for servers with required capabilities
   - Present installation options to user
   - Handle API key setup instructions
   - Install and configure new servers

2. For terminal commands, ALWAYS use the terminal server tools:
   - Use 'prepare_command_batch' for multiple related commands
   - Use 'execute_command' for single commands  
   - Commands require user approval before execution
   - Show clear descriptions of what each command does

3. For user interaction:
   - Use user_interaction tools when you need clarification
   - Ask before making significant changes
   - Handle ambiguous requests by asking specific questions

4. For complex tasks requiring multi-step reasoning:
   - Use self_prompting tools to break down complex problems
   - Initiate reasoning chains for analysis, planning, or problem-solving
   - Each self-prompt must stay relevant to the original objective
   - Always explain your reasoning process to the user
   - Stop when objective is achieved or no new insights emerge

SELF-PROMPTING GUIDELINES:
- Only use for genuinely complex tasks that benefit from iterative reasoning
- Always ask user permission before starting extended reasoning chains
- Keep each iteration focused and cite specific evidence
- Provide progress updates to user during long reasoning chains
- Maximum 6 iterations per chain unless user explicitly requests more
- If confidence drops or you're repeating ideas, terminate the chain

WORKFLOW EXAMPLES:
- User asks for weather: Search for weather servers → Present installation → Get API key → Install → Use
- User asks to run multiple commands: Batch them → Show all commands → Get approval → Execute approved ones
- User request is ambiguous: Use ask_user to clarify before proceeding
- Complex analysis task: Ask permission → Start self-prompting chain → Provide incremental insights → Present final conclusion

Always be proactive about extending your capabilities while maintaining focused, relevant responses.
"""

    browser_agent = client.beta.agents.create(
        model=MODEL,
        name="Dynamic AI Assistant",
        instructions=agent_instructions,
        description="AI assistant that can dynamically acquire new capabilities by installing MCP servers"
    )

    print(f"Dynamic AI Assistant initialized")
    print(f"Using model: {MODEL}")
    print(f"Log file: {LOG_FILE}")
    print(f"Configuration: mcp_config.json")
    print("\nFeatures:")
    print("- Dynamic server installation")
    print("- Batch terminal command approval") 
    print("- Interactive task pausing")
    print("- Configuration-based server management")
    print("\nType your request and press Enter. Type 'quit' to exit.")
    print("-" * 70)

    try:
        async with RunContext(
            agent_id=browser_agent.id,
            continue_on_fn_error=True,
            output_format=TaskResult,
        ) as run_ctx:
            
            # Load servers from configuration
            loaded_count, failed_count = await setup_mcp_clients(run_ctx)
            print(f"Server status: {loaded_count} loaded, {failed_count} failed")
            print("-" * 70)
            
            while True:
                try:
                    user_input = input(f"\n> ").strip()
                    
                    if user_input.lower() in ['quit', 'exit', 'q']:
                        print("👋 Goodbye!")
                        break
                    
                    if not user_input:
                        continue
                    
                    # Special commands
                    if user_input.lower() == 'list servers':
                        all_servers = config_manager.get_all_servers()
                        print("\nInstalled Servers:")
                        for name, config in all_servers.items():
                            server_type = "default" if config.get("always_load") else "dynamic"
                            print(f"  • {name} ({server_type}) - {config.get('description', 'No description')}")
                        continue
                    
                    if user_input.lower() == 'reload config':
                        config_manager._config = None  # Force reload
                        print("Configuration reloaded")
                        continue
                    
                    # Handle task with possible interruptions
                    run_result = await handle_task_with_interruption(client, run_ctx, user_input)
                    
                    # Extract and display the final response
                    if hasattr(run_result, 'output') and run_result.output:
                        if hasattr(run_result.output, 'result'):
                            response_text = run_result.output.result
                        else:
                            response_text = str(run_result.output)
                    else:
                        response_text = extract_response_content(run_result)
                    
                    print(f"\nTask completed!")
                    print(f"{response_text}")
                    print("-" * 70)
                    
                    # Log the interaction
                    if run_result:
                        tools_used = extract_tools_used(run_result)
                        response_data = {
                            "output": run_result.output if hasattr(run_result, 'output') else None,
                            "text": extract_response_content(run_result)
                        }
                        log_interaction(user_input, tools_used, response_data)
                    
                except KeyboardInterrupt:
                    print("\nRequest interrupted. Type 'quit' to exit or continue with a new request.")
                    continue
                except Exception as e:
                    if "BrokenResourceError" in str(e) or "Shutdown signal received" in str(e):
                        continue
                    else:
                        print(f"Error processing request: {e}")
                        continue
                        
    except Exception as e:
        if "BrokenResourceError" not in str(e) and "Shutdown signal received" not in str(e):
            print(f"Setup error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSession ended by user.")
    except Exception as e:
        print("Session completed successfully.")