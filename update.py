import csv
import time
import requests
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient

# ================= Configuration =================
MONGO_URI = "mongodb://127.0.0.1:27017/?directConnection=true"
DATABASE_NAME = "stock_history"
COLLECTION_NAME = "sh_daily"
CSV_FILE = "sse_codes.csv"          # Stock code list file
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
PROXY = None                         # If proxy is needed, e.g., {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}

# ================= Connect to MongoDB =================
client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]
coll = db[COLLECTION_NAME]

def load_stock_codes(filename=CSV_FILE):
    """Read stock codes from CSV (automatically handles BOM)."""
    codes = []
    try:
        with open(filename, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            for row in reader:
                if row and row[0].strip():
                    codes.append(row[0].strip())
        print(f"✅ Read {len(codes)} stock codes from {filename}")
        return codes
    except FileNotFoundError:
        print(f"❌ File not found: {filename}. Please check the file location.")
        return []

def get_latest_date(code):
    """Get the latest date of a stock in the database (UTC), returns None if not found."""
    result = coll.find_one(
        {"metadata.code": code},
        sort=[("date", -1)],
        projection={"date": 1}
    )
    if result and "date" in result:
        return result["date"]  # datetime object (may be UTC)
    return None

def fetch_and_store_incremental(code):
    """Incrementally fetch and insert new data for a single stock."""
    latest_date = get_latest_date(code)

    # Fix: MongoDB returns naive datetime, convert to UTC-aware
    if latest_date and latest_date.tzinfo is None:
        latest_date = latest_date.replace(tzinfo=timezone.utc)

    if latest_date:
        # Start from the next calendar day at UTC midnight
        start_dt = datetime.combine(
            latest_date.date() + timedelta(days=1),
            datetime.min.time(),
            tzinfo=timezone.utc
        )
    else:
        # New stock: start from 2010-01-01
        start_dt = datetime(2010, 1, 1, tzinfo=timezone.utc)

    # If start date is later than today (i.e., already up to date), skip
    if start_dt > datetime.now(timezone.utc):
        print(f"⏭️ {code}: Already up to date, skipping")
        return

    start_unix = int(start_dt.timestamp())
    end_unix = int(datetime.now().timestamp())

    yahoo_symbol = f"{code}.SS"
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?"
        f"period1={start_unix}&period2={end_unix}&interval=1d&events=history"
        f"&includeAdjustedClose=true"
    )

    try:
        resp = requests.get(url, headers=HEADERS, proxies=PROXY, timeout=20)
        if resp.status_code == 429:
            print(f"⚠️ {code}: Rate limited, waiting 10 seconds...")
            time.sleep(10)
            return
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
            print(f"⏭️ {code}: No new data")
            return

        quote = result["indicators"]["quote"][0]
        adjclose = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])

        docs = []
        for i, ts in enumerate(timestamps):
            if quote["open"][i] is None or quote["close"][i] is None:
                continue

            date_obj = datetime.fromtimestamp(ts, tz=timezone.utc)
            # Ensure we only insert data later than the latest date
            if latest_date and date_obj <= latest_date:
                continue

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
            print(f"✅ {code}: Inserted {len(docs)} new records")
        else:
            print(f"⏭️ {code}: No new data (or already exists)")

    except Exception as e:
        print(f"❌ {code}: Update failed - {e}")
def main():
    codes = load_stock_codes()
    if not codes:
        print("No stock codes found, exiting")
        return

    print(f"🚀 Starting incremental update for {len(codes)} stocks...")
    start_time = time.time()

    for i, code in enumerate(codes):
        fetch_and_store_incremental(code)
        # Yahoo rate limit: wait 2 seconds per stock (incremental update has small data volume, can be slightly faster, but conservative 2 seconds)
        time.sleep(2)
        if (i + 1) % 50 == 0:
            print(f"📊 Progress: {i+1}/{len(codes)}")

    elapsed = time.time() - start_time
    print(f"🎉 Incremental update completed! Total time: {elapsed/60:.2f} minutes")

if __name__ == "__main__":
    main() 