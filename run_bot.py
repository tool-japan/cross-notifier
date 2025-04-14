import os
import time as time_module
from datetime import datetime, timedelta
from flask import Flask
from sqlalchemy.orm import scoped_session, sessionmaker
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
import holidays
import pandas as pd
import yfinance as yf
import pandas_ta as ta
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from models import db, User

# Flask & 環境設定
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
db.init_app(app)

load_dotenv()
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL")

# ⏰ 実行戦略マップ
TIME_STRATEGY_MAP = {
    "09:10": "オープニング逆張りスナイパー",
    "09:40": "モーニングトレンドハンター",
    "10:05": "ボリュームライディングブレイカー",
    "10:30": "ボリュームライディングブレイカー",
    "11:00": "サイレント・ゾーン・スキャナー",
    "12:40": "リバーサル・シーカー",
    "13:10": "リバーサル・シーカー",
    "13:30": "リバーサル・シーカー",
    "14:10": "クロージング・サージ・スナイパー",
    "14:30": "クロージング・サージ・スナイパー"
}

# メール送信
def send_email(to_email, subject, body):
    message = Mail(from_email=SENDGRID_FROM_EMAIL, to_emails=to_email, subject=subject, plain_text_content=body)
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"✅ メール送信成功: {to_email} {response.status_code}")
    except Exception as e:
        print("メール送信エラー:", e, flush=True)

# 各戦略のテクニカルロジック
def detect_rsi_stoch_signal(df):
    df = df.copy()
    df["RSI"] = ta.rsi(df["Close"], length=14)
    stoch = ta.stoch(df["High"], df["Low"], df["Close"], k=14, d=3)
    df[["STOCH_K", "STOCH_D"]] = stoch.values
    latest = df.dropna().iloc[-1]
    if latest.RSI < 30 and latest.STOCH_K < 20:
        return "RSI+ストキャスで売られすぎ → 買いシグナル"
    elif latest.RSI > 70 and latest.STOCH_K > 80:
        return "RSI+ストキャスで買われすぎ → 売りシグナル"
    return None

def detect_ma_rsi_signal(df):
    df = df.copy()
    df["SMA5"] = df["Close"].rolling(5).mean()
    df["SMA10"] = df["Close"].rolling(10).mean()
    df["RSI"] = ta.rsi(df["Close"], length=14)
    latest = df.dropna().iloc[-1]
    if latest.SMA5 > latest.SMA10 and latest.RSI > 50:
        return "移動平均5>10 & RSI高 → 上昇トレンド継続中（買い）"
    elif latest.SMA5 < latest.SMA10 and latest.RSI < 50:
        return "移動平均5<10 & RSI低 → 下降トレンド継続中（売り）"
    return None

def detect_volume_rsi_breakout(df):
    df = df.copy()
    df["RSI"] = ta.rsi(df["Close"], length=14)
    df["Vol_Avg"] = df["Volume"].rolling(10).mean()
    high_break = df["Close"] > df["High"].shift(1).rolling(10).max()
    latest = df.dropna().iloc[-1]
    if latest.Volume > latest.Vol_Avg * 1.5:
        if latest.RSI > 50 and high_break.iloc[-1]:
            return "出来高急増 + 高値ブレイク + RSI高 → 強い買いシグナル"
        elif latest.RSI < 50:
            return "出来高急増 + RSI低 → 売り圧力シグナル"
    return None

def detect_atr_low_volatility(df):
    df = df.copy()
    df["ATR"] = ta.atr(df["High"], df["Low"], df["Close"], length=14)
    return "ATR低下 → ボラティリティ低下と判断" if df["ATR"].iloc[-1] < df["ATR"].iloc[-10:-5].mean() * 0.6 else None

def detect_macd_reversal(df):
    df = df.copy()
    macd = ta.macd(df['Close'])
    if macd is None or macd.isnull().values.any():
        return None
    df[['MACD', 'Signal', 'Hist']] = macd.values
    df = df.dropna()
    if len(df) < 2:
        return None
    prev, curr = df.iloc[-2], df.iloc[-1]
    if prev.MACD < prev.Signal and curr.MACD > curr.Signal:
        return "MACDゴールデンクロス → 上昇反転シグナル"
    elif prev.MACD > prev.Signal and curr.MACD < curr.Signal:
        return "MACDデッドクロス → 下降反転シグナル"
    elif curr.MACD > curr.Signal and (curr.MACD - curr.Signal) > (prev.MACD - prev.Signal):
        return "MACD乖離拡大中 → 上昇トレンド継続中"
    elif curr.MACD < curr.Signal and (prev.MACD - prev.Signal) > (curr.MACD - curr.Signal):
        return "MACD乖離拡大中 → 下降トレンド継続中"
    return None

