from flask import Flask, render_template, request, redirect, session, jsonify
import requests as http_requests
from werkzeug.security import generate_password_hash, check_password_hash
import os
from flask_sqlalchemy import SQLAlchemy
import yfinance as yf

import pandas as pd

url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

df = pd.read_csv(url)

NSE_STOCKS = []

for i,row in df.iterrows():

    NSE_STOCKS.append({
        "name": row["NAME OF COMPANY"],
        "symbol": row["SYMBOL"] + ".NS"
    })
FOREIGN_STOCKS = [

{"name":"Apple","symbol":"AAPL"},
{"name":"Microsoft","symbol":"MSFT"},
{"name":"Amazon","symbol":"AMZN"},
{"name":"Tesla","symbol":"TSLA"},
{"name":"Nvidia","symbol":"NVDA"}

]

ALL_STOCKS = NSE_STOCKS + FOREIGN_STOCKS

# HELPER FUNCTION TO GET CURRENT PRICE
def get_price(symbol):

    ticker = yf.Ticker(symbol)

    price = ticker.info.get("currentPrice")

    if price is None:
        return None

    if symbol.endswith(".NS"):
        return round(price,2)

    else:
        return round(price * 83,2)
    
# Use absolute path so Flask always finds templates no matter where you run from
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'), static_folder=os.path.join(BASE_DIR, 'static'))
app.secret_key = "secret123"
app.config["ANTHROPIC_API_KEY"] = "YOUR_ANTHROPIC_API_KEY_HERE"
app.config["GROQ_API_KEY"] = "YOUR_GROQ_API_KEY_HERE"

# DATABASE CONFIG
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stocks.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# ---------------------------
# DATABASE MODELS
# ---------------------------

class User(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(100), unique=True, nullable=False)

    password = db.Column(db.String(200), nullable=False)

    balance = db.Column(db.Float, default=1000000)

from datetime import datetime
import pytz
class Transaction(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer)

    symbol = db.Column(db.String(20))

    quantity = db.Column(db.Integer)

    price = db.Column(db.Float)

    time = db.Column(
        db.DateTime,
        default=lambda: datetime.now(pytz.timezone("Asia/Kolkata"))
    )

    


# ---------------------------
# ADDITIONAL MODELS
# ---------------------------

class ChatHistory(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, nullable=False)
    role       = db.Column(db.String(10))   # 'user' or 'assistant'
    message    = db.Column(db.Text)
    timestamp  = db.Column(db.DateTime, default=lambda: datetime.now(pytz.timezone("Asia/Kolkata")))


class UserSession(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, nullable=False)
    last_seen   = db.Column(db.DateTime, default=lambda: datetime.now(pytz.timezone("Asia/Kolkata")))
    is_online   = db.Column(db.Boolean, default=True)


# ---------------------------
# ROUTES
# ---------------------------

@app.route("/")
def index():
    return render_template("index.html")


# REGISTER
@app.route("/register", methods=["GET","POST"])
def register():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        user_exists = User.query.filter_by(username=username).first()

        if user_exists:
            return "User already exists"

        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password=hashed_password)

        db.session.add(new_user)
        db.session.commit()

        return redirect("/login")

    return render_template("register.html")



