# ✅ デイトレード向けに最適化した run_bot.py（5分足 + EMA5/EMA12 使用）
import os
from datetime import datetime, timedelta, time
import time as time_module
import yfinance as yf
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from flask import Flask
from sqlalchemy.orm import scoped_session, sessionmaker
from dotenv import load_dotenv

from models import db, User

load_dotenv()

SES_SMTP_USER = os.environ.get("SES_SMTP_USER")
SES_SMTP_PASSWORD = os.environ.get("SES_SMTP_PASSWORD")
SES_FROM_EMAIL = os.environ.get("SES_FROM_EMAIL")

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///users.db")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default_secret_key")
db.init_app(app)

def send_email(to_email, subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = SES_FROM_EMAIL
    msg['To'] = to_email
    try:
        server = smtplib.SMTP('email-smtp.us-east-1.amazonaws.com', 587)
        server.starttls()
        server.login(SES_SMTP_USER, SES_SMTP_PASSWORD)
        server.sendmail(SES_FROM_EMAIL, to_email, msg.as_string())
        server.quit()
    except Exception as e:
        print("メール送信エラー:", e, flush=True)

def detect_cross(df, symbol):
    df["EMA5"] = df["Close"].ewm(span=5).mean()
    df["EMA12"] = df["Close"].ewm(span=12).mean()
    df["Signal"] = 0
    df.loc[df["EMA5"] > df["EMA12"], "Signal"] = 1
    df.loc[df["EMA5"] < df["EMA12"], "Signal"] = -1
    df["Cross"] = df["Signal"].diff()

    if df["Cross"].iloc[-1] == 2:
        return "ゴールデンクロス"
    elif df["Cross"].iloc[-1] == -2:
        return "デッドクロス"
    return None

def batch(iterable, size):
    it = iter(iterable)
    while True:
        chunk = list([next(it, None) for _ in range(size)])
        chunk = [i for i in chunk if i]
        if not chunk:
            break
        yield chunk

def format_email_body(results):
    jp = []
    us = []
    for symbol, cross_type in results:
        is_jp = symbol[0].isdigit()
        symbol_with_suffix = symbol + ".T" if is_jp else symbol

        try:
            info = yf.Ticker(symbol_with_suffix).info
            name = info.get("longName", "名称不明")
        except Exception:
            name = "名称取得失敗"

        signal = "買い気配" if "ゴールデンクロス" in cross_type else "売り気配"
        url = f"https://finance.yahoo.co.jp/quote/{symbol_with_suffix}"

        line = f"""{symbol}
{cross_type}→{signal}
{name}
{url}
"""
        if is_jp:
            jp.append(line)
        else:
            us.append(line)

    body = ""
    if jp:
        body += "国内株式\n" + "\n".join(jp) + "\n"
    if us:
        body += "米国株式\n" + "\n".join(us)

    return body.strip()

def main_loop():
    with app.app_context():
        Session = scoped_session(sessionmaker(bind=db.engine))

        # テスト用：一度だけ実行（本番用ループは下にコメントで残す）
        # while True:
        now_utc = datetime.utcnow()
        now_jst = now_utc + timedelta(hours=9)
        now_est = now_utc - timedelta(hours=4)

        print("ループ実行:", datetime.now(), flush=True)

        db_session = Session()
        users = db_session.query(User).filter_by(notify_enabled=True).all()
        all_symbols = set()
        user_map = {}

        for u in users:
            syms = [s.strip() for s in u.symbols.splitlines() if s.strip()]
            user_map[u.id] = (u, syms)
            all_symbols.update(syms)

        japan_symbols = {s for s in all_symbols if s[0].isdigit()}
        us_symbols = {s for s in all_symbols if s[0].isalpha()}

        symbols_to_fetch = set()
        symbols_to_fetch.update([s + ".T" for s in japan_symbols])
        symbols_to_fetch.update(us_symbols)

        print(f"{datetime.now()} - 処理対象シンボル数: {len(symbols_to_fetch)} 件", flush=True)

        cache = {}
        access_count = 0
        for batch_syms in batch(symbols_to_fetch, 10):
            for sym in batch_syms:
                try:
                    print(f"Downloading: {sym}", flush=True)
                    df = yf.download(sym, period="2d", interval="5m", progress=False)
                    if not df.empty:
                        cache[sym] = df
                        access_count += 1
                        if access_count % 100 == 0:
                            print("🔄 100件取得完了、5秒待機...", flush=True)
                            time_module.sleep(5)
                except Exception as e:
                    print(f"エラー（{sym}）: {e}", flush=True)

        failed_symbols = [sym for sym in symbols_to_fetch if sym not in cache]
        if failed_symbols:
            print(f"{datetime.now()} - ⚠️ Yahoo取得失敗: {len(failed_symbols)}銘柄 → {failed_symbols}", flush=True)

        print(f"{datetime.now()} - Yahoo取得成功: {len(cache)}銘柄 / ユーザー登録合計: {len(all_symbols)}銘柄", flush=True)

        for uid, (user, symbols) in user_map.items():
            results = []
            for sym in symbols:
                actual = sym + ".T" if sym[0].isdigit() else sym
                df = cache.get(actual)
                if df is not None:
                    cross_type = detect_cross(df, sym)
                    if cross_type:
                        results.append((sym, cross_type))

            if results:
                body = format_email_body(results)
                send_email(user.email, "【株式テクニカル分析検出通知】", body)
                print(f"📧 {user.username} へ通知: {results}", flush=True)

        db_session.close()

if __name__ == "__main__":
    main_loop()
