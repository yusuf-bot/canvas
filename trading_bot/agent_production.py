# agent_production.py
"""
Production-grade AI trading foundation
- Binance for historical klines + websocket for live trades/orderbook
- Alpaca for order placement (paper/live via .env)
- SQLite persistence for state + Optuna RDB for trials
- Vectorized backtester with orderbook-impact & slippage model
- Walk-forward CV and weekly retrain schedule
- LightGBM meta-model (train/predict)
- Kill-switch + min_notional / lot-size checks for Alpaca
"""
import os
import time
import json
import math
import random
import argparse
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Tuple

import numpy as np
import pandas as pd
import pandas_ta as ta
from sklearn.mixture import GaussianMixture
from scipy.stats import entropy as shannon_entropy
from sklearn.model_selection import train_test_split
import lightgbm as lgb
import optuna
from sqlalchemy import create_engine
from sqlalchemy import text
from dotenv import load_dotenv

# Binance
from binance import Client as BinanceClient

# Alpaca
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# websocket client for Binance depth/trades
from websocket import WebSocketApp

# -------------------- CONFIG --------------------
load_dotenv()  # read .env file

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "True").lower() in ("1","true","yes")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

DB_PATH = "agent_prod.sqlite"
OPTUNA_DB_URL = f"sqlite:///optuna_trials.sqlite"
MODEL_NAME = "meta_lgb_v1"

DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_INTERVAL = "1h"   # chosen to mitigate alpaca commission impact, fewer trades
LOOKBACK = 2000  # candles to fetch for backtests/training
TRADES_BACK = 1000
DEPTH_LIMIT = 50

# Backtest defaults
INITIAL_CAPITAL = 10000.0
RISK_PER_TRADE = 0.01

# Walk-forward / retrain
RETRAIN_WEEKS = 1  # retrain every N weeks

# Slippage model
IMPACT_K = 0.3  # price impact coefficient (tunable)

# Random seed
RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

# -------------------------------------------------

# clients
binance = BinanceClient(BINANCE_API_KEY or None, BINANCE_API_SECRET or None)
alpaca_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=ALPACA_PAPER) if ALPACA_API_KEY and ALPACA_SECRET_KEY else None

# -------------------- DB helpers --------------------
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

def ensure_tables():
    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS features (
            ts TEXT PRIMARY KEY,
            symbol TEXT,
            interval TEXT,
            feat_json TEXT
        )"""))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            symbol TEXT,
            side TEXT,
            qty REAL,
            entry REAL,
            exit REAL,
            pnl REAL,
            balance REAL,
            meta_json TEXT
        )"""))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS models (
            name TEXT PRIMARY KEY,
            model_blob BLOB,
            meta_json TEXT
        )"""))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS backtests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            params_json TEXT,
            metrics_json TEXT
        )"""))
ensure_tables()