# LOGIN
@app.route("/login", methods=["GET","POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()
        if user and not check_password_hash(user.password, password):
            user = None

        if user:
            session["user_id"] = user.id

            # Track user session
            from datetime import datetime
            now = datetime.now(pytz.timezone("Asia/Kolkata"))
            existing = UserSession.query.filter_by(user_id=user.id).first()
            if existing:
                existing.last_seen = now
                existing.is_online = True
            else:
                db.session.add(UserSession(user_id=user.id, last_seen=now, is_online=True))
            db.session.commit()

            return redirect("/dashboard")

        else:
            return "Invalid login"

    return render_template("login.html")



# LOGOUT
@app.route("/logout")
def logout():
    if "user_id" in session:
        us = UserSession.query.filter_by(user_id=session["user_id"]).first()
        if us:
            us.is_online = False
            db.session.commit()
    session.clear()
    return redirect("/")



# DASHBOARD
@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect("/login")

    user = User.query.get(session["user_id"])

    transactions = Transaction.query.filter_by(user_id=user.id).all()

    holdings = {}
    portfolio_value = 0

    # Calculate shares owned
    for t in transactions:
        if t.symbol not in holdings:
            holdings[t.symbol] = 0
        holdings[t.symbol] += t.quantity

    # Calculate live value
    import yfinance as yf

    for symbol, qty in holdings.items():

        try:
            data = yf.Ticker(symbol)
            price = data.info.get("currentPrice")

            if symbol.endswith(".NS"):
                final_price = price
            else:
                final_price = price * 83

            portfolio_value += final_price * qty

        except:
            pass

    total_wealth = user.balance + portfolio_value

    is_admin = (user.username == ADMIN_USERNAME)
    return render_template(
        "dashboard.html",
        user=user,
        value=round(portfolio_value,2),
        total_wealth=round(total_wealth,2),
        holdings=holdings,
        is_admin=is_admin
    )



# MARKET PAGE
@app.route("/market", methods=["GET","POST"])
def market():
    if "user_id" not in session:
        return redirect("/login")

    stock=None
    error=None

    if request.method=="POST":

        symbol=request.form["symbol"].upper()

        try:

            price=get_price(symbol)

            if price is None:
                raise Exception()

            stock={
            "symbol":symbol,
            "price":price
            }

        except:

            error="Stock not found"

    # Build TradingView symbol in Python
    tv_symbol = "NIFTY"
    if stock:
        s = stock["symbol"]
        if s.endswith(".NS") or s.endswith(".BO"):
            tv_symbol = "BSE:" + s.replace(".NS","").replace(".BO","")
        else:
            tv_symbol = s
    print("DEBUG tv_symbol =", tv_symbol)

    u2 = User.query.get(session["user_id"]) if "user_id" in session else None
    is_admin = (u2.username == ADMIN_USERNAME) if u2 else False
    return render_template(
        "market.html",
        stock=stock,
        error=error,
        stocks=ALL_STOCKS,
        tv_symbol=tv_symbol,
        is_admin=is_admin
    )

# BUY STOCK
@app.route("/buy", methods=["POST"])
def buy():

    if "user_id" not in session:
        return redirect("/login")

    symbol = request.form["symbol"]
    qty = int(request.form["qty"])

    # GET CURRENT PRICE
    price = get_price(symbol)

    user = User.query.get(session["user_id"])

    total_cost = price * qty

    if user.balance < total_cost:
        return "Not enough balance"

    user.balance -= total_cost

    transaction = Transaction(
        user_id=user.id,
        symbol=symbol,
        quantity=qty,
        price=price
    )

    db.session.add(transaction)
    db.session.commit()

    return redirect("/dashboard")

# SELL STOCK
@app.route("/sell", methods=["POST"])
def sell():

    if "user_id" not in session:
        return redirect("/login")

    symbol = request.form["symbol"]
    qty = int(request.form["qty"])

    user_id = session["user_id"]

    # get all transactions for this stock
    transactions = Transaction.query.filter_by(
        user_id=user_id,
        symbol=symbol
    ).all()

    owned_qty = sum(t.quantity for t in transactions)

    # prevent selling more than owned
    if qty > owned_qty:
        return "You don't own that many shares"

    ticker = yf.Ticker(symbol)
    price = ticker.info.get("currentPrice")

    if symbol.endswith(".NS"):
        final_price = price
    else:
        final_price = price * 83

    final_price = round(final_price,2)

    user = User.query.get(user_id)

    total_value = final_price * qty

    user.balance += total_value

    transaction = Transaction(
        user_id=user.id,
        symbol=symbol,
        quantity=-qty,
        price=final_price
    )

    db.session.add(transaction)
    db.session.commit()

    return redirect("/portfolio")

# PORTFOLIO 
@app.route("/portfolio")
def portfolio():

    if "user_id" not in session:
        return redirect("/login")

    transactions = Transaction.query.filter_by(user_id=session["user_id"]).all()

    portfolio = {}

    for t in transactions:

        if t.symbol not in portfolio:
            portfolio[t.symbol] = {"qty":0,"total":0}

        portfolio[t.symbol]["qty"] += t.quantity
        portfolio[t.symbol]["total"] += t.price * t.quantity


    result=[]

    for symbol,data in portfolio.items():

        qty=data["qty"]
        avg_price=data["total"]/qty

        current_price=get_price(symbol)

        profit=(current_price-avg_price)*qty

        result.append({
            "symbol":symbol,
            "qty":qty,
            "buy_price":round(avg_price,2),
            "current_price":current_price,
            "profit":round(profit,2)
        })

    u = User.query.get(session["user_id"])
    is_admin = (u.username == ADMIN_USERNAME)
    return render_template("portfolio.html", stocks=result, is_admin=is_admin)


# TRANSACTION HISTORY
@app.route("/history")
def history():

    if "user_id" not in session:
        return redirect("/login")

    transactions = Transaction.query.filter_by(
        user_id=session["user_id"]
    ).all()

    u = User.query.get(session["user_id"])
    is_admin = (u.username == ADMIN_USERNAME)
    return render_template(
        "history.html",
        transactions=transactions,
        is_admin=is_admin
    )

# ---------------------------
# CREATE DATABASE
# ---------------------------

with app.app_context():
    db.create_all()


# ---------------------------
# RUN APP
# ---------------------------

# AI STOCK ADVISOR
@app.route("/advisor")
def advisor():
    if "user_id" not in session:
        return redirect("/login")

    user = User.query.get(session["user_id"])
    transactions = Transaction.query.filter_by(user_id=user.id).all()

    portfolio = {}
    for t in transactions:
        if t.symbol not in portfolio:
            portfolio[t.symbol] = {"qty": 0, "total": 0}
        portfolio[t.symbol]["qty"] += t.quantity
        portfolio[t.symbol]["total"] += t.price * t.quantity

    holdings_data = []
    for symbol, data in portfolio.items():
        qty = data["qty"]
        if qty <= 0:
            continue
        avg_price = data["total"] / qty
        current_price = get_price(symbol)
        if current_price:
            profit = round((current_price - avg_price) * qty, 2)
            profit_pct = round(((current_price - avg_price) / avg_price) * 100, 2)
            holdings_data.append({
                "symbol": symbol,
                "qty": qty,
                "avg_price": round(avg_price, 2),
                "current_price": current_price,
                "profit": profit,
                "profit_pct": profit_pct
            })

    is_admin = (user.username == ADMIN_USERNAME)
    return render_template(
        "advisor.html",
        user=user,
        holdings=holdings_data,
        balance=round(user.balance, 2),
        is_admin=is_admin
    )


# ─────────────────────────────────────────
# BUILT-IN AI ADVISOR ENGINE (no API needed)
# ─────────────────────────────────────────

def analyze_any_stock(symbol):
    """Fetch real data from yfinance and return analysis dict"""
    try:
        ticker = yf.Ticker(symbol)
        info   = ticker.info
        hist   = ticker.history(period="1y")   # 1 year for proper analysis

        if hist.empty or len(hist) < 10:
            return None

        closes = hist["Close"].dropna()
        if len(closes) < 10:
            return None

        current         = round(float(closes.iloc[-1]), 2)
        high_52w        = round(float(closes.max()), 2)
        low_52w         = round(float(closes.min()), 2)
        week_ago        = round(float(closes.iloc[-5]),  2) if len(closes) >= 5  else current
        month_ago       = round(float(closes.iloc[-22]), 2) if len(closes) >= 22 else current
        three_month_ago = round(float(closes.iloc[-66]), 2) if len(closes) >= 66 else round(float(closes.iloc[0]), 2)

        change_1w  = round((current - week_ago)        / week_ago        * 100, 2)
        change_1m  = round((current - month_ago)       / month_ago       * 100, 2)
        change_3m  = round((current - three_month_ago) / three_month_ago * 100, 2)

        # Moving averages
        sma20 = round(float(closes.tail(20).mean()), 2) if len(closes) >= 20 else current
        sma50 = round(float(closes.tail(50).mean()), 2) if len(closes) >= 50 else current

        # RSI (14-period)
        delta = closes.diff().dropna()
        gain  = delta.clip(lower=0).tail(14).mean()
        loss  = (-delta.clip(upper=0)).tail(14).mean()
        if loss and loss != 0 and str(loss) != "nan":
            rsi = round(100 - (100 / (1 + float(gain) / float(loss))), 1)
        else:
            rsi = 50

        # Volume
        vols      = hist["Volume"].dropna()
        avg_vol   = float(vols.tail(20).mean()) if len(vols) >= 20 else 1
        today_vol = float(vols.iloc[-1])
        vol_ratio = round(today_vol / avg_vol, 2) if avg_vol > 0 else 1.0

        # Linear regression on last 60 days for prediction
        price_series = closes.tail(60).values.tolist()
        n      = len(price_series)
        x_vals = list(range(n))
        sum_x  = sum(x_vals)
        sum_y  = sum(price_series)
        sum_xy = sum(x_vals[i] * price_series[i] for i in range(n))
        sum_x2 = sum(xi**2 for xi in x_vals)
        denom  = n * sum_x2 - sum_x**2
        slope  = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0

        pred_7d  = round(current + slope * 7,  2)
        pred_30d = round(current + slope * 30, 2)
        pred_90d = round(current + slope * 90, 2)

        # % from 52w high/low
        from_high = round((current - high_52w) / high_52w * 100, 1)
        from_low  = round((current - low_52w)  / low_52w  * 100, 1)

        # Trend
        if current > sma20 > sma50:   trend = "STRONG UPTREND 📈"
        elif current > sma20:          trend = "MILD UPTREND 📈"
        elif current < sma20 < sma50:  trend = "STRONG DOWNTREND 📉"
        elif current < sma20:          trend = "MILD DOWNTREND 📉"
        else:                          trend = "SIDEWAYS ➡️"

        # RSI signal
        if rsi >= 70:    rsi_signal = "OVERBOUGHT ⚠️ (may correct)"
        elif rsi <= 30:  rsi_signal = "OVERSOLD ✅ (may bounce)"
        else:            rsi_signal = "NEUTRAL ✅"

        # Score-based recommendation
        score = 0
        if current > sma20:   score += 1
        if current > sma50:   score += 1
        if 30 < rsi < 65:     score += 1
        if change_1m > 0:     score += 1
        if slope > 0:         score += 1
        if change_3m > 0:     score += 1

        if score >= 5:    rec = "✅ STRONG BUY"
        elif score == 4:  rec = "✅ BUY"
        elif score == 3:  rec = "⏸️ HOLD / NEUTRAL"
        elif score == 2:  rec = "⚠️ WEAK — Proceed with caution"
        else:             rec = "❌ AVOID / SELL"

        name = info.get("longName", symbol)

        return {
            "symbol": symbol, "name": name,
            "current": current,
            "high_52w": high_52w, "low_52w": low_52w,
            "from_high": from_high, "from_low": from_low,
            "change_1w": change_1w, "change_1m": change_1m, "change_3m": change_3m,
            "sma20": sma20, "sma50": sma50,
            "rsi": rsi, "rsi_signal": rsi_signal,
            "vol_ratio": vol_ratio,
            "trend": trend,
            "pred_7d": pred_7d, "pred_30d": pred_30d, "pred_90d": pred_90d,
            "slope": slope, "rec": rec, "score": score
        }
    except Exception as e:
        return None


def format_stock_analysis(d, is_inr=True):
    """Format stock analysis dict into readable AI response"""
    lines = []
    lines.append(f"📊 {d['name']} ({d['symbol']})\n" + "─"*35)
    lines.append(f"💵 Current Price:  ₹{d['current']}")
    lines.append(f"📈 52W High:       ₹{d['high_52w']}  ({d['from_high']}% from high)")
    lines.append(f"📉 52W Low:        ₹{d['low_52w']}  (+{d['from_low']}% from low)\n")

    lines.append(f"📅 RECENT PERFORMANCE")
    w_icon = "🟢" if d["change_1w"] >= 0 else "🔴"
    m_icon = "🟢" if d["change_1m"] >= 0 else "🔴"
    q_icon = "🟢" if d["change_3m"] >= 0 else "🔴"
    lines.append(f"  {w_icon} 1 Week:   {d['change_1w']}%")
    lines.append(f"  {m_icon} 1 Month:  {d['change_1m']}%")
    lines.append(f"  {q_icon} 3 Months: {d['change_3m']}%\n")

    lines.append(f"📐 TECHNICAL INDICATORS")
    lines.append(f"  Trend:    {d['trend']}")
    lines.append(f"  SMA 20:   ₹{d['sma20']}  ({'above' if d['current'] > d['sma20'] else 'below'} avg ↗)" )
    lines.append(f"  SMA 50:   ₹{d['sma50']}  ({'above' if d['current'] > d['sma50'] else 'below'} avg ↗)")
    lines.append(f"  RSI(14):  {d['rsi']} — {d['rsi_signal']}")
    vol_txt = "HIGH 🔥 (strong interest)" if d["vol_ratio"] > 1.5 else ("LOW 😴 (weak interest)" if d["vol_ratio"] < 0.7 else "NORMAL")
    lines.append(f"  Volume:   {vol_txt}\n")

    lines.append(f"🔮 PRICE FORECAST (linear trend model)")
    p7_icon  = "🟢" if d["pred_7d"]  >= d["current"] else "🔴"
    p30_icon = "🟢" if d["pred_30d"] >= d["current"] else "🔴"
    p90_icon = "🟢" if d["pred_90d"] >= d["current"] else "🔴"
    p7_pct   = round((d["pred_7d"]  - d["current"]) / d["current"] * 100, 1)
    p30_pct  = round((d["pred_30d"] - d["current"]) / d["current"] * 100, 1)
    p90_pct  = round((d["pred_90d"] - d["current"]) / d["current"] * 100, 1)
    lines.append(f"  {p7_icon}  7 Days:  ₹{d['pred_7d']}  ({'+' if p7_pct>=0 else ''}{p7_pct}%)")
    lines.append(f"  {p30_icon} 30 Days: ₹{d['pred_30d']} ({'+' if p30_pct>=0 else ''}{p30_pct}%)")
    lines.append(f"  {p90_icon} 90 Days: ₹{d['pred_90d']} ({'+' if p90_pct>=0 else ''}{p90_pct}%)\n")

    lines.append(f"🤖 AI VERDICT  (score: {d['score']}/6)")
    lines.append(f"  {d['rec']}\n")

    # Plain language explanation
    if d["score"] >= 5:
        lines.append("💬 The stock is showing strong momentum, trading above key averages with positive trend. Good time to consider buying.")
    elif d["score"] == 4:
        lines.append("💬 Stock looks decent. Trend is positive but not perfect. Consider buying in small quantity.")
    elif d["score"] == 3:
        lines.append("💬 Mixed signals. Wait for clearer trend before investing.")
    else:
        lines.append("💬 Stock is underperforming. Better to avoid or wait for recovery signs.")

    lines.append("\n⚠️ Note: Forecast uses 60-day linear trend. Not financial advice.")
    return "\n".join(lines)


def get_stock_context(holdings, balance):
    """Build rich portfolio context string for AI"""
    lines = ["User portfolio context:"]
    lines.append(f"Available cash balance: Rs {balance:,.2f}")

    if holdings:
        total_invested = sum(h["avg_price"] * h["qty"] for h in holdings)
        total_current  = sum(h["current_price"] * h["qty"] for h in holdings)
        total_pnl      = total_current - total_invested
        total_pnl_pct  = round(total_pnl / total_invested * 100, 2) if total_invested > 0 else 0
        total_wealth   = balance + total_current

        lines.append(f"Total invested: Rs {total_invested:,.2f}")
        lines.append(f"Current portfolio value: Rs {total_current:,.2f}")
        lines.append(f"Total P&L: Rs {total_pnl:,.2f} ({total_pnl_pct}%)")
        lines.append(f"Total wealth: Rs {total_wealth:,.2f}")
        lines.append("")
        lines.append("Holdings detail:")

        for h in holdings:
            weight = round(h["current_price"] * h["qty"] / total_current * 100, 1) if total_current > 0 else 0
            # Drawdown from peak (approx using avg price as reference)
            drawdown = round(((h["current_price"] - h["avg_price"]) / h["avg_price"]) * 100, 2)
            lines.append(
                f"- {h['symbol']}: {h['qty']} shares | avg Rs {h['avg_price']} | "
                f"current Rs {h['current_price']} | P&L Rs {h['profit']} ({h['profit_pct']}%) | "
                f"portfolio weight: {weight}% | price change from buy: {drawdown}%"
            )

        # Risk assessment data
        losers  = [h for h in holdings if h["profit_pct"] < -5]
        winners = [h for h in holdings if h["profit_pct"] > 5]
        indian  = [h for h in holdings if h["symbol"].endswith(".NS")]
        us      = [h for h in holdings if not h["symbol"].endswith(".NS")]

        lines.append("")
        lines.append(f"Portfolio stats: {len(holdings)} positions | {len(winners)} winners | {len(losers)} losers")
        lines.append(f"Indian stocks: {len(indian)} | US stocks: {len(us)}")

        # Concentration warning
        for h in holdings:
            w = round(h["current_price"] * h["qty"] / total_current * 100, 1) if total_current > 0 else 0
            if w > 35:
                lines.append(f"WARNING: {h['symbol']} is {w}% of portfolio — highly concentrated")

    else:
        lines.append("No holdings yet.")

    return "\n".join(lines)


def call_groq_ai(user_message, portfolio_context, conversation_history):
    """Call Groq API with Llama 3"""
    import requests as req

    system_prompt = f"""You are FinBot — an expert Indian stock market AI advisor built into a stock trading simulator.
You have deep knowledge of NSE, BSE, global markets, technical analysis, fundamental analysis, and trading psychology.

{portfolio_context}

YOUR CAPABILITIES — you must handle ALL of these naturally:

1. RISK SCORE: When asked about portfolio risk, rate it 1-10 based on:
   - Concentration (single stock > 35% = high risk)
   - Number of losing positions
   - Indian vs US diversification
   - Overall P&L trend
   Format: "Risk Score: X/10" with explanation

2. TARGET PRICE: When user sets a target like "I want RELIANCE to hit 1600", calculate:
   - How far current price is from target (%)
   - Whether target is realistic based on trend
   - Estimated time to reach target

3. BEST TIME TO BUY: Analyze entry points using:
   - RSI levels (buy below 40, avoid above 70)
   - Price vs SMA20/SMA50 (buy near SMA support)
   - Recent dips as buying opportunities
   - Give specific price ranges to watch

4. SIMILAR STOCKS: When user asks for similar stocks to what they own:
   - Match by sector (IT, Banking, Pharma, Energy etc.)
   - Suggest 3-4 alternatives with brief reason
   - Compare fundamentals

5. PORTFOLIO SCORE: Grade the portfolio A/B/C/D based on:
   - Diversification across sectors
   - Overall P&L performance
   - Risk-reward balance
   - Number of positions

6. DRAWDOWN ALERT: Flag any stock that has dropped more than 8% from buy price
   - Use "🚨 DRAWDOWN ALERT" format
   - Suggest stop-loss levels

7. REBALANCING: Analyze portfolio weights and suggest:
   - Which stocks to trim (over 30% weight)
   - Which sectors are missing
   - How to redistribute for better balance

8. FUTURE PRICE PREDICTION: For any stock asked, provide:
   - Short term target (1 month)
   - Medium term target (3 months)
   - Long term target (1 year)
   - Bull case and Bear case scenarios
   - Key levels to watch (support/resistance)

9. GENERAL QUESTIONS: Answer ANY stock market question — concepts, news, strategy, psychology

RESPONSE RULES:
- Always use Rs for Indian prices
- Use emojis to make responses scannable (✅ ❌ 🟢 🔴 📈 📉 ⚠️)
- Keep responses concise but complete
- Use bullet points for lists
- Always end stock predictions with "⚠️ Educational simulator only"
- Never refuse a stock-related question
- Be conversational and friendly"""

    messages = conversation_history + [{"role": "user", "content": user_message}]

    try:
        response = req.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {app.config['GROQ_API_KEY']}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "system", "content": system_prompt}] + messages,
                "max_tokens": 1024,
                "temperature": 0.7
            },
            timeout=30
        )
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Sorry, AI is temporarily unavailable. Error: {str(e)}"


