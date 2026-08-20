from fastapi import FastAPI, Query, HTTPException
from pymongo import MongoClient
from datetime import datetime, date, timezone

# Create FastAPI app
app = FastAPI(title="Stock Data API")

# Connect to MongoDB (ensure local MongoDB service is running)
client = MongoClient("mongodb://127.0.0.1:27017/?directConnection=true")
db = client["stock_history"]
coll = db["sh_daily"]

@app.get("/api/stock_data")
def get_stock_data(
    ticker: str = Query(..., description="Stock ticker, e.g., 600000"),
    start: date = Query(..., description="Start date YYYY-MM-DD"),
    end: date = Query(..., description="End date YYYY-MM-DD"),
    fields: str = Query("open,high,low,close,volume,adj_close", description="Comma-separated list of desired fields")
):
    """
    Return time series data based on ticker, date range, and requested fields.
    """
    # 1. Parse requested fields list
    field_list = [f.strip() for f in fields.split(",") if f.strip()]

    # 2. Convert query date range to UTC timezone (consistent with stored data)
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc)

    # 3. Build MongoDB query criteria
    query = {
        "metadata.code": ticker,
        "date": {
            "$gte": start_dt,
            "$lte": end_dt
        }
    }

    # 4. Build projection to return only requested fields and date field
    projection = {"_id": 0, "date": 1}
    for field in field_list:
        if field not in ("date",):  # date is already included
            projection[field] = 1

    # 5. Execute query
    results = list(coll.find(query, projection))

    if not results:
        raise HTTPException(status_code=404, detail="No data found for the given criteria")

    # 6. Format output, converting date to YYYY-MM-DD string
    output = []
    for r in results:
        item = {"date": r["date"].strftime("%Y-%m-%d")}
        for field in field_list:
            if field in r:
                item[field] = r[field]
        output.append(item)

    return output

# If this file is run directly, start the uvicorn server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)