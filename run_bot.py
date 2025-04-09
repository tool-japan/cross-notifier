import time
import yfinance as yf
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from cryptography.fernet import Fernet
from datetime import datetime, timedelta
import os
from sqlalchemy.orm import scoped_session, sessionmaker
from concurrent.futures import ThreadPoolExecutor
import re

# SES用 環境変数
SES_SMTP_USER = os.environ.get("SES_SMTP_USER")
SES_SMTP_PASSWORD = os.environ.get("SES_SMTP_PASSWORD")
SES_FROM_EMAIL = os.environ.get("SES_FROM_EMAIL")

# Flask & DB初期化
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///users.db")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default_secret_key")
db = SQLAlchemy(app)

ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", Fernet.generate_key())
fernet = Fernet(ENCRYPTION_KEY)

# モデル定義
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    symbols = db.Column(db.Text, nullable=False)
    notify_enabled = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(10), default="user")  # "admin" or "user"

# メール送信
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
        print("メール送信エラー:", e)

# クロス検出
def detect_cross(df, symbol):
    df["EMA9"] = df["Close"].ewm(span=9).mean()
    df["EMA20"] = df["Close"].ewm(span=20).mean()
    df["Signal"] = 0
    df.loc[df["EMA9"] > df["EMA20"], "Signal"] = 1
    df.loc[df["EMA9"] < df["EMA20"], "Signal"] = -1
    df["Cross"] = df["Signal"].diff()

    if df["Cross"].iloc[-1] == 2:
        return f"{symbol} で ゴールデンクロス"
    elif df["Cross"].iloc[-1] == -2:
        return f"{symbol} で デッドクロス"
    return None

# シンボル補正（日本株は.Tを付ける）
def normalize_symbol(sym):
    return f"{sym}.T" if re.match(r"^\d", sym) and not sym.endswith(".T") else sym

# シンボル取得処理（並列化用）
def fetch_symbol_data(sym):
    try:
        df = yf.download(sym, period="20d", interval="1d", progress=False)
        return (sym, df if not df.empty else None)
    except Exception as e:
        print(f"データ取得エラー（{sym}）: {e}")
        return (sym, None)

# メインループ
def main_loop():
    with app.app_context():
        Session = scoped_session(sessionmaker(bind=db.engine))

        while True:
            print("ループ実行:", datetime.now())

            db_session = Session()
            users = db_session.query(User).filter_by(notify_enabled=True).all()
            all_symbols = set()
            user_map = {}

            for u in users:
                raw_syms = u.symbols.splitlines()
                cleaned_syms = list({normalize_symbol(s.strip()) for s in raw_syms if s.strip()})

                # 管理者/一般ユーザーの制限
                limit = 10000 if u.role == "admin" else 100
                limited_syms = cleaned_syms[:limit]
                user_map[u.id] = (u, limited_syms)
                all_symbols.update(limited_syms)

            print(f"総ユニーク銘柄数: {len(all_symbols)}")

            # 並列取得
            cache = {}
            with ThreadPoolExecutor(max_workers=20) as executor:
                results = executor.map(fetch_symbol_data, all_symbols)

            for sym, df in results:
                if df is not None:
                    cache[sym] = df

            print(f"{datetime.now()} - 取得成功: {len(cache)}銘柄 / 全体: {len(all_symbols)}銘柄")

            # 通知判定
            for uid, (user, symbols) in user_map.items():
                print(f"ユーザーID {uid} - 登録銘柄数: {len(symbols)}")
                msgs = []
                for sym in symbols:
                    if sym in cache:
                        msg = detect_cross(cache[sym].copy(), sym)
                        if msg:
                            msgs.append(msg)
                if msgs:
                    body = "\n".join(msgs)
                    send_email(user.email.strip(), "【クロス検出通知】", body)
                    print(f"{datetime.now()} - 通知送信: {user.email} → {len(msgs)}件")

            Session.remove()
            print(f"{datetime.now()} - ループ完了。次回まで休止...\n")
            time.sleep(300)

if __name__ == "__main__":
    main_loop()