@app.route("/advisor/chat", methods=["POST"])
def advisor_chat():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json()
    user_message = data.get("message", "")
    conversation_history = data.get("history", [])

    user = User.query.get(session["user_id"])
    transactions = Transaction.query.filter_by(user_id=user.id).all()

    portfolio = {}
    for t in transactions:
        if t.symbol not in portfolio:
            portfolio[t.symbol] = {"qty": 0, "total": 0}
        portfolio[t.symbol]["qty"] += t.quantity
        portfolio[t.symbol]["total"] += t.price * t.quantity

    holdings = []
    for symbol, d in portfolio.items():
        qty = d["qty"]
        if qty <= 0:
            continue
        avg_price = d["total"] / qty
        current_price = get_price(symbol)
        if current_price:
            profit = round((current_price - avg_price) * qty, 2)
            profit_pct = round(((current_price - avg_price) / avg_price) * 100, 2)
            holdings.append({
                "symbol": symbol,
                "qty": qty,
                "avg_price": round(avg_price, 2),
                "current_price": current_price,
                "profit": profit,
                "profit_pct": profit_pct
            })

    portfolio_context = get_stock_context(holdings, user.balance)
    reply = call_groq_ai(user_message, portfolio_context, conversation_history)

    # Save chat to database
    try:
        db.session.add(ChatHistory(user_id=user.id, role="user",      message=user_message))
        db.session.add(ChatHistory(user_id=user.id, role="assistant", message=reply))
        # Update last seen
        us = UserSession.query.filter_by(user_id=user.id).first()
        if us:
            us.last_seen = datetime.now(pytz.timezone("Asia/Kolkata"))
        db.session.commit()
    except:
        pass

    return jsonify({"reply": reply})


