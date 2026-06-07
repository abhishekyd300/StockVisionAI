from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
import traceback

# Lightweight forecasting (Vercel-compatible — no Prophet/Stan)
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings('ignore')

app = Flask(__name__)
CORS(app)

# ── Company name → ticker lookup table ──────────────────────────────────────
COMPANY_TICKER_MAP = {
    "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL", "alphabet": "GOOGL",
    "amazon": "AMZN", "tesla": "TSLA", "meta": "META", "facebook": "META",
    "nvidia": "NVDA", "netflix": "NFLX", "intel": "INTC", "amd": "AMD",
    "jpmorgan": "JPM", "jp morgan": "JPM", "goldman sachs": "GS",
    "bank of america": "BAC", "disney": "DIS", "walmart": "WMT",
    "coca cola": "KO", "cocacola": "KO", "pepsi": "PEP", "pepsico": "PEP",
    "johnson & johnson": "JNJ", "pfizer": "PFE",
    "berkshire": "BRK-B", "visa": "V", "mastercard": "MA",
    "paypal": "PYPL", "salesforce": "CRM", "adobe": "ADBE", "oracle": "ORCL",
    "ibm": "IBM", "qualcomm": "QCOM", "broadcom": "AVGO", "cisco": "CSCO",
    "uber": "UBER", "airbnb": "ABNB", "lyft": "LYFT", "spotify": "SPOT",
    "zoom": "ZM", "shopify": "SHOP", "block": "SQ",
    "tata": "TCS.NS", "infosys": "INFY", "wipro": "WIPRO.NS",
    "reliance": "RELIANCE.NS", "hdfc": "HDFCBANK.NS", "sbi": "SBIN.NS",
    "bajaj": "BAJAJFINSV.NS", "itc": "ITC.NS", "maruti": "MARUTI.NS",
    "tcs": "TCS.NS", "hcl": "HCLTECH.NS", "axis bank": "AXISBANK.NS",
    "kotak": "KOTAKBANK.NS", "bajaj finance": "BAJFINANCE.NS",
    "asian paints": "ASIANPAINT.NS", "titan": "TITAN.NS",
    "adani": "ADANIENT.NS", "zomato": "ZOMATO.NS", "paytm": "PAYTM.NS",
    "nifty": "^NSEI", "sensex": "^BSESN", "sp500": "^GSPC",
    "s&p 500": "^GSPC", "dow jones": "^DJI", "nasdaq": "^IXIC",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def resolve_ticker(company_input: str) -> tuple[str, str]:
    """Resolve a company name or ticker string to a valid Yahoo Finance ticker."""
    cleaned = company_input.strip().lower()

    if cleaned in COMPANY_TICKER_MAP:
        return COMPANY_TICKER_MAP[cleaned], company_input.strip()

    # Try the raw input as a ticker (uppercase)
    upper = company_input.strip().upper()
    test  = yf.Ticker(upper)
    info  = test.info
    if info and (info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")):
        return upper, info.get("longName", upper)

    # Fall back to yfinance search
    try:
        results = yf.Search(company_input, max_results=5)
        quotes  = results.quotes
        if quotes:
            ticker = quotes[0].get("symbol", upper)
            name   = quotes[0].get("longname") or quotes[0].get("shortname") or ticker
            return ticker, name
    except Exception:
        pass

    return upper, company_input.strip()


def fetch_stock_data(ticker: str) -> pd.DataFrame:
    """Fetch up to 2 years of daily historical close prices."""
    end   = datetime.now()
    start = end - timedelta(days=730)
    stock = yf.Ticker(ticker)
    df    = stock.history(
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d")
    )
    if df.empty:
        raise ValueError(f"No data found for ticker: {ticker}")
    df = df.reset_index()
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
    return df


def predict_prices(df: pd.DataFrame, days: int = 14) -> dict:
    """
    Forecast the next `days` closing prices using Holt-Winters
    Exponential Smoothing (additive trend + seasonality).

    Returns a dict compatible with the original Prophet-based API shape.
    """
    close = df["Close"].values.astype(float)

    # Fit Holt-Winters with additive trend and weekly seasonality (period=5 trading days)
    seasonal_periods = 5
    model = ExponentialSmoothing(
        close,
        trend="add",
        seasonal="add",
        seasonal_periods=seasonal_periods,
        damped_trend=True,
        initialization_method="estimated",
    )
    fit = model.fit(optimized=True)

    # In-sample fitted values (last 90 obs)
    fitted = fit.fittedvalues

    # Forecast next `days` steps
    forecast_mean = fit.forecast(days)

    # Approximate 80% confidence interval using residual std
    residuals = close - fitted
    resid_std = float(np.std(residuals))
    z80 = 1.2816  # 80% CI z-score
    lower = forecast_mean - z80 * resid_std * np.sqrt(np.arange(1, days + 1))
    upper = forecast_mean + z80 * resid_std * np.sqrt(np.arange(1, days + 1))

    # Build future business-day dates
    last_date  = df["Date"].iloc[-1]
    pred_dates = pd.bdate_range(start=last_date + timedelta(days=1), periods=days)

    # Historical slice (last 90 trading days)
    hist_slice = df.tail(90)[["Date", "Close"]].copy()
    historical = [
        {"ds": row["Date"].isoformat(), "y": float(row["Close"])}
        for _, row in hist_slice.iterrows()
    ]

    # Trend-historical (fitted values for last 90 obs)
    fitted_slice = fitted[-90:]
    trend_hist   = [
        {
            "ds":          hist_slice.iloc[i]["Date"].isoformat(),
            "yhat":        float(fitted_slice[i]),
            "yhat_lower":  float(fitted_slice[i]) - z80 * resid_std,
            "yhat_upper":  float(fitted_slice[i]) + z80 * resid_std,
        }
        for i in range(len(fitted_slice))
    ]

    # Prediction records
    prediction = [
        {
            "ds":         str(pred_dates[i].date()),
            "yhat":       float(forecast_mean[i]),
            "yhat_lower": float(lower[i]),
            "yhat_upper": float(upper[i]),
        }
        for i in range(days)
    ]

    return {
        "historical":      historical,
        "trend_historical": trend_hist,
        "prediction":      prediction,
    }


def get_company_info(ticker: str) -> dict:
    """Fetch company metadata from Yahoo Finance."""
    try:
        info = yf.Ticker(ticker).info
        return {
            "name":        info.get("longName", ticker),
            "sector":      info.get("sector", "N/A"),
            "industry":    info.get("industry", "N/A"),
            "country":     info.get("country", "N/A"),
            "currency":    info.get("currency", "USD"),
            "market_cap":  info.get("marketCap"),
            "pe_ratio":    info.get("trailingPE"),
            "52w_high":    info.get("fiftyTwoWeekHigh"),
            "52w_low":     info.get("fiftyTwoWeekLow"),
            "volume":      info.get("volume"),
            "avg_volume":  info.get("averageVolume"),
            "website":     info.get("website", ""),
            "description": (info.get("longBusinessSummary", "")[:300] + "…")
                           if info.get("longBusinessSummary") else "",
        }
    except Exception:
        return {"name": ticker, "currency": "USD"}


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/predict", methods=["POST"])
def predict():
    try:
        data           = request.get_json()
        company_input  = data.get("company", "").strip()

        if not company_input:
            return jsonify({"error": "Please enter a company name or ticker symbol."}), 400

        ticker, company_name = resolve_ticker(company_input)
        df                   = fetch_stock_data(ticker)
        result               = predict_prices(df)
        info                 = get_company_info(ticker)

        current_price    = float(df["Close"].iloc[-1])
        prev_price       = float(df["Close"].iloc[-2]) if len(df) > 1 else current_price
        price_change     = current_price - prev_price
        price_change_pct = (price_change / prev_price) * 100

        pred_df          = result["prediction"]
        pred_high        = max(p["yhat_upper"] for p in pred_df) if pred_df else current_price
        pred_low         = min(p["yhat_lower"] for p in pred_df) if pred_df else current_price
        pred_end         = pred_df[-1]["yhat"] if pred_df else current_price
        pred_change_pct  = ((pred_end - current_price) / current_price) * 100

        return jsonify({
            "ticker":           ticker,
            "company_name":     info.get("name", company_name),
            "currency":         info.get("currency", "USD"),
            "current_price":    round(current_price, 2),
            "price_change":     round(price_change, 2),
            "price_change_pct": round(price_change_pct, 2),
            "pred_high":        round(pred_high, 2),
            "pred_low":         round(pred_low, 2),
            "pred_end":         round(pred_end, 2),
            "pred_change_pct":  round(pred_change_pct, 2),
            "info":             info,
            "historical":       result["historical"],
            "trend_historical": result["trend_historical"],
            "prediction":       result["prediction"],
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
        results     = yf.Search(query, max_results=8)
        quotes      = results.quotes or []
        suggestions = [
            {
                "symbol":   q.get("symbol", ""),
                "name":     q.get("longname") or q.get("shortname") or q.get("symbol", ""),
                "type":     q.get("quoteType", ""),
                "exchange": q.get("exchange", ""),
            }
            for q in quotes
        ]
        return jsonify(suggestions)
    except Exception:
        return jsonify([])


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)
