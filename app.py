from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import numpy as np
from prophet import Prophet
from datetime import datetime, timedelta
import warnings
import traceback

warnings.filterwarnings('ignore')

app = Flask(__name__)
CORS(app)

# Common company name to ticker mapping
COMPANY_TICKER_MAP = {
    "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL", "alphabet": "GOOGL",
    "amazon": "AMZN", "tesla": "TSLA", "meta": "META", "facebook": "META",
    "nvidia": "NVDA", "netflix": "NFLX", "twitter": "TWTR", "x": "X",
    "samsung": "005930.KS", "intel": "INTC", "amd": "AMD",
    "jpmorgan": "JPM", "jp morgan": "JPM", "goldman sachs": "GS",
    "bank of america": "BAC", "disney": "DIS", "walmart": "WMT",
    "coca cola": "KO", "cocacola": "KO", "pepsi": "PEP", "pepsico": "PEP",
    "johnson": "JNJ", "johnson & johnson": "JNJ", "pfizer": "PFE",
    "berkshire": "BRK-B", "visa": "V", "mastercard": "MA",
    "paypal": "PYPL", "salesforce": "CRM", "adobe": "ADBE", "oracle": "ORCL",
    "ibm": "IBM", "qualcomm": "QCOM", "broadcom": "AVGO", "cisco": "CSCO",
    "uber": "UBER", "airbnb": "ABNB", "lyft": "LYFT", "spotify": "SPOT",
    "zoom": "ZM", "shopify": "SHOP", "square": "SQ", "block": "SQ",
    "twitter x": "X", "tata": "TCS.NS", "infosys": "INFY", "wipro": "WIPRO.NS",
    "reliance": "RELIANCE.NS", "hdfc": "HDFCBANK.NS", "sbi": "SBIN.NS",
    "bajaj": "BAJAJFINSV.NS", "itc": "ITC.NS", "maruti": "MARUTI.NS",
    "tcs": "TCS.NS", "hcl": "HCLTECH.NS", "axis bank": "AXISBANK.NS",
    "kotak": "KOTAKBANK.NS", "bajaj finance": "BAJFINANCE.NS",
    "asian paints": "ASIANPAINT.NS", "titan": "TITAN.NS", "nestle": "NESTLEIND.NS",
    "adani": "ADANIENT.NS", "zomato": "ZOMATO.NS", "paytm": "PAYTM.NS",
    "nifty": "^NSEI", "sensex": "^BSESN", "sp500": "^GSPC", "s&p 500": "^GSPC",
    "dow jones": "^DJI", "nasdaq": "^IXIC",
}


def resolve_ticker(company_input: str) -> tuple[str, str]:
    """Resolve company name or ticker to a valid ticker symbol."""
    cleaned = company_input.strip().lower()

    # Check direct map
    if cleaned in COMPANY_TICKER_MAP:
        ticker = COMPANY_TICKER_MAP[cleaned]
        return ticker, company_input.strip()

    # Try upper-case as ticker directly
    upper = company_input.strip().upper()
    test = yf.Ticker(upper)
    info = test.info
    if info and info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose"):
        name = info.get("longName", upper)
        return upper, name

    # Try search via yfinance
    try:
        results = yf.Search(company_input, max_results=5)
        quotes = results.quotes
        if quotes:
            ticker = quotes[0].get("symbol", upper)
            name = quotes[0].get("longname") or quotes[0].get("shortname") or ticker
            return ticker, name
    except Exception:
        pass

    return upper, company_input.strip()


def fetch_stock_data(ticker: str) -> pd.DataFrame:
    """Fetch 2 years of historical stock data."""
    end = datetime.now()
    start = end - timedelta(days=730)  # 2 years
    stock = yf.Ticker(ticker)
    df = stock.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
    if df.empty:
        raise ValueError(f"No data found for ticker: {ticker}")
    df = df.reset_index()
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
    return df