# ═══════════════════════════════════════════
# AI ADVISOR FEATURE ROUTES
# ═══════════════════════════════════════════

def get_user_holdings(user_id):
    """Helper to get holdings for a user"""
    transactions = Transaction.query.filter_by(user_id=user_id).all()
    portfolio = {}
    for t in transactions:
        if t.symbol not in portfolio:
            portfolio[t.symbol] = {"qty": 0, "total": 0}
        portfolio[t.symbol]["qty"] += t.quantity
        portfolio[t.symbol]["total"] += t.price * t.quantity

    holdings = []
    for symbol, d in portfolio.items():
        qty = d["qty"]
        if qty <= 0:
            continue
        avg_price = d["total"] / qty
        current_price = get_price(symbol)
        if current_price:
            profit = round((current_price - avg_price) * qty, 2)
            profit_pct = round(((current_price - avg_price) / avg_price) * 100, 2)
            holdings.append({
                "symbol": symbol, "qty": qty,
                "avg_price": round(avg_price, 2),
                "current_price": current_price,
                "profit": profit, "profit_pct": profit_pct
            })
    return holdings


@app.route("/advisor/risk")
def advisor_risk():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    user = User.query.get(session["user_id"])
    holdings = get_user_holdings(user.id)
    if not holdings:
        return jsonify({"score": 0, "label": "N/A", "details": "No holdings yet."})

    total_current = sum(h["current_price"] * h["qty"] for h in holdings)
    score = 5  # base

    # Concentration risk
    for h in holdings:
        w = h["current_price"] * h["qty"] / total_current * 100 if total_current > 0 else 0
        if w > 50: score += 2
        elif w > 35: score += 1

    # Losing positions
    losers = [h for h in holdings if h["profit_pct"] < -5]
    score += len(losers)

    # Diversification bonus
    indian = len([h for h in holdings if h["symbol"].endswith(".NS")])
    us     = len([h for h in holdings if not h["symbol"].endswith(".NS")])
    if indian > 0 and us > 0: score -= 1
    if len(holdings) >= 6:    score -= 1

    score = max(1, min(10, score))

    if score <= 3:   label = "LOW RISK 🟢"
    elif score <= 6: label = "MODERATE RISK 🟡"
    else:            label = "HIGH RISK 🔴"

    details = []
    for h in holdings:
        w = round(h["current_price"] * h["qty"] / total_current * 100, 1) if total_current > 0 else 0
        if w > 35: details.append(f"⚠️ {h['symbol']} is {w}% of portfolio")
    for h in losers:
        details.append(f"🔴 {h['symbol']} down {h['profit_pct']}%")

    return jsonify({"score": score, "label": label, "details": details})


