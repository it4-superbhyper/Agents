# app.py
from flask import Flask, render_template
import requests
from dotenv import load_dotenv
import os
import json
import time
from datetime import datetime

load_dotenv()

app = Flask(__name__)

USERNAME = os.getenv("AUTOTRADER_USERNAME")
PASSWORD = os.getenv("AUTOTRADER_PASSWORD")
API_URL = os.getenv("API_URL")

# Cache settings
CACHE_FILE = "cache_listings.json"
CACHE_TIMEOUT = 1800  # 30 minutes (in seconds)


def get_listings_from_cache():
    """Read cached data if it exists and is still fresh"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if time.time() - cache["timestamp"] < CACHE_TIMEOUT:
                print("✅ Using cached API data")
                return cache["data"]
            else:
                print("⏳ Cache expired, will fetch fresh data")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"⚠️ Cache file corrupted or invalid: {e}")
    return None


def save_listings_to_cache(data):
    """Save API response to cache with timestamp"""
    try:
        cache = {
            "timestamp": time.time(),
            "data": data
        }
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
        print("💾 Fresh data saved to cache")
    except Exception as e:
        print(f"❌ Failed to save cache: {e}")


def parse_iso_datetime(dt_str):
    """
    Safely parse ISO 8601 datetime string (handles fractional seconds and timezone).
    Returns Unix timestamp for sorting.
    """
    try:
        # Remove timezone part if present and use fromisoformat
        if dt_str.endswith('Z'):
            dt_str = dt_str[:-1] + '+00:00'
        if '+' in dt_str and ':' == dt_str.rsplit('+', 1)[-1][2:3]:
            pass  # Correct format like +02:00
        elif '+' in dt_str:
            # Fix missing colon in offset like +0200 → +02:00
            parts = dt_str.split('+')
            dt_str = parts[0] + '+' + parts[1][:2] + ':' + parts[1][2:]
        dt = datetime.fromisoformat(dt_str)
        return dt.timestamp()
    except Exception as e:
        print(f"⚠️ Failed to parse datetime: {dt_str} | Error: {e}")
        return 0  # Default to oldest if invalid


def fetch_listings():
    """Fetch vehicle listings from API or cache, then sort by 'created' (newest first)"""
    listings = []

    # Try to get from cache first
    cached_data = get_listings_from_cache()
    if cached_data is not None:
        raw_listings = cached_data
    else:
        # Cache miss — fetch from API
        print("📡 Fetching fresh data from API...")
        try:
            response = requests.get(
                API_URL,
                auth=(USERNAME, PASSWORD),
                timeout=10,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "AutoTrader-Client-App/1.0"
                }
            )

            if response.status_code == 200:
                raw_data = response.json()

                # Normalize response structure
                if isinstance(raw_data, list):
                    raw_listings = raw_data
                elif isinstance(raw_data, dict):
                    raw_listings = raw_data.get("listings", []) or raw_data.get("vehicles", []) or []
                else:
                    raw_listings = []

                # Save to cache
                save_listings_to_cache(raw_listings)

            else:
                print(f"❌ API Error {response.status_code}: {response.text}")
                # Fallback: use stale cache if available
                if cached_data is not None:
                    print("⚠️ Using stale cache due to API failure")
                    raw_listings = cached_data
                else:
                    print("❌ No cache available. Showing empty list.")
                    raw_listings = []

        except Exception as e:
            print(f"🚨 Request failed: {e}")
            # Fallback to cache
            if cached_data is not None:
                print("⚠️ Using cached data after connection error")
                raw_listings = cached_data
            else:
                raw_listings = []

    # Process each listing
    for item in raw_listings:
        make = item.get("make", "Unknown").title()
        model = item.get("model", "Model").title()
        year = item.get("year", "N/A")
        location = item.get("location", "South Africa")
        colour = item.get("colour", "Unknown")
        description = item.get("description", "No description available.").replace('\r', '') # Clean description
        variant = item.get("variant", "")
        body_type = item.get("bodyType", "")

        # --- START OF PRICE HANDLING FIX ---
        price_value_for_sorting = 0
        price_display = "POA"
        raw_price_str = item.get("price", "")

        if isinstance(raw_price_str, str):
             raw_price_str = raw_price_str.strip()

        # Check for POA conditions
        if not raw_price_str or (isinstance(raw_price_str, str) and raw_price_str.upper() in ["POA", "ON REQUEST", "PRICE ON APPLICATION", ""]):
            price_display = "POA"
            price_value_for_sorting = 0
        else:
            # Assume format is "1234567,0000" where comma is decimal separator
            try:
                if isinstance(raw_price_str, str):
                    parts = raw_price_str.split(',')
                    if len(parts) == 2:
                        major_part_str = parts[0]
                        minor_part_str = parts[1][:2] # Take only first 2 digits after comma for cents/display

                        # Remove any non-digit characters from major part (e.g., spaces, 'R')
                        major_digits_only = ''.join(filter(str.isdigit, major_part_str))
                        if not major_digits_only:
                             major_digits_only = "0"

                        # Combine parts to form a string suitable for float conversion
                        # e.g., "18499000" and "00" -> "18499000.00"
                        price_float_str = f"{major_digits_only}.{minor_part_str}"

                        # Convert to float for sorting
                        price_value_for_sorting = float(price_float_str)

                        # Format for display: R + space thousands separator + no decimal
                        # Use Python's built-in formatting for thousands separator
                        # Then replace commas with spaces
                        major_int = int(major_digits_only)
                        # Correctly format with spaces as thousand separators and no decimals
                        formatted_major = f"{major_int:,}".replace(',', ' ')
                        price_display = f"R{formatted_major}"

                    else:
                        # If split doesn't produce two parts, assume it's an integer or invalid
                        # Try direct conversion after cleaning
                        clean_str = ''.join(filter(str.isdigit, raw_price_str))
                        if clean_str:
                            price_value_for_sorting = float(clean_str)
                            # Format display with spaces and no decimals
                            price_display = f"R{price_value_for_sorting:,.0f}".replace(',', ' ')
                        else:
                             price_display = "POA"
                             price_value_for_sorting = 0
                elif isinstance(raw_price_str, (int, float)):
                    price_value_for_sorting = float(raw_price_str)
                    # Format display with spaces and no decimals
                    price_display = f"R{price_value_for_sorting:,.0f}".replace(',', ' ')
                else:
                     price_display = "POA"
                     price_value_for_sorting = 0

            except (ValueError, IndexError, TypeError) as e:
                print(f"⚠️ Error parsing price '{raw_price_str}': {e}")
                price_display = "POA"
                price_value_for_sorting = 0
        # --- END OF PRICE HANDLING FIX ---

        # --- START OF MILEAGE HANDLING ---
        mileage = item.get("mileageInKm", 0)
        # Format mileage with spaces as thousand separators
        formatted_mileage = f"{mileage:,}".replace(',', ' ')
        # --- END OF MILEAGE HANDLING ---

        # Images
        image_urls = item.get("imageUrls", [])
        if not image_urls:
            image_urls = [f"https://source.unsplash.com/random/800x600/?car,{make.lower()}+{model.lower()}"]

        # Use actual 'created' field for sorting
        created = item.get("created", "")
        created_timestamp = parse_iso_datetime(created) if created else time.time()

        listings.append({
            "id": item.get("id"), # Include ID for modal fix
            "make": make,
            "model": model,
            "year": year,
            "price_display": price_display, # Correctly formatted string
            "price": price_value_for_sorting, # Numerical value for sorting
            "image_urls": image_urls,
            "variant": variant,
            "body_type": body_type,
            "colour": colour,
            "location": location,  # Keep original location for debugging
            "mileage": formatted_mileage, # New field for mileage
            "description": description,
            "created": created,  # Keep original ISO string for debugging/display
            "created_timestamp": created_timestamp  # For sorting
        })

    # 🔥 Sort by 'created_timestamp' — newest first
    listings.sort(key=lambda x: x["created_timestamp"], reverse=True)

    print(f"📦 Total processed & sorted listings: {len(listings)}")
    return listings


@app.route("/")
def index():
    listings = fetch_listings()
    return render_template("index.html", listings=listings)


if __name__ == "__main__":
    # Use the PORT environment variable from Render, or default to 5000
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