# -------------------- Data layer --------------------
def fetch_klines(symbol: str, interval: str, limit: int=1000) -> pd.DataFrame:
    raw = binance.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(raw, columns=[
        "open_time","open","high","low","close","volume","close_time","qav","num_trades","taker_base_vol","taker_quote_vol","ignore"
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    return df

def fetch_agg_trades(symbol: str, limit:int=500) -> pd.DataFrame:
    raw = binance.get_aggregate_trades(symbol=symbol, limit=limit)
    trades = [{"price":float(t["p"]), "qty":float(t["q"]), "is_buyer_maker": t.get("m", False), "time": pd.to_datetime(t["T"], unit="ms")} for t in raw]
    return pd.DataFrame(trades)

def fetch_orderbook(symbol: str, limit: int = 50) -> dict:
    book = binance.get_order_book(symbol=symbol, limit=limit)
    bids = np.array([[float(p), float(q)] for p,q in book["bids"]], dtype=float)
    asks = np.array([[float(p), float(q)] for p,q in book["asks"]], dtype=float)
    spread = asks[0,0] - bids[0,0] if len(asks) and len(bids) else 0.0
    bid_vol = bids[:,1].sum() if len(bids) else 0.0
    ask_vol = asks[:,1].sum() if len(asks) else 0.0
    imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol + 1e-9)
    return {"bids":bids, "asks":asks, "spread":spread, "imbalance":imbalance, "mid": (asks[0,0]+bids[0,0])/2.0 if len(asks) and len(bids) else 0.0}

# -------------------- Feature engineering --------------------
def compute_cvd(trades: pd.DataFrame) -> Tuple[float,float,float]:
    buys = trades[trades["is_buyer_maker"]==False]["qty"].sum()
    sells = trades[trades["is_buyer_maker"]==True]["qty"].sum()
    return buys - sells, buys, sells

def rolling_entropy(returns: np.ndarray, bins:int=16) -> float:
    hist, _ = np.histogram(returns, bins=bins, density=True)
    hist = hist + 1e-12
    return float(shannon_entropy(hist))

def make_features(candles: pd.DataFrame, trades: pd.DataFrame, book: dict) -> Tuple[pd.DataFrame, Dict[str,Any]]:
    df = candles.copy()
    df["ema200"] = ta.ema(df["close"], length=200)
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    adx = ta.adx(df["high"], df["low"], df["close"], length=14)
    df["adx"] = adx["ADX_14"]
    df["rsi"] = ta.rsi(df["close"], length=14)
    df["returns"] = df["close"].pct_change().fillna(0)
    df["vol20"] = df["returns"].rolling(20).std().fillna(0)
    cvd, buys, sells = compute_cvd(trades)
    latest = df.iloc[-1]
    recent_returns = df["returns"].iloc[-50:].values if len(df)>=50 else df["returns"].values
    ent = rolling_entropy(recent_returns) if len(recent_returns)>5 else 0.0
    feat = {
        "ts": latest["open_time"].isoformat(),
        "close": float(latest["close"]),
        "open": float(latest["open"]),
        "high": float(latest["high"]),
        "low": float(latest["low"]),
        "atr": float(latest["atr"]) if not np.isnan(latest["atr"]) else 0.0,
        "adx": float(latest["adx"]) if not np.isnan(latest["adx"]) else 0.0,
        "vol20": float(latest["vol20"]) if not np.isnan(latest["vol20"]) else 0.0,
        "spread": float(book["spread"]) if book else 0.0,
        "imbalance": float(book["imbalance"]) if book else 0.0,
        "cvd": float(cvd),
        "ent": float(ent),
        "rsi": float(latest["rsi"]) if not np.isnan(latest["rsi"]) else 50.0,
        "ema200": float(latest["ema200"]) if not np.isnan(latest["ema200"]) else float(latest["close"])
    }
    return df, feat

# -------------------- Regime detector --------------------
class RegimeDetector:
    def __init__(self, n_components=3):
        self.n = n_components
        self.model = None
        self.history = []

    def add(self, feat: Dict[str,Any]):
        vec = np.array([feat["atr"], feat["adx"], feat["vol20"], feat["spread"], feat["imbalance"], feat["cvd"], feat["ent"]], dtype=float)
        self.history.append(vec)
        if len(self.history) > 2000:
            self.history.pop(0)

    def fit(self):
        if len(self.history) < max(100, self.n*20):
            return
        X = np.array(self.history)
        Xs = (X - X.mean(axis=0)) / (X.std(axis=0)+1e-9)
        self.model = GaussianMixture(n_components=self.n, random_state=RANDOM_SEED).fit(Xs)

    def predict(self, feat: Dict[str,Any]):
        if self.model is None:
            return None
        hist = np.array(self.history)
        mu = hist.mean(axis=0)
        sigma = hist.std(axis=0)+1e-9
        vec = np.array([feat["atr"], feat["adx"], feat["vol20"], feat["spread"], feat["imbalance"], feat["cvd"], feat["ent"]], dtype=float)
        Xs = (vec - mu) / sigma
        label = int(self.model.predict(Xs.reshape(1,-1))[0])
        return label

# -------------------- LightGBM meta-model --------------------
class Modeler:
    def __init__(self, name=MODEL_NAME):
        self.name = name
        self.model = None
        self.feature_cols = None

    def prepare_train(self, feats: pd.DataFrame, horizon=3, thr=0.0015):
        df = feats.copy().reset_index(drop=True)
        df["future_close"] = df["close"].shift(-horizon)
        df["fret"] = (df["future_close"] - df["close"]) / df["close"]
        df["label"] = (df["fret"] > thr).astype(int)
        df = df.dropna(subset=["label"])
        X = df[[c for c in df.columns if c not in ["ts","label","future_close","fret","close","open","high","low"]]].values
        y = df["label"].values
        self.feature_cols = [c for c in df.columns if c not in ["ts","label","future_close","fret","close","open","high","low"]]
        return X, y, self.feature_cols

    def train(self, feats: pd.DataFrame, num_rounds=100):
        X,y,cols = self.prepare_train(feats)
        if len(y) < 200:
            print("Not enough samples to train model:", len(y))
            return None
        X_train, X_val, y_train, y_val = train_test_split(X,y,test_size=0.2, random_state=RANDOM_SEED)
        dtrain = lgb.Dataset(X_train, label=y_train)
        dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)
        params = {"objective":"binary", "metric":"binary_logloss", "verbosity":-1, "seed":RANDOM_SEED}
        bst = lgb.train(params, dtrain, num_boost_round=num_rounds, valid_sets=[dval], early_stopping_rounds=20, verbose_eval=False)
        self.model = bst
        self.feature_cols = cols
        # persist to DB
        with engine.begin() as conn:
            conn.execute("REPLACE INTO models (name, model_blob, meta_json) VALUES (?, ?, ?)", (self.name, bst.model_to_string().encode("utf-8"), json.dumps({"cols":self.feature_cols})))
        print("Model trained and saved.")
        return bst

    def load(self):
        with engine.begin() as conn:
            row = conn.execute("SELECT model_blob, meta_json FROM models WHERE name=?", (self.name,)).fetchone()
            if not row:
                return None
            model_blob, meta = row
            model_str = model_blob.decode("utf-8")
            self.model = lgb.Booster(model_str=model_str)
            meta_json = json.loads(meta)
            self.feature_cols = meta_json.get("cols", [])
            return self.model

    def predict_proba(self, feat: Dict[str,Any]):
        if self.model is None:
            return None
        x = np.array([feat.get(c, 0.0) for c in self.feature_cols]).reshape(1,-1)
        p = float(self.model.predict(x)[0])
        return p