@app.route("/advisor/drawdown")
def advisor_drawdown():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    user = User.query.get(session["user_id"])
    holdings = get_user_holdings(user.id)
    alerts = []
    for h in holdings:
        if h["profit_pct"] <= -8:
            alerts.append({
                "symbol": h["symbol"],
                "drop": h["profit_pct"],
                "loss": h["profit"],
                "stop_loss": round(h["avg_price"] * 0.90, 2),
                "current": h["current_price"]
            })
    return jsonify({"alerts": alerts})


@app.route("/advisor/rebalance")
def advisor_rebalance():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    user = User.query.get(session["user_id"])
    holdings = get_user_holdings(user.id)
    if not holdings:
        return jsonify({"tips": []})

    total = sum(h["current_price"] * h["qty"] for h in holdings)
    tips = []
    indian = [h for h in holdings if h["symbol"].endswith(".NS")]
    us     = [h for h in holdings if not h["symbol"].endswith(".NS")]

    for h in holdings:
        w = round(h["current_price"] * h["qty"] / total * 100, 1) if total > 0 else 0
        if w > 35:
            tips.append({"type": "trim",   "symbol": h["symbol"], "weight": w, "msg": f"Consider trimming — {w}% is too concentrated"})
        elif w < 5 and h["profit_pct"] > 5:
            tips.append({"type": "add",    "symbol": h["symbol"], "weight": w, "msg": f"Only {w}% weight but performing well — consider adding"})

    if not indian: tips.append({"type": "diversify", "symbol": "NSE", "weight": 0, "msg": "Add Indian stocks for INR exposure"})
    if not us:     tips.append({"type": "diversify", "symbol": "US",  "weight": 0, "msg": "Add US stocks for global exposure"})
    if len(holdings) < 5: tips.append({"type": "diversify", "symbol": "ALL", "weight": 0, "msg": f"Only {len(holdings)} stocks — aim for 8-12 for better diversification"})

    return jsonify({"tips": tips})


