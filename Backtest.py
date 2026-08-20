import pandas as pd
import numpy as np
from pymongo import MongoClient
from statsmodels.tsa.stattools import adfuller
import statsmodels.api as sm
import matplotlib.pyplot as plt
import warnings
import time

warnings.filterwarnings("ignore")

# ================= Configuration =================
MONGO_URI = "mongodb://127.0.0.1:27017/?directConnection=true"
DATABASE_NAME = "stock_history"
COLLECTION_NAME = "sh_daily"
CLUSTERS_FILE = "stock_clusters.csv"

EST_WINDOW = 250                # lookback days for estimation
REBALANCE_INTERVAL = 20        # rebalance frequency (trading days)
Z_ENTRY = 2.0
Z_EXIT = 0.5
Z_STOP = 3.5
MAX_HOLDING_DAYS = 20
CORR_THRESHOLD = 0.8           # minimum correlation for candidate pairs
MAX_TOTAL_PAIRS = 200          # maximum number of pairs to consider globally
MAX_PAIRS_PER_CLUSTER = 2      # maximum pairs from the same cluster

COMMISSION = 0.0002
STAMP_DUTY = 0.0005
SLIPPAGE = 0.001
INITIAL_CAPITAL = 1_000_000
CAPITAL_PER_TRADE = 100_000

# Set date range for backtest; use None for full history after initial window
START_DATE = "2015-01-01"
END_DATE = "2026-08-17"

# ================= Load data =================
print("Loading data from MongoDB...")
client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]
coll = db[COLLECTION_NAME]

cursor = coll.find({}, {"_id": 0, "date": 1, "metadata.code": 1, "adj_close": 1})
df = pd.DataFrame(list(cursor))
df["date"] = pd.to_datetime(df["date"])
df["code"] = df["metadata"].apply(lambda x: x["code"])

price = df.pivot(index="date", columns="code", values="adj_close").sort_index()
print(f"Price matrix shape: {price.shape}")

# Load cluster map
clusters = pd.read_csv(CLUSTERS_FILE, dtype={"code": str, "cluster": int})
cluster_map = dict(zip(clusters["code"], clusters["cluster"]))
print(f"Loaded clusters for {len(cluster_map)} stocks")

# Keep only stocks with cluster info
common_codes = [c for c in price.columns if c in cluster_map]
price = price[common_codes]
print(f"Stocks in universe: {len(common_codes)}")

# Filter by date range
if START_DATE:
    price = price[price.index >= START_DATE]
if END_DATE:
    price = price[price.index <= END_DATE]

# ================= Helper functions =================
def select_pairs_global(returns_window, cluster_map, corr_threshold=0.8,
                        max_total_pairs=200, max_pairs_per_cluster=2):
    """
    Select candidate pairs globally based on correlation and same-cluster membership.
    Returns dict {(stockA, stockB): {'beta': 1.0, 'alpha': 0.0}} (placeholders)
    """
    # Compute full correlation matrix
    corr_matrix = returns_window.corr(method='pearson')
    
    # Get upper triangle (excluding diagonal)
    corr_pairs = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)).stack()
    corr_pairs = corr_pairs[corr_pairs > corr_threshold].sort_values(ascending=False)
    
    selected_pairs = {}
    cluster_pair_count = {}  # track number of selected pairs per cluster
    
    for (a, b), corr in corr_pairs.items():
        if len(selected_pairs) >= max_total_pairs:
            break
        
        # Ensure both stocks are in the same cluster
        cl_a = cluster_map.get(a)
        cl_b = cluster_map.get(b)
        if cl_a is None or cl_b is None or cl_a != cl_b:
            continue
        
        # Check per-cluster limit
        cluster_id = cl_a
        count = cluster_pair_count.get(cluster_id, 0)
        if count >= max_pairs_per_cluster:
            continue
        
        selected_pairs[(a, b)] = {'beta': 1.0, 'alpha': 0.0}
        cluster_pair_count[cluster_id] = count + 1
    
    return selected_pairs