def detect_closing_surge(df):
    df = df.copy()
    df["Vol_Avg"] = df["Volume"].rolling(window=20).mean()
    latest = df.dropna().iloc[-1]
    ratio = latest["Volume"] / latest["Vol_Avg"] if latest["Vol_Avg"] > 0 else 0
    return f"出来高が平均の{ratio:.1f}倍 → 急騰銘柄の可能性" if ratio > 2 else None

# ユーティリティ
def batch(iterable, size):
    it = iter(iterable)
    while True:
        chunk = list([next(it, None) for _ in range(size)])
        chunk = [i for i in chunk if i]
        if not chunk:
            break
        yield chunk

def format_email_body(results, strategy_name):
    now_jst = datetime.utcnow() + timedelta(hours=9)
    timestamp = now_jst.strftime("%Y-%m-%d %H:%M:%S")
    body = f"\n【戦略】{strategy_name}\n通知時刻（日本時間）: {timestamp}\n"
    for symbol, signal in results:
        full = symbol + ".T"
        try:
            name = yf.Ticker(full).info.get("longName", "名称不明")
        except:
            name = "名称取得失敗"
        url = f"https://finance.yahoo.co.jp/quote/{full}"
        body += f"\n{symbol}\n{signal}\n{name}\n{url}\n"
    return body.strip()

# メインループ（±2分対応 + シグナル無し表示）
def main_loop():
    now = datetime.utcnow() + timedelta(hours=9)
    hour = now.strftime("%H")
    minute = now.minute
    candidates = [f"{hour}:{(minute + offset) % 60:02d}" for offset in [-2, -1, 0, 1, 2]]
    strategy_name = None
    for t in candidates:
        if t in TIME_STRATEGY_MAP:
            strategy_name = TIME_STRATEGY_MAP[t]
            break

    if not strategy_name:
        print(f"⏸ 現在の時刻 {now.strftime('%H:%M')} は戦略対象外です", flush=True)
        return

    if now.weekday() >= 5 or now.date() in holidays.Japan():
        print("⏸ 日本の休日または週末のためスキップ", flush=True)
        return

    print(f"🚀 現在の戦略: {strategy_name}", flush=True)

    with app.app_context():
        Session = scoped_session(sessionmaker(bind=db.engine))
        db_session = Session()

        users = db_session.query(User).filter_by(notify_enabled=True).all()
        user_map, all_symbols = {}, set()

        for u in users:
            syms = [s.strip() for s in u.symbols.splitlines() if s.strip() and s[0].isdigit()]
            user_map[u.id] = (u, syms)
            all_symbols.update(syms)

        symbols_to_fetch = [s + ".T" for s in all_symbols]
        cache, access_count = {}, 0

        for syms in batch(symbols_to_fetch, 10):
            for sym in syms:
                try:
                    print(f"📥 Downloading: {sym}", flush=True)
                    df = yf.download(sym, period="2d", interval="5m", progress=False)
                    if not df.empty:
                        cache[sym] = df
                        access_count += 1
                        if access_count % 100 == 0:
                            print("🔄 100件取得、5秒待機", flush=True)
                            time_module.sleep(5)
                except Exception as e:
                    print(f"❌ エラー({sym}): {e}", flush=True)

        for uid, (user, symbols) in user_map.items():
            results = []
            for sym in symbols:
                df = cache.get(sym + ".T")
                if df is None or df.empty:
                    print(f"⚠️ {sym} のデータが取得できませんでした", flush=True)
                    continue

                signal = None
                if strategy_name == "オープニング逆張りスナイパー":
                    signal = detect_rsi_stoch_signal(df)
                elif strategy_name == "モーニングトレンドハンター":
                    signal = detect_ma_rsi_signal(df)
                elif strategy_name == "ボリュームライディングブレイカー":
                    signal = detect_volume_rsi_breakout(df)
                elif strategy_name == "サイレント・ゾーン・スキャナー":
                    signal = detect_atr_low_volatility(df)
                elif strategy_name == "リバーサル・シーカー":
                    signal = detect_macd_reversal(df)
                elif strategy_name == "クロージング・サージ・スナイパー":
                    signal = detect_closing_surge(df)

                if signal:
                    results.append((sym, signal))
                else:
                    print(f"🔍 {sym} → シグナルなし", flush=True)

            if results:
                body = format_email_body(results, strategy_name)
                send_email(user.email, "【株式テクニカル分析検出通知】", body)
                print(f"📧 {user.username} へ通知: {results}", flush=True)

        db_session.close()

if __name__ == "__main__":
    main_loop()
