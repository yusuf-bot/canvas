#!/usr/bin/env python3
"""
Enhanced MCP STDIO server with self-prompting capabilities.
"""

import asyncio
import json
import time
from typing import Any, Dict
from dataclasses import dataclass, asdict
from datetime import datetime

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
)

# Create server instance
server = Server("enhanced-stdio-server")

@dataclass
class SelfPromptSession:
    session_id: str
    original_objective: str
    current_iteration: int
    max_iterations: int
    conversation_history: list
    start_time: float
    last_progress_check: str
    confidence_scores: list
    status: str  # "active", "completed", "terminated"

# Global state for self-prompting sessions
active_sessions: Dict[str, SelfPromptSession] = {}

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="sleep",
            description="Pause execution for a given number of seconds",
            inputSchema={
                "type": "object",
                "properties": {
                    "seconds": {
                        "type": "integer",
                        "description": "Number of seconds to sleep"
                    }
                },
                "required": ["seconds"]
            }
        ),
        Tool(
            name="initiate_self_reasoning",
            description="Start a self-prompting reasoning chain for complex tasks. Use only when task genuinely requires iterative analysis.",
            inputSchema={
                "type": "object",
                "properties": {
                    "objective": {
                        "type": "string",
                        "description": "The main objective or question to reason about"
                    },
                    "initial_context": {
                        "type": "string",
                        "description": "Initial information or context for the reasoning"
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Maximum number of reasoning iterations (default: 5, max: 8)",
                        "default": 5
                    },
                    "confidence_threshold": {
                        "type": "number",
                        "description": "Minimum confidence score to continue (0.0-1.0, default: 0.6)",
                        "default": 0.6
                    }
                },
                "required": ["objective", "initial_context"]
            }
        ),
        Tool(
            name="continue_self_reasoning",
            description="Continue an active self-reasoning chain with new insights",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "ID of the active reasoning session"
                    },
                    "new_insight": {
                        "type": "string",
                        "description": "New insight or reasoning step"
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Supporting evidence or data for this insight"
                    },
                    "confidence_score": {
                        "type": "number",
                        "description": "Confidence in this insight (0.0-1.0)"
                    },
                    "next_question": {
                        "type": "string",
                        "description": "Next question to explore, or 'COMPLETE' if objective is achieved"
                    }
                },
                "required": ["session_id", "new_insight", "confidence_score"]
            }
        ),
        Tool(
            name="terminate_self_reasoning",
            description="Terminate an active self-reasoning session",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "ID of the session to terminate"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for termination"
                    },
                    "final_conclusion": {
                        "type": "string",
                        "description": "Final conclusion or summary"
                    }
                },
                "required": ["session_id", "reason"]
            }
        ),
        Tool(
            name="get_reasoning_status",
            description="Check the status of active reasoning sessions",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Optional: specific session ID to check"
                    }
                }
            }
        )
    ]

def generate_session_id() -> str:
    """Generate a unique session ID."""
    return f"reasoning_{int(time.time() * 1000)}"

def calculate_relevance_score(text: str, objective: str) -> float:
    """Simple relevance scoring (you could enhance this with NLP)."""
    objective_words = set(objective.lower().split())
    text_words = set(text.lower().split())
    
    if not objective_words:
        return 0.0
    
    overlap = len(objective_words.intersection(text_words))
    return min(1.0, overlap / len(objective_words))