def predict_prices(df: pd.DataFrame, days: int = 14) -> dict:
    """Use Prophet to predict stock prices for next N days."""
    # Prepare data for Prophet
    prophet_df = df[["Date", "Close"]].rename(columns={"Date": "ds", "Close": "y"})
    prophet_df = prophet_df.dropna()

    model = Prophet(
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=True,
        changepoint_prior_scale=0.05,
        seasonality_prior_scale=10,
        interval_width=0.8,
    )
    model.fit(prophet_df)

    # Create future dataframe (only business days)
    future = model.make_future_dataframe(periods=days, freq="B")
    forecast = model.predict(future)

    # Split historical vs prediction
    last_hist_date = prophet_df["ds"].max()
    hist_forecast = forecast[forecast["ds"] <= last_hist_date]
    pred_forecast = forecast[forecast["ds"] > last_hist_date].head(days)

    return {
        "historical": prophet_df.tail(90).to_dict(orient="records"),  # Last 90 days
        "trend_historical": hist_forecast.tail(90)[["ds", "yhat", "yhat_lower", "yhat_upper"]].to_dict(orient="records"),
        "prediction": pred_forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].to_dict(orient="records"),
    }


def get_company_info(ticker: str) -> dict:
    """Get company metadata."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            "name": info.get("longName", ticker),
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "country": info.get("country", "N/A"),
            "currency": info.get("currency", "USD"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "volume": info.get("volume"),
            "avg_volume": info.get("averageVolume"),
            "website": info.get("website", ""),
            "description": info.get("longBusinessSummary", "")[:300] + "..." if info.get("longBusinessSummary") else "",
        }
    except Exception:
        return {"name": ticker, "currency": "USD"}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/predict", methods=["POST"])
def predict():
    try:
        data = request.get_json()
        company_input = data.get("company", "").strip()

        if not company_input:
            return jsonify({"error": "Please enter a company name or ticker symbol."}), 400

        # Resolve ticker
        ticker, company_name = resolve_ticker(company_input)

        # Fetch stock data
        df = fetch_stock_data(ticker)

        # Get predictions
        result = predict_prices(df)

        # Get company info
        info = get_company_info(ticker)

        # Current price info
        current_price = float(df["Close"].iloc[-1])
        prev_price = float(df["Close"].iloc[-2]) if len(df) > 1 else current_price
        price_change = current_price - prev_price
        price_change_pct = (price_change / prev_price) * 100

        # Predicted stats
        pred_df = result["prediction"]
        pred_high = max(p["yhat_upper"] for p in pred_df) if pred_df else current_price
        pred_low = min(p["yhat_lower"] for p in pred_df) if pred_df else current_price
        pred_end = pred_df[-1]["yhat"] if pred_df else current_price
        pred_change_pct = ((pred_end - current_price) / current_price) * 100

        def serialize_records(records):
            out = []
            for r in records:
                row = {}
                for k, v in r.items():
                    if hasattr(v, "isoformat"):
                        row[k] = v.isoformat()
                    elif isinstance(v, (np.integer, np.floating)):
                        row[k] = float(v)
                    else:
                        row[k] = v
                out.append(row)
            return out

        return jsonify({
            "ticker": ticker,
            "company_name": info.get("name", company_name),
            "currency": info.get("currency", "USD"),
            "current_price": round(current_price, 2),
            "price_change": round(price_change, 2),
            "price_change_pct": round(price_change_pct, 2),
            "pred_high": round(pred_high, 2),
            "pred_low": round(pred_low, 2),
            "pred_end": round(pred_end, 2),
            "pred_change_pct": round(pred_change_pct, 2),
            "info": info,
            "historical": serialize_records(result["historical"]),
            "trend_historical": serialize_records(result["trend_historical"]),
            "prediction": serialize_records(result["prediction"]),
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Prediction failed: {str(e)}"}), 500


@app.route("/api/search", methods=["GET"])
def search():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify([])
    try:
        results = yf.Search(query, max_results=8)
        quotes = results.quotes or []
        suggestions = []
        for q in quotes:
            suggestions.append({
                "symbol": q.get("symbol", ""),
                "name": q.get("longname") or q.get("shortname") or q.get("symbol", ""),
                "type": q.get("quoteType", ""),
                "exchange": q.get("exchange", ""),
            })
        return jsonify(suggestions)
    except Exception:
        return jsonify([])


if __name__ == "__main__":
    app.run(debug=True, port=5000)
