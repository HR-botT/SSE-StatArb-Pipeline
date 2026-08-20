import pandas as pd
import numpy as np
from scipy.cluster.hierarchy import linkage, fcluster, dendrogram
from scipy.spatial.distance import squareform
import matplotlib.pyplot as plt
import time

# ---------------- Configuration ----------------
CORR_FILE = "correlation_matrix.csv"          # Correlation matrix from Subtask A
DISTANCE_THRESHOLD = 0.5                      # Cutoff distance threshold (equivalent to correlation > 0.5)
OUTPUT_CLUSTERS_CSV = "stock_clusters.csv"    # Output file: stock -> cluster assignment
OUTPUT_DENDROGRAM_PNG = "dendrogram.png"      # Dendrogram for first 100 stocks

# ---------------- Load correlation matrix ----------------
print("🔄 Loading correlation matrix...")
corr_matrix = pd.read_csv(CORR_FILE, index_col=0)

# Ensure matrix is symmetric and diagonal is 1
codes = corr_matrix.columns.tolist()
print(f"Loaded matrix shape: {corr_matrix.shape}")

# Handle any NaN values (should not exist, but fill with 0 just in case)
if corr_matrix.isna().any().any():
    print("⚠️ NaN values found in matrix, filling with 0")
    corr_matrix = corr_matrix.fillna(0)

# ---------------- Convert correlation to distance ----------------
print("🧮 Converting correlation to distance...")
dist_matrix = 1 - corr_matrix.values

# Set diagonal to 0 and symmetrize
np.fill_diagonal(dist_matrix, 0)
dist_matrix = (dist_matrix + dist_matrix.T) / 2

# Convert to condensed form for scipy
condensed_dist = squareform(dist_matrix)

# ---------------- Hierarchical clustering ----------------
print("🔗 Performing hierarchical clustering (Ward's method)...")
start = time.time()
Z = linkage(condensed_dist, method='ward')
print(f"Clustering completed in {time.time()-start:.2f} seconds")

# ---------------- Cut tree by distance threshold ----------------
clusters = fcluster(Z, t=DISTANCE_THRESHOLD, criterion='distance')
print(f"✅ Number of clusters formed: {len(set(clusters))}")

# ---------------- Save cluster assignments ----------------
cluster_df = pd.DataFrame({'code': codes, 'cluster': clusters})
cluster_df.to_csv(OUTPUT_CLUSTERS_CSV, index=False)
print(f"💾 Cluster assignments saved to {OUTPUT_CLUSTERS_CSV}")

# ---------------- Summary statistics ----------------
print("\n📊 Cluster size distribution (top 20 clusters):")
size_series = cluster_df['cluster'].value_counts().sort_values(ascending=False)
print(size_series.head(20).to_string())

# ---------------- Optional: Dendrogram for first 100 stocks ----------------
try:
    print("\n🌿 Generating dendrogram for first 100 stocks...")
    plt.figure(figsize=(18, 10))
    # Take submatrix of first 100 stocks
    sub_dist = dist_matrix[:100, :100]
    sub_condensed = squareform(sub_dist)
    sub_Z = linkage(sub_condensed, method='ward')
    dendrogram(sub_Z, labels=codes[:100], leaf_rotation=90, leaf_font_size=8)
    plt.title(f"Dendrogram (First 100 Stocks, Distance Threshold = {DISTANCE_THRESHOLD})")
    plt.tight_layout()
    plt.savefig(OUTPUT_DENDROGRAM_PNG, dpi=150)
    plt.close()
    print(f"💾 Dendrogram saved to {OUTPUT_DENDROGRAM_PNG}")
except Exception as e:
    print(f"⚠️ Dendrogram generation failed: {e}")

print("\n✅ Analysis B completed.")