# ================= Main backtest loop =================
def run_backtest():
    dates = price.index.tolist()
    n_dates = len(dates)
    if n_dates <= EST_WINDOW:
        print("Not enough data for estimation window.")
        return

    cash = INITIAL_CAPITAL
    positions = {}
    equity_curve = []
    trade_log = []
    active_pairs = {}

    start_time = time.time()

    for i in range(EST_WINDOW, n_dates):
        today = dates[i]
        current_prices = price.iloc[i]

        # Print progress every 50 trading days
        if (i - EST_WINDOW) % 50 == 0:
            elapsed = time.time() - start_time
            print(f"Processing day {i-EST_WINDOW}/{n_dates-EST_WINDOW} (elapsed {elapsed:.1f}s)")

        # Rebalance
        if (i - EST_WINDOW) % REBALANCE_INTERVAL == 0:
            window_start = i - EST_WINDOW
            window_end = i
            prices_window = price.iloc[window_start:window_end]
            returns_window = np.log(prices_window / prices_window.shift(1)).dropna(how='all')
            
            # Select candidate pairs
            selected_pairs = select_pairs_global(
                returns_window, cluster_map,
                corr_threshold=CORR_THRESHOLD,
                max_total_pairs=MAX_TOTAL_PAIRS,
                max_pairs_per_cluster=MAX_PAIRS_PER_CLUSTER
            )
            print(f"  Selected {len(selected_pairs)} candidate pairs")

            # Filter by cointegration and estimate beta/alpha
            filtered_pairs = {}
            for pair in list(selected_pairs.keys()):
                a, b = pair
                if a not in prices_window.columns or b not in prices_window.columns:
                    continue
                log_a = np.log(prices_window[a])
                log_b = np.log(prices_window[b])
                valid = ~(log_a.isna() | log_b.isna())
                if valid.sum() < 100:
                    continue
                log_a = log_a[valid]
                log_b = log_b[valid]
                X = sm.add_constant(log_b)
                model = sm.OLS(log_a, X).fit()
                beta = model.params.iloc[1]
                alpha = model.params.iloc[0]
                resid = model.resid
                adf_p = adfuller(resid, autolag='AIC')[1]
                if adf_p < 0.05:
                    filtered_pairs[pair] = {'beta': beta, 'alpha': alpha}
            active_pairs = filtered_pairs
            print(f"  After cointegration filter: {len(active_pairs)} pairs")

        # Trading signals for active pairs
        for pair, params in active_pairs.items():
            a, b = pair
            if a not in price.columns or b not in price.columns:
                continue

            # Compute spread and z-score
            lookback = min(60, i)
            hist_a = price[a].iloc[max(0, i-lookback):i+1]
            hist_b = price[b].iloc[max(0, i-lookback):i+1]
            valid = ~(hist_a.isna() | hist_b.isna())
            if valid.sum() < 10:
                continue
            hist_a = hist_a[valid]
            hist_b = hist_b[valid]
            beta = params['beta']
            alpha = params['alpha']
            spread = np.log(hist_a) - beta * np.log(hist_b) - alpha
            if len(spread) < 10:
                continue
            z = (spread.iloc[-1] - spread.mean()) / spread.std()

            # Check existing position
            if pair in positions:
                pos = positions[pair]
                days_held = (today - pos['entry_date']).days
                if abs(z) < Z_EXIT or days_held >= MAX_HOLDING_DAYS or abs(z) > Z_STOP:
                    # Close position
                    exit_a = current_prices.get(a, np.nan)
                    exit_b = current_prices.get(b, np.nan)
                    if pd.isna(exit_a) or pd.isna(exit_b):
                        continue
                    if pos['direction'] == 'long':
                        pnl_a = (exit_a - pos['entry_a']) * pos['shares_a']
                        pnl_b = (pos['entry_b'] - exit_b) * pos['shares_b']
                    else:
                        pnl_a = (pos['entry_a'] - exit_a) * pos['shares_a']
                        pnl_b = (exit_b - pos['entry_b']) * pos['shares_b']
                    total_cost = (COMMISSION * 2 * (pos['entry_a'] * pos['shares_a'] + pos['entry_b'] * pos['shares_b']) +
                                  STAMP_DUTY * (pos['entry_a'] * pos['shares_a'] + pos['entry_b'] * pos['shares_b']) +
                                  SLIPPAGE * (pos['entry_a'] * pos['shares_a'] + pos['entry_b'] * pos['shares_b']))
                    pnl = pnl_a + pnl_b - total_cost
                    cash += pnl
                    trade_log.append({
                        'pair': f"{a}-{b}",
                        'entry_date': pos['entry_date'],
                        'exit_date': today,
                        'direction': pos['direction'],
                        'pnl': pnl
                    })
                    del positions[pair]
            else:
                # Entry logic
                if z > Z_ENTRY:
                    direction = 'short'   # short A, long B
                elif z < -Z_ENTRY:
                    direction = 'long'    # long A, short B
                else:
                    continue
                entry_a = current_prices.get(a, np.nan)
                entry_b = current_prices.get(b, np.nan)
                if pd.isna(entry_a) or pd.isna(entry_b):
                    continue
                shares_a = CAPITAL_PER_TRADE / entry_a
                shares_b = CAPITAL_PER_TRADE / entry_b
                cost = (COMMISSION * (entry_a * shares_a + entry_b * shares_b) +
                        SLIPPAGE * (entry_a * shares_a + entry_b * shares_b))
                cash -= cost
                positions[pair] = {
                    'entry_date': today,
                    'direction': direction,
                    'entry_a': entry_a,
                    'entry_b': entry_b,
                    'shares_a': shares_a,
                    'shares_b': shares_b,
                    'value': (shares_a * entry_a) + (shares_b * entry_b)
                }

        # Record equity
        total_value = cash
        for pos in positions.values():
            total_value += pos['value']
        equity_curve.append((today, total_value))

    # ================= Results =================
    equity_df = pd.DataFrame(equity_curve, columns=['date', 'equity'])
    equity_df.set_index('date', inplace=True)
    equity_df.to_csv("equity_curve.csv")
    trade_log_df = pd.DataFrame(trade_log)
    trade_log_df.to_csv("trade_log.csv", index=False)

    if len(equity_df) > 1:
        daily_returns = equity_df['equity'].pct_change().dropna()
        total_return = equity_df['equity'].iloc[-1] / equity_df['equity'].iloc[0] - 1
        years = (equity_df.index[-1] - equity_df.index[0]).days / 365.25
        annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
        sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() != 0 else 0
        max_drawdown = (equity_df['equity'] / equity_df['equity'].cummax() - 1).min()
        win_rate = (trade_log_df['pnl'] > 0).mean() if len(trade_log_df) > 0 else 0

        print("\n================ Backtest Results ================")
        print(f"Total return: {total_return:.2%}")
        print(f"Annualized return: {annual_return:.2%}")
        print(f"Sharpe ratio: {sharpe:.2f}")
        print(f"Max drawdown: {max_drawdown:.2%}")
        print(f"Win rate: {win_rate:.2%}")
        print(f"Number of trades: {len(trade_log_df)}")
        print("==================================================")

        plt.figure(figsize=(12, 6))
        plt.plot(equity_df.index, equity_df['equity'], label='Strategy Equity')
        plt.title("Backtest Equity Curve")
        plt.xlabel("Date")
        plt.ylabel("Equity")
        plt.legend()
        plt.grid(True)
        plt.savefig("equity_curve.png", dpi=150)
        plt.close()
        print("Equity curve saved to equity_curve.png")

    return equity_df, trade_log_df

if __name__ == "__main__":
    run_backtest()