# CHAT HISTORY ROUTES
@app.route("/advisor/history/sessions")
def chat_sessions():
    if "user_id" not in session:
        return jsonify([])
    chats = ChatHistory.query.filter_by(
        user_id=session["user_id"]
    ).order_by(ChatHistory.timestamp.asc()).all()

    if not chats:
        return jsonify([])

    # Group into sessions: new session = gap > 30 mins between messages
    sessions = []
    current = []
    prev_time = None

    for c in chats:
        # Make timezone-aware comparison
        c_time = c.timestamp
        if c_time.tzinfo is None:
            c_time = pytz.timezone("Asia/Kolkata").localize(c_time)

        if prev_time is not None:
            diff = (c_time - prev_time).total_seconds()
            if diff > 1800:  # 30 min gap = new session
                if current:
                    sessions.append(current)
                current = []

        current.append({
            "role":    c.role,
            "message": c.message[:120] + ("..." if len(c.message) > 120 else ""),
            "full":    c.message,
            "time":    c.timestamp.strftime("%d %b %I:%M %p")
        })
        prev_time = c_time

    if current:
        sessions.append(current)

    # Return newest first, max 30 sessions
    sessions.reverse()
    return jsonify(sessions[:30])


@app.route("/advisor/history")
def advisor_history():
    if "user_id" not in session:
        return redirect("/login")
    chats = ChatHistory.query.filter_by(user_id=session["user_id"]).order_by(ChatHistory.timestamp).all()
    return render_template("chat_history.html", chats=chats)


@app.route("/advisor/history/clear", methods=["POST"])
def clear_chat_history():
    if "user_id" not in session:
        return redirect("/login")
    ChatHistory.query.filter_by(user_id=session["user_id"]).delete()
    db.session.commit()
    return redirect("/advisor/history")