def detect_repetition(history: list, new_insight: str) -> bool:
    """Detect if the new insight is too similar to previous ones."""
    if len(history) < 2:
        return False
    
    recent_insights = [entry.get('insight', '') for entry in history[-3:]]
    new_words = set(new_insight.lower().split())
    
    for insight in recent_insights:
        insight_words = set(insight.lower().split())
        overlap = len(new_words.intersection(insight_words))
        similarity = overlap / max(len(new_words), len(insight_words), 1)
        if similarity > 0.7:  # High similarity threshold
            return True
    
    return False

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any] | None) -> list[TextContent]:
    """Handle tool calls."""
    if arguments is None:
        arguments = {}

    if name == "sleep":
        seconds = arguments.get("seconds", 1)
        await asyncio.sleep(seconds)
        return [TextContent(
            type="text",
            text=f"Slept for {seconds} seconds."
        )]

    elif name == "initiate_self_reasoning":
        objective = arguments.get("objective", "")
        initial_context = arguments.get("initial_context", "")
        max_iterations = min(arguments.get("max_iterations", 5), 8)  # Cap at 8
        confidence_threshold = arguments.get("confidence_threshold", 0.6)
        
        session_id = generate_session_id()
        
        session = SelfPromptSession(
            session_id=session_id,
            original_objective=objective,
            current_iteration=0,
            max_iterations=max_iterations,
            conversation_history=[{
                "iteration": 0,
                "context": initial_context,
                "timestamp": datetime.now().isoformat()
            }],
            start_time=time.time(),
            last_progress_check="initialized",
            confidence_scores=[],
            status="active"
        )
        
        active_sessions[session_id] = session
        
        response = {
            "type": "reasoning_initiated",
            "session_id": session_id,
            "message": f"Self-reasoning session started for: {objective}",
            "max_iterations": max_iterations,
            "initial_context": initial_context,
            "instructions": "Use 'continue_self_reasoning' to add insights and progress through the reasoning chain."
        }
        
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    elif name == "continue_self_reasoning":
        session_id = arguments.get("session_id", "")
        new_insight = arguments.get("new_insight", "")
        evidence = arguments.get("evidence", "")
        confidence_score = arguments.get("confidence_score", 0.0)
        next_question = arguments.get("next_question", "")
        
        if session_id not in active_sessions:
            return [TextContent(
                type="text",
                text=json.dumps({"error": "Session not found or already terminated"})
            )]
        
        session = active_sessions[session_id]
        
        if session.status != "active":
            return [TextContent(
                type="text",
                text=json.dumps({"error": f"Session is {session.status}, cannot continue"})
            )]
        
        # Guardrails checks
        checks = []
        
        # 1. Iteration limit
        if session.current_iteration >= session.max_iterations:
            session.status = "terminated"
            checks.append("Maximum iterations reached")
        
        # 2. Relevance check
        relevance = calculate_relevance_score(new_insight, session.original_objective)
        if relevance < 0.3:
            checks.append(f"Low relevance to objective (score: {relevance:.2f})")
        
        # 3. Repetition check
        if detect_repetition(session.conversation_history, new_insight):
            checks.append("Repetitive insight detected")
        
        # 4. Confidence degradation
        session.confidence_scores.append(confidence_score)
        if len(session.confidence_scores) >= 2:
            recent_avg = sum(session.confidence_scores[-2:]) / 2
            if recent_avg < 0.4:
                checks.append(f"Low confidence trend (avg: {recent_avg:.2f})")
        
        # 5. Time limit (optional - 10 minutes)
        elapsed_time = time.time() - session.start_time
        if elapsed_time > 600:  # 10 minutes
            checks.append("Time limit exceeded")
        
        # Update session
        session.current_iteration += 1
        session.conversation_history.append({
            "iteration": session.current_iteration,
            "insight": new_insight,
            "evidence": evidence,
            "confidence": confidence_score,
            "next_question": next_question,
            "timestamp": datetime.now().isoformat(),
            "relevance_score": relevance
        })
        
        # Determine if should continue
        should_terminate = bool(checks) or next_question.upper() == "COMPLETE"
        
        if should_terminate:
            session.status = "completed" if next_question.upper() == "COMPLETE" else "terminated"
            
            response = {
                "type": "reasoning_completed",
                "session_id": session_id,
                "status": session.status,
                "total_iterations": session.current_iteration,
                "final_insight": new_insight,
                "termination_reasons": checks if checks else ["Objective completed"],
                "conversation_summary": session.conversation_history,
                "average_confidence": sum(session.confidence_scores) / len(session.confidence_scores) if session.confidence_scores else 0.0
            }
        else:
            response = {
                "type": "reasoning_continued",
                "session_id": session_id,
                "iteration": session.current_iteration,
                "insight_accepted": True,
                "relevance_score": relevance,
                "confidence_score": confidence_score,
                "next_question": next_question,
                "remaining_iterations": session.max_iterations - session.current_iteration
            }
        
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    elif name == "terminate_self_reasoning":
        session_id = arguments.get("session_id", "")
        reason = arguments.get("reason", "Manual termination")
        final_conclusion = arguments.get("final_conclusion", "")
        
        if session_id in active_sessions:
            session = active_sessions[session_id]
            session.status = "terminated"
            
            response = {
                "type": "reasoning_terminated",
                "session_id": session_id,
                "reason": reason,
                "final_conclusion": final_conclusion,
                "iterations_completed": session.current_iteration,
                "summary": session.conversation_history
            }
        else:
            response = {"error": "Session not found"}
        
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    elif name == "get_reasoning_status":
        session_id = arguments.get("session_id")
        
        if session_id:
            if session_id in active_sessions:
                session = active_sessions[session_id]
                response = {
                    "session": asdict(session),
                    "elapsed_time": time.time() - session.start_time
                }
            else:
                response = {"error": "Session not found"}
        else:
            response = {
                "active_sessions": len([s for s in active_sessions.values() if s.status == "active"]),
                "total_sessions": len(active_sessions),
                "session_ids": list(active_sessions.keys())
            }
        
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    else:
        raise ValueError(f"Unknown tool: {name}")

async def main():
    """Main entry point for the server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())