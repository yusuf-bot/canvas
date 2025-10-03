#!/usr/bin/env python3
"""
Simulated Trading Engine MCP Server
Provides tools for managing simulated cryptocurrency trades with realistic features.
"""

import asyncio
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    CallToolRequestParams,
)

# Initialize server
server = Server("trading-engine")

# Configuration
TRADES_CSV = "trades_history.csv"
BALANCE_FILE = "balance.json"
INITIAL_BALANCE = 1000.0  # USDT
DEFAULT_COMMISSION = 0.001  # 0.1%
DEFAULT_ORDER_SIZE = 100.0  # USDT

# CSV Headers
CSV_HEADERS = [
    "trade_id", "timestamp", "token", "direction", "entry_price", 
    "quantity", "leverage", "margin_used", "status", "exit_price", 
    "exit_timestamp", "pnl", "commission", "notes"
]

def ensure_files_exist():
    """Initialize required files if they don't exist"""
    # Initialize trades CSV
    if not os.path.exists(TRADES_CSV):
        with open(TRADES_CSV, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)
    
    # Initialize balance file
    if not os.path.exists(BALANCE_FILE):
        balance_data = {
            "total_balance": INITIAL_BALANCE,
            "available_balance": INITIAL_BALANCE,
            "margin_used": 0.0,
            "unrealized_pnl": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        with open(BALANCE_FILE, 'w') as f:
            json.dump(balance_data, f, indent=2)

def load_balance() -> Dict:
    """Load current balance information"""
    with open(BALANCE_FILE, 'r') as f:
        return json.load(f)

def save_balance(balance_data: Dict):
    """Save balance information"""
    balance_data["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(BALANCE_FILE, 'w') as f:
        json.dump(balance_data, f, indent=2)

def calculate_position_size(order_value: float, leverage: float) -> tuple:
    """Calculate margin required and position size"""
    margin_required = order_value / leverage if leverage > 1 else order_value
    return margin_required, order_value

def get_open_trades() -> List[Dict]:
    """Get all open trades from CSV"""
    trades = []
    try:
        with open(TRADES_CSV, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['status'] == 'open':
                    trades.append(row)
    except FileNotFoundError:
        pass
    return trades

def update_trade_in_csv(trade_id: str, updates: Dict):
    """Update a specific trade in CSV"""
    trades = []
    with open(TRADES_CSV, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['trade_id'] == trade_id:
                row.update(updates)
            trades.append(row)
    
    with open(TRADES_CSV, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(trades)

@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available trading tools"""
    return [
        Tool(
            name="execute_trade",
            description="Execute a new trade (open position)",
            inputSchema={
                "type": "object",
                "properties": {
                    "token": {"type": "string", "description": "Token symbol (e.g., BTC, ETH)"},
                    "direction": {"type": "string", "enum": ["long", "short"], "description": "Trade direction"},
                    "entry_price": {"type": "number", "description": "Entry price in USDT"},
                    "order_value": {"type": "number", "default": DEFAULT_ORDER_SIZE, "description": "Order value in USDT"},
                    "leverage": {"type": "number", "default": 1.0, "description": "Leverage multiplier (1.0 = no leverage)"},
                    "notes": {"type": "string", "description": "Optional trade notes"}
                },
                "required": ["token", "direction", "entry_price"]
            }
        ),
        Tool(
            name="close_trade",
            description="Close an existing trade",
            inputSchema={
                "type": "object",
                "properties": {
                    "trade_id": {"type": "string", "description": "Trade ID to close"},
                    "exit_price": {"type": "number", "description": "Exit price in USDT"},
                    "notes": {"type": "string", "description": "Optional closing notes"}
                },
                "required": ["trade_id", "exit_price"]
            }
        ),
        Tool(
            name="get_portfolio_status",
            description="Get current portfolio balance and open positions",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_trade_history",
            description="Get trade history with optional filters",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["open", "closed", "all"], "default": "all"},
                    "token": {"type": "string", "description": "Filter by specific token"},
                    "limit": {"type": "integer", "default": 50, "description": "Limit number of results"}
                },
                "required": []
            }
        ),
        Tool(
            name="calculate_pnl",
            description="Calculate unrealized PnL for open positions given current prices",
            inputSchema={
                "type": "object",
                "properties": {
                    "current_prices": {
                        "type": "object",
                        "description": "Current prices as {token: price} pairs",
                        "additionalProperties": {"type": "number"}
                    }
                },
                "required": ["current_prices"]
            }
        ),
        Tool(
            name="get_risk_metrics",
            description="Get risk metrics and position sizing recommendations",
            inputSchema={
                "type": "object",
                "properties": {
                    "proposed_order_value": {"type": "number", "description": "Proposed order value to check"},
                    "leverage": {"type": "number", "default": 1.0, "description": "Proposed leverage"}
                },
                "required": []
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any] | None) -> List[TextContent]:
    """Handle tool calls"""
    ensure_files_exist()
    
    if arguments is None:
        arguments = {}
    
    if name == "execute_trade":
        return await execute_trade(arguments)
    elif name == "close_trade":
        return await close_trade(arguments)
    elif name == "get_portfolio_status":
        return await get_portfolio_status(arguments)
    elif name == "get_trade_history":
        return await get_trade_history(arguments)
    elif name == "calculate_pnl":
        return await calculate_pnl(arguments)
    elif name == "get_risk_metrics":
        return await get_risk_metrics(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")

async def execute_trade(args: Dict) -> List[TextContent]:
    """Execute a new trade"""
    token = args["token"].upper()
    direction = args["direction"].lower()
    entry_price = float(args["entry_price"])
    order_value = float(args.get("order_value", DEFAULT_ORDER_SIZE))
    leverage = float(args.get("leverage", 1.0))
    notes = args.get("notes", "")
    
    # Load current balance
    balance_data = load_balance()
    
    # Calculate position requirements
    margin_required, position_value = calculate_position_size(order_value, leverage)
    quantity = position_value / entry_price
    commission = order_value * DEFAULT_COMMISSION
    
    # Check if sufficient balance
    if balance_data["available_balance"] < (margin_required + commission):
        return [TextContent(
            type="text",
            text=f"❌ Insufficient balance. Required: {margin_required + commission:.2f} USDT, Available: {balance_data['available_balance']:.2f} USDT"
        )]
    
    # Generate trade ID
    trade_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Create trade record
    trade_data = [
        trade_id, timestamp, token, direction, entry_price,
        quantity, leverage, margin_required, "open", "", 
        "", "", commission, notes
    ]
    
    # Write to CSV
    with open(TRADES_CSV, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(trade_data)
    
    # Update balance
    balance_data["available_balance"] -= (margin_required + commission)
    balance_data["margin_used"] += margin_required
    balance_data["total_trades"] += 1
    save_balance(balance_data)
    
    result_text = f"""✅ Trade Executed Successfully!
Trade ID: {trade_id}
Token: {token}
Direction: {direction.upper()}
Entry Price: ${entry_price:,.4f}
Quantity: {quantity:.6f}
Order Value: ${order_value:.2f}
Leverage: {leverage}x
Margin Used: ${margin_required:.2f}
Commission: ${commission:.2f}
Status: OPEN

💰 Updated Balance:
Available: ${balance_data['available_balance']:.2f}
Margin Used: ${balance_data['margin_used']:.2f}
"""
    
    return [TextContent(type="text", text=result_text)]

async def close_trade(args: Dict) -> List[TextContent]:
    """Close an existing trade"""
    trade_id = args["trade_id"]
    exit_price = float(args["exit_price"])
    notes = args.get("notes", "")
    
    # Find the trade
    trade_found = None
    with open(TRADES_CSV, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['trade_id'] == trade_id and row['status'] == 'open':
                trade_found = row
                break
    
    if not trade_found:
        return [TextContent(
            type="text",
            text=f"❌ Trade {trade_id} not found or already closed"
        )]
    
    # Calculate PnL
    entry_price = float(trade_found['entry_price'])
    quantity = float(trade_found['quantity'])
    leverage = float(trade_found['leverage'])
    margin_used = float(trade_found['margin_used'])
    direction = trade_found['direction']
    
    if direction == "long":
        price_change = (exit_price - entry_price) / entry_price
    else:  # short
        price_change = (entry_price - exit_price) / entry_price
    
    pnl = margin_used * price_change * leverage
    exit_commission = (quantity * exit_price) * DEFAULT_COMMISSION
    net_pnl = pnl - exit_commission
    
    # Update trade in CSV
    exit_timestamp = datetime.now(timezone.utc).isoformat()
    updates = {
        "status": "closed",
        "exit_price": exit_price,
        "exit_timestamp": exit_timestamp,
        "pnl": net_pnl,
        "notes": f"{trade_found['notes']} | {notes}".strip(" | ")
    }
    update_trade_in_csv(trade_id, updates)
    
    # Update balance
    balance_data = load_balance()
    balance_data["available_balance"] += (margin_used + net_pnl)
    balance_data["margin_used"] -= margin_used
    if net_pnl > 0:
        balance_data["winning_trades"] += 1
    save_balance(balance_data)
    
    pnl_emoji = "🟢" if net_pnl > 0 else "🔴"
    result_text = f"""✅ Trade Closed!
Trade ID: {trade_id}
Token: {trade_found['token']}
Direction: {direction.upper()}
Entry Price: ${entry_price:,.4f}
Exit Price: ${exit_price:,.4f}
Quantity: {quantity:.6f}
{pnl_emoji} Net P&L: ${net_pnl:.2f}
Exit Commission: ${exit_commission:.2f}

💰 Updated Balance:
Available: ${balance_data['available_balance']:.2f}
Total Balance: ${balance_data['available_balance'] + balance_data['margin_used']:.2f}
"""
    
    return [TextContent(type="text", text=result_text)]

async def get_portfolio_status(args: Dict) -> List[TextContent]:
    """Get current portfolio status"""
    balance_data = load_balance()
    open_trades = get_open_trades()
    
    total_balance = balance_data['available_balance'] + balance_data['margin_used']
    win_rate = (balance_data['winning_trades'] / max(balance_data['total_trades'], 1)) * 100
    
    status_text = f"""📊 Portfolio Status
💰 Balance:
  • Total: ${total_balance:.2f}
  • Available: ${balance_data['available_balance']:.2f}
  • Margin Used: ${balance_data['margin_used']:.2f}

📈 Trading Stats:
  • Total Trades: {balance_data['total_trades']}
  • Winning Trades: {balance_data['winning_trades']}
  • Win Rate: {win_rate:.1f}%
  • Open Positions: {len(open_trades)}

🔓 Open Positions:"""
    
    if open_trades:
        for trade in open_trades:
            status_text += f"""
  • {trade['trade_id'][:8]} | {trade['token']} {trade['direction'].upper()} | ${float(trade['entry_price']):,.4f} | {trade['leverage']}x"""
    else:
        status_text += "\n  • No open positions"
    
    return [TextContent(type="text", text=status_text)]

async def get_trade_history(args: Dict) -> List[TextContent]:
    """Get trade history with filters"""
    status_filter = args.get("status", "all")
    token_filter = args.get("token", "").upper()
    limit = args.get("limit", 50)
    
    trades = []
    with open(TRADES_CSV, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if status_filter != "all" and row['status'] != status_filter:
                continue
            if token_filter and row['token'] != token_filter:
                continue
            trades.append(row)
    
    # Sort by timestamp (most recent first) and limit
    trades = sorted(trades, key=lambda x: x['timestamp'], reverse=True)[:limit]
    
    history_text = f"📜 Trade History (Filter: {status_filter}, Limit: {limit})\n\n"
    
    for trade in trades:
        status_emoji = "🔓" if trade['status'] == 'open' else "🔒"
        pnl_text = ""
        if trade['pnl']:
            pnl = float(trade['pnl'])
            pnl_emoji = "🟢" if pnl > 0 else "🔴"
            pnl_text = f" | P&L: {pnl_emoji}${pnl:.2f}"
        
        history_text += f"""{status_emoji} {trade['trade_id'][:8]} | {trade['token']} {trade['direction'].upper()} | ${float(trade['entry_price']):,.4f} | {trade['leverage']}x{pnl_text}
"""
    
    if not trades:
        history_text += "No trades found matching criteria."
    
    return [TextContent(type="text", text=history_text)]

async def calculate_pnl(args: Dict) -> List[TextContent]:
    """Calculate unrealized PnL for open positions"""
    current_prices = args["current_prices"]
    open_trades = get_open_trades()
    
    if not open_trades:
        return [TextContent(type="text", text="📊 No open positions to calculate PnL")]
    
    total_unrealized_pnl = 0.0
    pnl_text = "📊 Unrealized P&L Analysis\n\n"
    
    for trade in open_trades:
        token = trade['token']
        if token not in current_prices:
            pnl_text += f"❌ {token}: No current price available\n"
            continue
        
        entry_price = float(trade['entry_price'])
        current_price = float(current_prices[token])
        quantity = float(trade['quantity'])
        leverage = float(trade['leverage'])
        margin_used = float(trade['margin_used'])
        direction = trade['direction']
        
        if direction == "long":
            price_change = (current_price - entry_price) / entry_price
        else:  # short
            price_change = (entry_price - current_price) / entry_price
        
        unrealized_pnl = margin_used * price_change * leverage
        total_unrealized_pnl += unrealized_pnl
        
        pnl_emoji = "🟢" if unrealized_pnl > 0 else "🔴"
        change_pct = price_change * 100
        
        pnl_text += f"""{pnl_emoji} {trade['trade_id'][:8]} | {token} {direction.upper()}
  Entry: ${entry_price:,.4f} → Current: ${current_price:,.4f} ({change_pct:+.2f}%)
  Unrealized P&L: ${unrealized_pnl:.2f}

"""
    
    pnl_text += f"💰 Total Unrealized P&L: ${total_unrealized_pnl:.2f}"
    
    return [TextContent(type="text", text=pnl_text)]

async def get_risk_metrics(args: Dict) -> List[TextContent]:
    """Get risk metrics and recommendations"""
    balance_data = load_balance()
    open_trades = get_open_trades()
    
    proposed_order = args.get("proposed_order_value", 0)
    proposed_leverage = args.get("leverage", 1.0)
    
    total_balance = balance_data['available_balance'] + balance_data['margin_used']
    margin_usage = (balance_data['margin_used'] / total_balance) * 100
    
    risk_text = f"""⚖️ Risk Analysis
📊 Current Risk Metrics:
  • Total Balance: ${total_balance:.2f}
  • Margin Usage: {margin_usage:.1f}%
  • Open Positions: {len(open_trades)}
  • Available Balance: ${balance_data['available_balance']:.2f}

🛡️ Risk Recommendations:
"""
    
    # Risk level assessment
    if margin_usage < 20:
        risk_level = "🟢 LOW"
        recommendation = "Safe to open new positions"
    elif margin_usage < 50:
        risk_level = "🟡 MODERATE"
        recommendation = "Consider position sizing carefully"
    else:
        risk_level = "🔴 HIGH"
        recommendation = "Reduce exposure before new trades"
    
    risk_text += f"  • Risk Level: {risk_level}\n  • {recommendation}\n"
    
    if proposed_order > 0:
        margin_needed = proposed_order / proposed_leverage if proposed_leverage > 1 else proposed_order
        new_margin_usage = ((balance_data['margin_used'] + margin_needed) / total_balance) * 100
        
        risk_text += f"\n💭 Proposed Trade Analysis:\n"
        risk_text += f"  • Order Value: ${proposed_order:.2f}\n"
        risk_text += f"  • Leverage: {proposed_leverage}x\n"
        risk_text += f"  • Margin Required: ${margin_needed:.2f}\n"
        risk_text += f"  • New Margin Usage: {new_margin_usage:.1f}%\n"
        
        if balance_data['available_balance'] >= margin_needed:
            if new_margin_usage < 70:
                risk_text += "  • ✅ Trade approved - within risk limits"
            else:
                risk_text += "  • ⚠️ High risk - consider reducing size"
        else:
            risk_text += "  • ❌ Insufficient balance for this trade"
    
    return [TextContent(type="text", text=risk_text)]

async def main():
    """Main entry point for the trading engine server"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())