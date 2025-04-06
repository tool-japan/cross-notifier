import time
import yfinance as yf
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from cryptography.fernet import Fernet
from datetime import datetime
import os
  
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///users.db")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default_secret_key")
db = SQLAlchemy(app)

ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", Fernet.generate_key())
fernet = Fernet(ENCRYPTION_KEY)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    symbols = db.Column(db.Text, nullable=False)
    smtp_email = db.Column(db.String(255), nullable=False)
    smtp_password = db.Column(db.Text, nullable=False)
    notify_enabled = db.Column(db.Boolean, default=True)

def send_email(from_email, app_password, to_email, subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(from_email, app_password)
        server.sendmail(from_email, to_email, msg.as_string())
        server.quit()
    except Exception as e:
        print("メール送信エラー:", e)

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

def main_loop():
    with app.app_context(): 
        db.create_all()  # ← これを追加！
        while True:
            print("ループ実行:", datetime.now())
            users = User.query.filter_by(notify_enabled=True).all()
            all_symbols = set()
            user_map = {}
            for u in users:
                syms = [s.strip() for s in u.symbols.splitlines() if s.strip()]
                user_map[u.id] = (u, syms)
                all_symbols.update(syms)

            cache = {}
            for sym in all_symbols:
                df = yf.download(sym, period="5d", interval="5m")
                if not df.empty:
                    cache[sym] = df

            for uid, (user, symbols) in user_map.items():
                msgs = []
                for sym in symbols:
                    if sym in cache:
                        msg = detect_cross(cache[sym].copy(), sym)
                        if msg:
                            msgs.append(msg)
                if msgs:
                    body = "\n".join(msgs)
                    pw = fernet.decrypt(user.smtp_password.encode()).decode()
                    send_email(user.smtp_email, pw, user.email, "【クロス検出通知】", body)
            time.sleep(300)

if __name__ == "__main__":
    main_loop()