# HEARTBEAT - keeps user online status updated
@app.route("/heartbeat", methods=["POST"])
def heartbeat():
    if "user_id" in session:
        us = UserSession.query.filter_by(user_id=session["user_id"]).first()
        if us:
            us.last_seen = datetime.now(pytz.timezone("Asia/Kolkata"))
            us.is_online = True
            db.session.commit()
    return jsonify({"ok": True})


# ADMIN DASHBOARD
ADMIN_USERNAME = "Moksha Jain"  # Admin username

@app.route("/admin")
def admin_dashboard():
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    if user.username != ADMIN_USERNAME:
        return "Access denied", 403

    from datetime import timedelta
    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    cutoff = now - timedelta(minutes=5)

    all_users = User.query.all()
    user_data = []
    for u in all_users:
        us = UserSession.query.filter_by(user_id=u.id).first()
        chat_count = ChatHistory.query.filter_by(user_id=u.id).count()
        tx_count   = Transaction.query.filter_by(user_id=u.id).count()
        is_online  = False
        last_seen  = None
        if us:
            # Make both timezone-aware for comparison
            last_seen_aware = us.last_seen
            if last_seen_aware.tzinfo is None:
                last_seen_aware = pytz.timezone("Asia/Kolkata").localize(last_seen_aware)
            is_online = us.is_online and last_seen_aware > cutoff
            last_seen = us.last_seen.strftime("%d %b %Y %I:%M %p") if us.last_seen else "Never"

        user_data.append({
            "id":         u.id,
            "username":   u.username,
            "balance":    round(u.balance, 2),
            "is_online":  is_online,
            "last_seen":  last_seen or "Never",
            "chat_count": chat_count,
            "tx_count":   tx_count
        })

    online_count = sum(1 for u in user_data if u["is_online"])
    total_users  = len(all_users)

    return render_template("admin.html",
        users=user_data,
        online_count=online_count,
        total_users=total_users
    )


# PORTFOLIO GROWTH CHART DATA
@app.route("/portfolio/history")
def portfolio_history():
    if "user_id" not in session:
        return jsonify([])

    transactions = Transaction.query.filter_by(
        user_id=session["user_id"]
    ).order_by(Transaction.time).all()

    if not transactions:
        return jsonify([])

    # Build daily wealth snapshots from transactions
    from collections import defaultdict
    import yfinance as yf2
    from datetime import timedelta

    # Get all unique symbols
    symbols = list(set(t.symbol for t in transactions))

    # Get current prices
    prices = {}
    for sym in symbols:
        p = get_price(sym)
        if p:
            prices[sym] = p

    # Build cumulative holdings over time
    snapshots = []
    holdings = defaultdict(int)
    balance = 1000000.0

    for t in transactions:
        holdings[t.symbol] += t.quantity
        balance -= t.price * t.quantity

        # Calculate portfolio value at this point using current prices as approximation
        portfolio_val = sum(
            holdings[s] * prices.get(s, 0)
            for s in holdings
        )
        total = round(balance + portfolio_val, 2)

        snapshots.append({
            "date": t.time.strftime("%d %b %Y"),
            "total": total,
            "label": f"{t.symbol} ({'BUY' if t.quantity > 0 else 'SELL'})"
        })

    return jsonify(snapshots)


# ═══════════════════════════════════════════
# MARKET SENTIMENT AI
# ═══════════════════════════════════════════

