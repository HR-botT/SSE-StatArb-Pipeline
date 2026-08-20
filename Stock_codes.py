import re
import time
import requests
import csv

def fetch_all_sse_codes_from_stockanalysis(output_file="sse_codes.csv"):
    base_url = "https://stockanalysis.com/list/shanghai-stock-exchange/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    all_codes = set()
    page = 1
    max_pages = 20          # Safety upper limit to prevent infinite loop
    count_per_page = 500    # Fixed number of items per page

    while page <= max_pages:
        # Build current page URL with fixed count=500
        url = f"{base_url}?page={page}&count={count_per_page}" if page > 1 else f"{base_url}?count={count_per_page}"
        print(f"Requesting page {page}: {url}")

        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            print(f"Page {page} request failed, stopping pagination. Error: {e}")
            break

        # Extract all stock codes from the current page (including A-shares and B-shares)
        matches = re.findall(r'sha/(\d{6})', html)
        print(f"Page {page} extracted {len(matches)} codes")

        if not matches:
            print("No codes found; may have reached the end or page structure changed.")
            break

        # Filter: keep only traditional stock codes (A-share main board, STAR market, B-shares)
        # Need to add them manually if there is newly added code heads. 
        # Current heads are enough for quite some future time.
        valid_codes = {c for c in matches if c.startswith(('600', '601', '603', '605', '688', '689', '900'))}
        all_codes.update(valid_codes)

        # If the number of extracted codes is less than 500, we have reached the last page
        if len(matches) < count_per_page:
            print("Reached the last page.")
            break

        page += 1
        time.sleep(1)   # Short delay to avoid making requests too fast

    if not all_codes:
        print("No stock codes were extracted.")
        return

    # Sort and write to CSV (no header, only one column of codes)
    sorted_codes = sorted(all_codes)
    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        for code in sorted_codes:
            writer.writerow([code])

    print(f"Successfully extracted {len(sorted_codes)} stock codes, saved to {output_file}")

if __name__ == "__main__":
    fetch_all_sse_codes_from_stockanalysis()