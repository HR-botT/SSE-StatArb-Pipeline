import csv
import time
import requests
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient

# ================= Configuration =================
# MongoDB connection
MONGO_URI = "mongodb://127.0.0.1:27017/?directConnection=true"
DATABASE_NAME = "stock_history"
COLLECTION_NAME = "sh_daily"

# Yahoo Finance request headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Proxy settings (set to None if no proxy needed)
PROXY = None
# If you need a proxy, uncomment and set:
# PROXY = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}

# CSV file containing stock codes (one code per line, no header)
CSV_FILE = "sse_codes.csv"

# ================= MongoDB Initialization =================
client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]

# Create time-series collection if it doesn't exist
if COLLECTION_NAME not in db.list_collection_names():
    db.create_collection(
        COLLECTION_NAME,
        timeseries={
            "timeField": "date",
            "metaField": "metadata",
            "granularity": "hours"
        }
    )
    print(f"✅ Created time-series collection '{COLLECTION_NAME}'")
else:
    print(f"✅ Collection '{COLLECTION_NAME}' already exists")

coll = db[COLLECTION_NAME]

# ================= Stock Code Loading =================
def load_stock_codes_from_csv(filename=CSV_FILE):
    """Read stock codes from a CSV file. Expects one 6-digit code per line."""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            codes = [row[0].strip() for row in reader if row and row[0].strip()]
        print(f"✅ Loaded {len(codes)} stock codes from {filename}")
        return codes
    except FileNotFoundError:
        print(f"❌ File '{filename}' not found. Please place it in the script directory.")
        return []

# ================= Yahoo Finance Data Fetch =================
def fetch_and_store_yahoo(code):
    """
    Fetch daily historical data for one SSE stock (.SS) from Yahoo Finance
    and store it in MongoDB.
    """
    yahoo_symbol = f"{code}.SS"
    start_unix = int(datetime(2010, 1, 1).timestamp())
    end_unix = int(datetime.now().timestamp())

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?"
        f"period1={start_unix}&period2={end_unix}&interval=1d&events=history"
        f"&includeAdjustedClose=true"
    )

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, proxies=PROXY, timeout=20)
            if resp.status_code == 429:
                print(f"⚠️ {code}: Rate limited (429), waiting 10 seconds...")
                time.sleep(10)
                continue
            if resp.status_code != 200:
                print(f"⚠️ {code}: HTTP {resp.status_code}")
                return

            data = resp.json()
            if "chart" not in data or data["chart"]["error"] or not data["chart"]["result"]:
                print(f"⚠️ {code}: No data from Yahoo")
                return

            result = data["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            if not timestamps:
                print(f"⚠️ {code}: No timestamps")
                return

            quote = result["indicators"]["quote"][0]
            adjclose = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])

            docs = []
            for i, ts in enumerate(timestamps):
                # Skip rows with missing open or close
                if quote["open"][i] is None or quote["close"][i] is None:
                    continue

                date_obj = datetime.fromtimestamp(ts, tz=timezone.utc)
                open_price = float(quote["open"][i])
                high_price = float(quote["high"][i])
                low_price = float(quote["low"][i])
                close_price = float(quote["close"][i])
                volume = int(quote["volume"][i]) if quote["volume"][i] is not None else 0
                adj_close = float(adjclose[i]) if i < len(adjclose) and adjclose[i] is not None else close_price

                doc = {
                    "date": date_obj,
                    "metadata": {"code": code},
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "close": close_price,
                    "adj_close": adj_close,
                    "volume": volume
                }
                docs.append(doc)

            if docs:
                coll.insert_many(docs, ordered=False)
                print(f"✅ {code}: inserted {len(docs)} records")
            else:
                print(f"⚠️ {code}: no valid data")
            return  # success

        except Exception as e:
            print(f"⚠️ {code}: attempt {attempt+1} failed - {e}")
            time.sleep(5 * (attempt + 1))   # exponential backoff

    print(f"❌ {code}: ultimately failed after 3 attempts")

# ================= Main =================
def main():
    codes = load_stock_codes_from_csv()
    if not codes:
        print("❌ No stock codes found. Exiting.")
        return

    print(f"🚀 Starting download for {len(codes)} stocks from Yahoo Finance...")
    start_time = time.time()

    for i, code in enumerate(codes):
        fetch_and_store_yahoo(code)
        # Yahoo free tier: 2.5 seconds between requests
        time.sleep(2.5)
        if (i + 1) % 10 == 0:
            print(f"📊 Progress: {i+1}/{len(codes)}")
            time.sleep(5)   # extra pause every 10 stocks

    elapsed = time.time() - start_time
    print(f"🎉 All done! Total time: {elapsed/60:.2f} minutes")

if __name__ == "__main__":
    main()