def fetch_news_headlines(ticker):
    """Fetch top news headlines for a stock ticker using multiple free sources"""
    import requests as req
    import xml.etree.ElementTree as ET

    # Clean ticker for search
    clean = ticker.replace(".NS", "").replace(".BO", "")

    headlines = []

    # Source 1: Google News RSS (free, no API key)
    try:
        url = f"https://news.google.com/rss/search?q={clean}+stock+NSE&hl=en-IN&gl=IN&ceid=IN:en"
        r = req.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:6]:
            title = item.findtext("title", "").strip()
            if title and clean.lower() in title.lower() or len(headlines) < 3:
                headlines.append(title)
    except:
        pass

    # Source 2: Economic Times RSS
    try:
        url2 = f"https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"
        r2 = req.get(url2, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        root2 = ET.fromstring(r2.content)
        for item in root2.findall(".//item")[:10]:
            title = item.findtext("title", "").strip()
            if title and clean.lower() in title.lower():
                headlines.append(title)
    except:
        pass

    # Deduplicate and limit to 8
    seen = set()
    unique = []
    for h in headlines:
        if h not in seen:
            seen.add(h)
            unique.append(h)
        if len(unique) >= 8:
            break

    return unique


def analyze_sentiment_with_llm(ticker, headlines):
    """Send headlines to Groq LLM for structured sentiment analysis"""
    import requests as req

    if not headlines:
        return {
            "sentiment": "Neutral",
            "score": 0,
            "confidence": "Low",
            "confidence_pct": 20,
            "positive_drivers": [],
            "negative_drivers": [],
            "market_impact": "No recent news found for this stock.",
            "analyst_insight": "Insufficient data to provide analysis.",
            "headlines": []
        }

    headlines_text = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines))

    prompt = f"""Analyze the sentiment of the following news headlines related to a stock and produce a structured market sentiment report.

Stock Ticker: {ticker}

News Headlines:
{headlines_text}

Instructions:
1. Determine the overall market sentiment toward the stock.
2. Classify sentiment as exactly one of: Strongly Bullish / Bullish / Neutral / Bearish / Strongly Bearish
3. Assign a sentiment score between -100 and +100 (+100 = extremely bullish, 0 = neutral, -100 = extremely bearish)
4. Identify key drivers influencing the sentiment.
5. Highlight potential risks or concerns mentioned in the news.
6. Provide a short forward-looking interpretation.

Return your response in this EXACT structured format (no extra text):
SENTIMENT: [Strongly Bullish/Bullish/Neutral/Bearish/Strongly Bearish]
SCORE: [number between -100 and +100]
CONFIDENCE: [Low/Medium/High]
POSITIVE_DRIVERS: [bullet1] | [bullet2] | [bullet3]
NEGATIVE_DRIVERS: [bullet1] | [bullet2] | [bullet3]
MARKET_IMPACT: [one sentence on how investors might react]
ANALYST_INSIGHT: [2-3 sentence professional financial interpretation]

Focus only on financial meaning of the headlines. No speculation beyond given information."""

    try:
        response = req.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {app.config['GROQ_API_KEY']}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
                "temperature": 0.2
            },
            timeout=25
        )
        text = response.json()["choices"][0]["message"]["content"]

        # Parse structured response
        sentiment       = "Neutral"
        score           = 0
        confidence      = "Medium"
        confidence_pct  = 50
        positive_drivers = []
        negative_drivers = []
        market_impact   = ""
        analyst_insight = ""

        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("SENTIMENT:"):
                val = line.replace("SENTIMENT:", "").strip()
                for s in ["Strongly Bullish","Bullish","Neutral","Bearish","Strongly Bearish"]:
                    if s.lower() in val.lower():
                        sentiment = s
                        break

            elif line.startswith("SCORE:"):
                try:
                    nums = [int(x) for x in line.replace("SCORE:","").split() if x.lstrip("-").isdigit()]
                    if nums:
                        score = max(-100, min(100, nums[0]))
                except:
                    score = 0

            elif line.startswith("CONFIDENCE:"):
                val = line.replace("CONFIDENCE:","").strip()
                if "High" in val:
                    confidence = "High"
                    confidence_pct = 85
                elif "Low" in val:
                    confidence = "Low"
                    confidence_pct = 30
                else:
                    confidence = "Medium"
                    confidence_pct = 60

            elif line.startswith("POSITIVE_DRIVERS:"):
                parts = line.replace("POSITIVE_DRIVERS:","").strip().split("|")
                positive_drivers = [p.strip().lstrip("•-* ") for p in parts if p.strip()]

            elif line.startswith("NEGATIVE_DRIVERS:"):
                parts = line.replace("NEGATIVE_DRIVERS:","").strip().split("|")
                negative_drivers = [p.strip().lstrip("•-* ") for p in parts if p.strip()]

            elif line.startswith("MARKET_IMPACT:"):
                market_impact = line.replace("MARKET_IMPACT:","").strip()

            elif line.startswith("ANALYST_INSIGHT:"):
                analyst_insight = line.replace("ANALYST_INSIGHT:","").strip()

        return {
            "sentiment": sentiment,
            "score": score,
            "confidence": confidence,
            "confidence_pct": confidence_pct,
            "positive_drivers": positive_drivers,
            "negative_drivers": negative_drivers,
            "market_impact": market_impact,
            "analyst_insight": analyst_insight,
            "headlines": headlines
        }

    except Exception as e:
        return {
            "sentiment": "Neutral",
            "score": 0,
            "confidence": "Low",
            "confidence_pct": 20,
            "positive_drivers": [],
            "negative_drivers": [],
            "market_impact": f"Could not analyze: {str(e)}",
            "analyst_insight": "",
            "headlines": headlines
        }


@app.route("/sentiment-page")
@app.route("/marketss")
def sentiment_page():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("marketss.html", stocks=ALL_STOCKS)


@app.route("/sentiment/<ticker>")
def market_sentiment(ticker):
    """Flask route: returns sentiment analysis for a stock ticker"""
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401

    ticker = ticker.upper()
    try:
        headlines = fetch_news_headlines(ticker)
        result = analyze_sentiment_with_llm(ticker, headlines)
        result["ticker"] = ticker
        # Ensure all values are JSON serializable
        safe_result = {
            "ticker":           str(result.get("ticker", ticker)),
            "sentiment":        str(result.get("sentiment", "Neutral")),
            "score":            int(result.get("score", 0)),
            "confidence":       str(result.get("confidence", "Medium")),
            "confidence_pct":   int(result.get("confidence_pct", 50)),
            "positive_drivers": [str(x) for x in result.get("positive_drivers", [])],
            "negative_drivers": [str(x) for x in result.get("negative_drivers", [])],
            "market_impact":    str(result.get("market_impact", "")),
            "analyst_insight":  str(result.get("analyst_insight", "")),
            "headlines":        [str(x) for x in result.get("headlines", [])]
        }
        return jsonify(safe_result)
    except Exception as e:
        return jsonify({"error": str(e), "ticker": ticker})


# LIVE NEWS FEED
@app.route("/news")
def get_news():
    import requests as req
    import xml.etree.ElementTree as ET

    feeds = [
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "https://www.moneycontrol.com/rss/marketreports.xml",
    ]

    articles = []
    for url in feeds:
        try:
            r = req.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
            root = ET.fromstring(r.content)
            for item in root.findall(".//item")[:5]:
                title = item.findtext("title", "").strip()
                link  = item.findtext("link", "").strip()
                pub   = item.findtext("pubDate", "").strip()
                if title:
                    articles.append({
                        "title": title,
                        "link": link,
                        "date": pub[:16] if pub else ""
                    })
        except:
            continue

    return jsonify(articles[:10])


if __name__ == "__main__":
    app.run(debug=True)
