import pandas as pd
import numpy as np
from pymongo import MongoClient
import time
import os

# ---------------- Configuration ----------------
MONGO_URI = "mongodb://127.0.0.1:27017/?directConnection=true"
DATABASE_NAME = "stock_history"
COLLECTION_NAME = "sh_daily"

# Time window for correlation analysis (in years)
LOOKBACK_YEARS = 2

# Minimum proportion of non-NaN returns required for a stock
MIN_DATA_RATIO = 0.8

# Output files
OUTPUT_CORR_CSV = "correlation_matrix.csv"
OUTPUT_TOP_PAIRS_CSV = "top_correlated_pairs.csv"
OUTPUT_HEATMAP_PNG = "correlation_heatmap_top50.png"

# ---------------- Connect to MongoDB ----------------
print("🔄 Connecting to MongoDB...")
client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]
coll = db[COLLECTION_NAME]

# ---------------- Load data ----------------
print("📥 Loading data from MongoDB (this may take a few minutes)...")
start_time = time.time()

cursor = coll.find(
    {},  # all documents
    {"_id": 0, "date": 1, "metadata.code": 1, "adj_close": 1}  # projection
)

df = pd.DataFrame(list(cursor))
print(f"✅ Loaded {len(df)} documents in {time.time()-start_time:.2f} seconds")

# ---------------- Pivot to price matrix ----------------
df["date"] = pd.to_datetime(df["date"])
df["code"] = df["metadata"].apply(lambda x: x["code"])

price_df = df.pivot(index="date", columns="code", values="adj_close")
price_df = price_df.sort_index()
print(f"Price matrix shape: {price_df.shape} (dates × stocks)")

# ---------------- Select recent time window ----------------
end_date = price_df.index.max()
start_date = end_date - pd.DateOffset(years=LOOKBACK_YEARS)
price_recent = price_df.loc[start_date:end_date]
print(f"Selected data from {start_date.date()} to {end_date.date()}")

# ---------------- Compute daily log returns ----------------
print("🧮 Calculating daily log returns...")
returns = np.log(price_recent / price_recent.shift(1)).dropna(how='all')
print(f"Returns matrix shape: {returns.shape}")

# ---------------- Filter stocks with insufficient data ----------------
min_non_nan = int(len(returns) * MIN_DATA_RATIO)
returns = returns.dropna(axis=1, thresh=min_non_nan)
print(f"After filtering, {returns.shape[1]} stocks remain (≥ {MIN_DATA_RATIO*100:.0f}% data)")

# ---------------- Compute Pearson correlation matrix ----------------
print("📈 Computing correlation matrix (may take several minutes)...")
corr_matrix = returns.corr(method='pearson')
print(f"Correlation matrix shape: {corr_matrix.shape}")

# ---------------- Save correlation matrix ----------------
corr_matrix.to_csv(OUTPUT_CORR_CSV)
print(f"💾 Correlation matrix saved to {OUTPUT_CORR_CSV}")

# ---------------- Find top correlated pairs ----------------
print("🔍 Finding top correlated pairs (excluding self-correlations)...")
corr_unstacked = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)).stack()
top_pairs = corr_unstacked.sort_values(ascending=False).head(50)

top_pairs_df = pd.DataFrame({
    'Stock A': top_pairs.index.get_level_values(0),
    'Stock B': top_pairs.index.get_level_values(1),
    'Correlation': top_pairs.values
})

top_pairs_df.to_csv(OUTPUT_TOP_PAIRS_CSV, index=False)
print(f"💾 Top 50 correlated pairs saved to {OUTPUT_TOP_PAIRS_CSV}")

# Print top 10 pairs
print("\n🔝 Top 10 most correlated pairs:")
print(top_pairs_df.head(10).to_string(index=False))

# ---------------- Plot heatmap for top 50 stocks ----------------
try:
    import matplotlib.pyplot as plt
    import seaborn as sns

    print("🌡️ Generating heatmap for first 50 stocks...")
    # Select top 50 stocks by average correlation (or simply first 50)
    top50_codes = corr_matrix.columns[:50]
    plt.figure(figsize=(14, 12))
    sns.heatmap(corr_matrix.loc[top50_codes, top50_codes],
                cmap='coolwarm', center=0, vmin=-1, vmax=1,
                square=True, linewidths=0.1, xticklabels=True, yticklabels=True)
    plt.title(f"Correlation Heatmap (Top 50 Stocks, {LOOKBACK_YEARS}Y)")
    plt.tight_layout()
    plt.savefig(OUTPUT_HEATMAP_PNG, dpi=150)
    plt.close()
    print(f"💾 Heatmap saved to {OUTPUT_HEATMAP_PNG}")
except ImportError:
    print("⚠️ matplotlib/seaborn not installed. Skipping heatmap. Install with: pip install matplotlib seaborn")
except Exception as e:
    print(f"⚠️ Heatmap generation failed: {e}")

print("\n✅ Analysis A completed.")