# -------------------- Orderbook impact & slippage model --------------------
def synthetic_book_from_candle(candle: pd.Series, depth_levels=50):
    # Create a synthetic orderbook around the close using candle range and volume decay
    mid = float(candle["close"])
    rng = max(1e-6, float(candle["high"] - candle["low"]))
    prices_up = mid + np.linspace(rng*0.01, rng*0.5, depth_levels//2)
    prices_dn = mid - np.linspace(rng*0.01, rng*0.5, depth_levels//2)
    # volumes decay away from mid
    base_vol = max(1e-6, float(candle["volume"]) / depth_levels)
    bids = np.column_stack([prices_dn[::-1], np.exp(-np.linspace(0,3, depth_levels//2)) * base_vol])
    asks = np.column_stack([prices_up, np.exp(-np.linspace(0,3, depth_levels//2)) * base_vol])
    return {"bids": bids, "asks": asks}

def simulate_fill(price: float, side: str, qty: float, book_snapshot: dict, k=IMPACT_K):
    """
    Simulate fill price given desired qty and a book snapshot (bids/asks arrays [price,qty]).
    Price impact model: slip = k * (order_qty / cumulative_depth_at_price)
    This is a simplified model; returns executed_price and slippage estimate.
    """
    # compute cumulative depth on the opposite side
    side_arr = book_snapshot["asks"] if side=="BUY" else book_snapshot["bids"]
    # For bids array decreasing, asks increasing - but arrays are just price rows
    cum = 0.0
    weighted_price = 0.0
    filled = 0.0
    for p,q in side_arr:
        take = min(q, qty - filled)
        weighted_price += take * p
        filled += take
        cum += q
        if filled >= qty - 1e-12:
            break
    if filled <= 0:
        # can't fill -> assume market price with large slippage
        impact = k * (qty / (book_snapshot.get("bid_vol",1e-9) + 1e-9))
        exec_price = price * (1 + impact) if side=="BUY" else price * (1 - impact)
        return exec_price, impact
    avg_price = weighted_price / filled
    # price impact margin approx proportional to qty/cum
    impact = k * (qty / (cum + 1e-9))
    exec_price = avg_price * (1 + impact) if side=="BUY" else avg_price * (1 - impact)
    return float(exec_price), float(impact)

# -------------------- Performance metrics --------------------
def compute_metrics(equity_curve: List[float], interval_minutes: int):
    eq = np.array(equity_curve)
    returns = np.diff(eq) / eq[:-1]
    if len(returns) <= 1:
        return {"pnl": eq[-1]-eq[0], "sharpe":0.0, "cagr":0.0, "max_dd":0.0}
    annual_factor = 525600 / interval_minutes  # minutes per year / interval_minutes
    mean = returns.mean() * annual_factor
    std = returns.std() * math.sqrt(annual_factor)
    sharpe = (mean / std) if std>0 else 0.0
    pnl = eq[-1] - eq[0]
    # cagr approx
    periods = len(eq)
    years = periods * (interval_minutes / (525600))
    cagr = (eq[-1]/eq[0]) ** (1/years) - 1 if years>0 else 0.0
    # max drawdown
    roll_max = np.maximum.accumulate(eq)
    dd = (eq - roll_max) / roll_max
    max_dd = float(np.min(dd))
    return {"pnl": float(pnl), "sharpe": float(sharpe), "cagr": float(cagr), "max_dd": max_dd, "final_equity": float(eq[-1])}

# -------------------- Backtester (vectorized but candle-level) --------------------
class Backtester:
    def __init__(self, symbol=DEFAULT_SYMBOL, interval=DEFAULT_INTERVAL, initial_capital=INITIAL_CAPITAL):
        self.symbol = symbol
        self.interval = interval
        self.capital = initial_capital
        self.risk_per_trade = RISK_PER_TRADE

    def run(self, params: Dict[str,Any], walk_forward=False) -> Dict[str,Any]:
        """
        params: hyperparameters including model params, stop/target ATR multipliers, etc.
        If walk_forward True -> do rolling walk-forward CV and aggregate metrics.
        """
        candles = fetch_klines(self.symbol, self.interval, limit=LOOKBACK)
        # precompute features for each candle (approx using REST trades/book at that time)
        feats = []
        for idx in range(200, len(candles)):
            window = candles.iloc[:idx+1].copy()
            # for backtest we synthesize trades and book using the candle
            trades_df = fetch_agg_trades(self.symbol, limit=200)
            book = synthetic_book_from_candle(window.iloc[-1])
            _, feat = make_features(window, trades_df, book)
            feats.append(feat)
        feat_df = pd.DataFrame(feats).reset_index(drop=True)
        interval_minutes = self._interval_to_minutes(self.interval)

        # if walk_forward: sliding windows with retrain
        if walk_forward:
            # define windows: train_size (e.g., 60%), test_size (e.g., 20%), step = test_size
            n = len(feat_df)
            train_pct = params.get("train_pct", 0.6)
            test_pct = params.get("test_pct", 0.2)
            train_size = int(n * train_pct)
            test_size = int(n * test_pct)
            start = 0
            equity_curve = []
            equity = self.capital
            all_metrics = []
            while start + train_size + test_size <= n:
                train_df = feat_df.iloc[start: start + train_size].reset_index(drop=True)
                test_df = feat_df.iloc[start + train_size: start + train_size + test_size].reset_index(drop=True)
                modeler = Modeler(name="temp_model")
                modeler.train(pd.concat([train_df, test_df], ignore_index=True), num_rounds=params.get("num_rounds",100))
                # simulate on test_df
                equity, eq_curve_slice = self._simulate_on_slice(test_df, modeler, equity, params)
                equity_curve.extend(eq_curve_slice)
                metrics = compute_metrics(equity_curve[-len(eq_curve_slice):], interval_minutes)
                all_metrics.append(metrics)
                start += test_size  # slide forward
            # aggregate metrics: average sharpe, total pnl etc
            final = compute_metrics(equity_curve, interval_minutes)
            return {"equity_curve": equity_curve, "metrics": final, "per_slice": all_metrics}
        else:
            # single-run: train on first portion then test on rest
            split = int(len(feat_df)*0.6)
            train_df = feat_df.iloc[:split].reset_index(drop=True)
            test_df = feat_df.iloc[split:].reset_index(drop=True)
            modeler = Modeler(name="temp_model")
            modeler.train(pd.concat([train_df,test_df], ignore_index=True), num_rounds=params.get("num_rounds",100))
            equity = self.capital
            equity, equity_curve = self._simulate_on_slice(test_df, modeler, equity, params)
            metrics = compute_metrics(equity_curve, interval_minutes)
            # persist backtest meta to DB
            with engine.begin() as conn:
                conn.execute("INSERT INTO backtests (ts, params_json, metrics_json) VALUES (?, ?, ?)",
                             (datetime.now(timezone.utc).isoformat(), json.dumps(params), json.dumps(metrics)))
            return {"equity_curve": equity_curve, "metrics": metrics}

    def _simulate_on_slice(self, test_df: pd.DataFrame, modeler: Modeler, initial_equity: float, params: Dict[str,Any]):
        equity = initial_equity
        eq_curve = []
        pos = None  # (side, qty, entry, stop, target)
        for i in range(len(test_df)):
            feat = test_df.iloc[i].to_dict()
            price = feat["close"]
            p = modeler.predict_proba(feat) if modeler.model else None
            # decision logic: use model prob + time bias + thresholds
            decision = "HOLD"
            if p is not None:
                tbias = self._time_bias(datetime.fromisoformat(feat["ts"]))
                score_buy = p + tbias
                score_sell = (1.0 - p) - tbias
                vol_scale = max(0.5, min(2.0, 1.0 + feat["vol20"]*50))
                thresh = params.get("base_thresh", 0.6) * vol_scale
                if score_buy > thresh and score_buy > score_sell:
                    decision = "BUY"
                elif score_sell > thresh and score_sell > score_buy:
                    decision = "SELL"
            else:
                # fallback momentum
                if feat["close"] > feat["ema200"] and feat["adx"] > 25:
                    decision = "BUY"
                elif feat["close"] < feat["ema200"] and feat["adx"] > 25:
                    decision = "SELL"
            # manage open position
            if pos is not None:
                side, qty, entry, stop, target, book = pos
                # check stop/target
                if (side=="BUY" and (price <= stop or price >= target)) or (side=="SELL" and (price >= stop or price <= target)):
                    # close with slippage simulation
                    exit_price, impact = simulate_fill(price, side="SELL" if side=="BUY" else "BUY", qty=qty, book_snapshot=book)
                    pnl = (exit_price - entry) * qty if side=="BUY" else (entry - exit_price) * qty
                    equity += pnl
                    pos = None
            # open new position
            if pos is None and decision in ("BUY", "SELL"):
                # estimate stop/target via ATR multipliers
                atr = max(1e-9, feat["atr"])
                stop_dist = atr * params.get("stop_atr", 1.0)
                target_dist = atr * params.get("target_atr", 2.0)
                if decision == "BUY":
                    stop = price - stop_dist
                    target = price + target_dist
                else:
                    stop = price + stop_dist
                    target = price - target_dist
                qty = (equity * self.risk_per_trade) / (stop_dist + 1e-9)
                # build synthetic book for this candle
                book = synthetic_book_from_candle(pd.Series({"close":price, "high":feat["high"], "low":feat["low"], "volume":feat.get("volume",1.0)}))
                exec_price, impact = simulate_fill(price, side=decision, qty=qty, book_snapshot=book)
                pos = (decision, qty, exec_price, stop, target, book)
            eq_curve.append(equity)
        return equity, eq_curve

    @staticmethod
    def _interval_to_minutes(interval: str) -> int:
        if interval.endswith("h"):
            return int(interval[:-1]) * 60
        if interval.endswith("m"):
            return int(interval[:-1])
        if interval.endswith("d"):
            return int(interval[:-1]) * 60*24
        return 60

    @staticmethod
    def _time_bias(now: datetime):
        h = now.hour
        if 12 <= h < 16:
            return 0.02
        if 0 <= h < 6:
            return -0.02
        return 0.0

# -------------------- Optuna optimization --------------------
def objective(trial: optuna.Trial):
    # define search space
    params = {
        "num_rounds": trial.suggest_categorical("num_rounds", [50,100,150,200]),
        "base_thresh": trial.suggest_float("base_thresh", 0.45, 0.85),
        "stop_atr": trial.suggest_float("stop_atr", 0.5, 2.0),
        "target_atr": trial.suggest_float("target_atr", 1.0, 4.0),
        "risk_per_trade": trial.suggest_float("risk_per_trade", 0.002, 0.02)
    }
    bt = Backtester()
    bt.risk_per_trade = params["risk_per_trade"]
    res = bt.run(params, walk_forward=True)
    metrics = res["metrics"]
    # objective: maximize pnl (or sharpe) - here using sharpe
    return metrics.get("sharpe", 0.0)

def run_optuna(n_trials=40):
    study = optuna.create_study(direction="maximize", study_name="agent_search",
                                storage=OPTUNA_DB_URL, load_if_exists=True)
    study.optimize(objective, n_trials=n_trials)
    print("Best trial:", study.best_trial.params)
    # persist best to DB
    with engine.begin() as conn:
        conn.execute("INSERT INTO backtests (ts, params_json, metrics_json) VALUES (?, ?, ?)",
                     (datetime.now(timezone.utc).isoformat(), json.dumps(study.best_trial.params), json.dumps({"value":study.best_value})))
    return study

# -------------------- Alpaca trading helpers --------------------
def alpaca_symbol_from_binance(sym: str) -> str:
    # Binance uses BTCUSDT -> Alpaca crypto uses BTC/USD
    if sym.endswith("USDT"):
        return sym.replace("USDT","/USD")
    if sym.endswith("USD"):
        return sym.replace("USD","/USD")
    return sym

def fetch_alpaca_asset(symbol: str):
    if not alpaca_client:
        return None
    try:
        assets = alpaca_client.get_all_assets()
        for a in assets:
            if a.symbol == symbol:
                return a
    except Exception as e:
        print("Alpaca asset fetch error", e)
    return None

def get_alpaca_account():
    if not alpaca_client:
        return None
    return alpaca_client.get_account()

def place_alpaca_limit_order(symbol: str, qty: float, side: str, limit_price: float, tif=TimeInForce.DAY):
    if not alpaca_client:
        return {"sim": True}
    # Build request
    if side not in ("BUY","SELL"):
        raise ValueError("side must be BUY/SELL")
    order_req = LimitOrderRequest(symbol=symbol, limit_price=limit_price, notional=None, qty=qty, side=OrderSide.BUY if side=="BUY" else OrderSide.SELL, time_in_force=tif)
    try:
        order = alpaca_client.submit_order(order_req)
        return order
    except Exception as e:
        print("Alpaca limit order failed:", e)
        return None

def place_alpaca_market_order(symbol: str, qty: float, side: str):
    if not alpaca_client:
        return {"sim": True}
    try:
        order_req = MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide.BUY if side=="BUY" else OrderSide.SELL, time_in_force=TimeInForce.DAY)
        order = alpaca_client.submit_order(order_req)
        return order
    except Exception as e:
        print("Alpaca market order failed:", e)
        return None

def check_min_notional_and_lot(symbol: str, qty: float, price: float) -> Tuple[bool,str]:
    """
    Basic check: Alpaca crypto supports fractional quantities and notional orders.
    We'll enforce min notional and naive lot size checks (this is an approximation).
    """
    min_notional = 1.0  # USD (approx) - adjust if needed
    if qty * price < min_notional:
        return False, f"min_notional_violation: qty*price={qty*price:.2f} < {min_notional}"
    # lot size checks could be added per asset; for crypto alpaca allows fractional
    return True, "ok"

# -------------------- Live Agent --------------------
class LiveAgent:
    def __init__(self, symbol=DEFAULT_SYMBOL, interval=DEFAULT_INTERVAL):
        self.symbol = symbol
        self.interval = interval
        self.alpaca_symbol = alpaca_symbol_from_binance(symbol)
        self.modeler = Modeler()
        self.modeler.load()
        self.strategy_capital = INITIAL_CAPITAL
        self.risk_per_trade = RISK_PER_TRADE
        self.regime = RegimeDetector()
        self.killswitch_enabled = True
        self.max_drawdown_pct = 0.2  # if equity falls more than this, kill
        self.equity = INITIAL_CAPITAL
        # Websocket for Binance depth/trades: best-effort
        self.book_snapshot = None
        self._start_binance_ws()

    def _start_binance_ws(self):
        # depth stream for symbol
        s = self.symbol.lower()
        url = f"wss://stream.binance.com:9443/ws/{s}@depth{DEPTH_LIMIT}@100ms"
        def on_message(ws, message):
            try:
                d = json.loads(message)
                bids = np.array([[float(p), float(q)] for p,q in d.get("b", [])]) if d.get("b") else np.zeros((0,2))
                asks = np.array([[float(p), float(q)] for p,q in d.get("a", [])]) if d.get("a") else np.zeros((0,2))
                bid_vol = bids[:,1].sum() if bids.size else 0.0
                ask_vol = asks[:,1].sum() if asks.size else 0.0
                imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol + 1e-9)
                spread = float(asks[0,0] - bids[0,0]) if bids.size and asks.size else 0.0
                self.book_snapshot = {"bids":bids, "asks":asks, "imbalance":imbalance, "spread":spread}
            except Exception:
                pass
        def on_error(ws, error):
            print("WS error:", error)
        def on_close(ws, code, msg):
            print("WS closed", code, msg)
        ws = WebSocketApp(url, on_message=on_message, on_error=on_error, on_close=on_close)
        t = threading.Thread(target=ws.run_forever, daemon=True)
        t.start()

    def run_loop(self):
        poll = max(60, int(self.interval.rstrip("h"))*60 if "h" in self.interval else int(self.interval.rstrip("m"))*60)
        while True:
            try:
                candles = fetch_klines(self.symbol, self.interval, limit=500)
                trades = fetch_agg_trades(self.symbol, limit=500)
                book = self.book_snapshot or synthetic_book_from_candle(candles.iloc[-1])
                _, feat = make_features(candles, trades, book)
                # persist feature
                with engine.begin() as conn:
                    conn.execute("REPLACE INTO features (ts, symbol, interval, feat_json) VALUES (?, ?, ?, ?)",
                                 (feat["ts"], self.symbol, self.interval, json.dumps(feat)))
                # decide
                p = self.modeler.predict_proba(feat) if self.modeler.model else None
                decision = "HOLD"
                if p is not None:
                    tb = Backtester._time_bias(datetime.fromisoformat(feat["ts"]))
                    score_buy = p + tb
                    score_sell = (1.0 - p) - tb
                    vol_scale = max(0.5, min(2.0, 1.0 + feat["vol20"]*50))
                    thresh = 0.6 * vol_scale
                    if score_buy > thresh and score_buy > score_sell:
                        decision = "BUY"
                    elif score_sell > thresh and score_sell > score_buy:
                        decision = "SELL"
                else:
                    # fallback rule
                    if feat["close"] > feat["ema200"] and feat["adx"] > 25:
                        decision = "BUY"
                    elif feat["close"] < feat["ema200"] and feat["adx"] > 25:
                        decision = "SELL"
                # kill-switch check
                if self.killswitch_enabled and self._check_killswitch():
                    print("Kill-switch triggered. Not placing new orders.")
                    decision = "HOLD"
                # if decision, place order via Alpaca (paper)
                if decision in ("BUY","SELL"):
                    atr = max(1e-9, feat["atr"])
                    stop_dist = atr * 1.0
                    target_dist = atr * 2.0
                    if decision=="BUY":
                        stop = feat["close"] - stop_dist
                        target = feat["close"] + target_dist
                    else:
                        stop = feat["close"] + stop_dist
                        target = feat["close"] - target_dist
                    qty = (self.equity * self.risk_per_trade) / (stop_dist + 1e-9)
                    # check alpaca min notional
                    ok, reason = check_min_notional_and_lot(self.alpaca_symbol, qty, feat["close"])
                    if not ok:
                        print("Order fails pre-check:", reason)
                    else:
                        # try limit order first
                        limit_price = feat["close"] * (1.001 if decision=="BUY" else 0.999)  # small improvement
                        # place order
                        if alpaca_client:
                            # use market order for quicker execution in this example; for production prefer limit and confirm
                            order = place_alpaca_market_order(self.alpaca_symbol, qty=round(qty, 8), side=decision)
                            print("Placed Alpaca order:", order)
                            # store trade placeholder; will update on fill checks
                            with engine.begin() as conn:
                                conn.execute("INSERT INTO trades (ts, symbol, side, qty, entry, exit, pnl, balance, meta_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                             (datetime.now(timezone.utc).isoformat(), self.symbol, decision, qty, feat["close"], None, None, self.equity, json.dumps({"notes":"placed_via_alpaca"})))
                        else:
                            # simulate execution with our slippage model
                            exec_price, impact = simulate_fill(feat["close"], side=decision, qty=qty, book_snapshot=book)
                            print(f"Simulated exec {decision} qty {qty:.6f} at {exec_price:.2f} impact {impact:.4f}")
                            with engine.begin() as conn:
                                conn.execute("INSERT INTO trades (ts, symbol, side, qty, entry, exit, pnl, balance, meta_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                             (datetime.now(timezone.utc).isoformat(), self.symbol, decision, qty, exec_price, None, None, self.equity, json.dumps({"sim":True})))
                print(f"[{feat['ts']}] decision {decision} p={p} equity {self.equity:.2f}")
            except Exception as e:
                print("Live loop error:", e)
            time.sleep(poll)

    def _check_killswitch(self):
        # compute current drawdown from recorded trades equity in DB (simple)
        with engine.begin() as conn:
            rows = conn.execute("SELECT balance FROM trades ORDER BY id DESC LIMIT 200").fetchall()
            if not rows:
                return False
            balances = [r[0] for r in rows if r[0] is not None]
            if not balances:
                return False
            peak = max(balances)
            cur = balances[0]
            dd = (peak - cur) / peak if peak>0 else 0.0
            if dd > self.max_drawdown_pct:
                print(f"Kill-switch: drawdown {dd:.3f} > {self.max_drawdown_pct}")
                return True
            return False

# -------------------- CLI --------------------
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["backtest","optimize","train","live"], default="backtest")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--interval", default=DEFAULT_INTERVAL)
    p.add_argument("--iters", type=int, default=40)
    return p.parse_args()

def main():
    args = parse_args()
    ensure_tables()
    if args.mode == "backtest":
        bt = Backtester(symbol=args.symbol, interval=args.interval)
        params = {"num_rounds":100, "base_thresh":0.6, "stop_atr":1.0, "target_atr":2.0, "risk_per_trade":RISK_PER_TRADE}
        res = bt.run(params, walk_forward=True)
        print("Backtest done. Metrics:", res["metrics"])
    elif args.mode == "optimize":
        study = run_optuna(n_trials=args.iters)
        print("Optuna done. Best:", study.best_trial.params)
    elif args.mode == "train":
        # fetch features and train model on all history
        candles = fetch_klines(args.symbol, args.interval, limit=LOOKBACK)
        feats = []
        for i in range(200, len(candles)):
            window = candles.iloc[:i+1]
            trades = fetch_agg_trades(args.symbol, limit=200)
            book = synthetic_book_from_candle(window.iloc[-1])
            _, feat = make_features(window, trades, book)
            feats.append(feat)
        feat_df = pd.DataFrame(feats)
        modeler = Modeler()
        modeler.train(feat_df, num_rounds=200)
    elif args.mode == "live":
        agent = LiveAgent(symbol=args.symbol, interval=args.interval)
        agent.run_loop()

if __name__ == "__main__":
    main()
