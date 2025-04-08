import time
import yfinance as yf
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
from itertools import islice
from sqlalchemy.orm import scoped_session, sessionmaker
from dotenv import load_dotenv
import pytz
import jpholiday

load_dotenv()

# SES用
SES_SMTP_USER = os.environ.get("SES_SMTP_USER")
SES_SMTP_PASSWORD = os.environ.get("SES_SMTP_PASSWORD")
SES_FROM_EMAIL = os.environ.get("SES_FROM_EMAIL")

# Flask & DB初期化
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///users.db")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default_secret_key")
db = SQLAlchemy(app)

# モデル定義
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    symbols = db.Column(db.Text, nullable=False)
    notify_enabled = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(10), default="user")

class NotificationHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    cross_type = db.Column(db.String(10), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

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
        print(f"[{symbol}] ゴールデンクロス検出")
        return "golden"
    elif df["Cross"].iloc[-1] == -2:
        print(f"[{symbol}] デッドクロス検出")
        return "dead"
    print(f"[{symbol}] クロスなし")
    return None

# バッチ処理
def batch(iterable, size):
    it = iter(iterable)
    while True:
        chunk = list(islice(it, size))
        if not chunk:
            break
        yield chunk

# 取引時間チェック
def is_trading_hours():
    now_utc = datetime.utcnow()

    # 日本時間（平日9:00〜15:00 & 祝日除く）
    jst = now_utc.astimezone(pytz.timezone("Asia/Tokyo"))
    if jst.weekday() < 5 and not jpholiday.is_holiday(jst.date()):
        if jst.hour == 9 or (10 <= jst.hour < 15):
            return True

    # 米国時間（平日 9:30〜16:00 / EST or EDT）
    est = now_utc.astimezone(pytz.timezone("US/Eastern"))
    if est.weekday() < 5:
        if (est.hour == 9 and est.minute >= 30) or (10 <= est.hour < 16):
            return True

    return False

# メインループ
def main_loop():
    with app.app_context():
        Session = scoped_session(sessionmaker(bind=db.engine))

        while True:
            print("ループ実行:", datetime.utcnow())

            if not is_trading_hours():
                print("📛 現在は取引時間外のためスキップします\n")
                time.sleep(300)
                continue

            db_session = Session()
            users = db_session.query(User).filter_by(notify_enabled=True).all()
            all_symbols = set()
            user_map = {}

            # 管理者が登録した銘柄は全ユーザーに追加
            admin_symbols = set()
            for admin in users:
                if admin.role == "admin":
                    admin_symbols.update([s.strip() for s in admin.symbols.splitlines() if s.strip()])

            for u in users:
                user_symbols = set([s.strip() for s in u.symbols.splitlines() if s.strip()])
                if u.role != "admin":
                    user_symbols.update(admin_symbols)
                user_map[u.id] = (u, list(user_symbols))
                all_symbols.update(user_symbols)

            # データ取得
            cache = {}
            for batch_syms in batch(all_symbols, 10):
                for sym in batch_syms:
                    try:
                        df = yf.download(sym, period="20d", interval="1d", progress=False)
                        if not df.empty:
                            cache[sym] = df
                    except Exception as e:
                        print(f"エラー（{sym}）: {e}")

            print(f"{datetime.utcnow()} - Yahoo取得成功: {len(cache)}銘柄 / ユーザー登録合計: {len(all_symbols)}銘柄")

            for uid, (user, symbols) in user_map.items():
                print(f"ユーザーID {uid} の登録銘柄: {symbols}")
                msgs = []

                for sym in symbols:
                    if sym not in cache:
                        continue
                    cross_type = detect_cross(cache[sym].copy(), sym)
                    if not cross_type:
                        continue

                    twenty_min_ago = datetime.utcnow() - timedelta(minutes=20)
                    recent = db_session.query(NotificationHistory).filter_by(
                        user_id=uid, symbol=sym, cross_type=cross_type
                    ).filter(NotificationHistory.timestamp >= twenty_min_ago).first()

                    if recent:
                        print(f"{sym} は直近20分以内に {cross_type} 通知済み → スキップ")
                        continue

                    db_session.add(NotificationHistory(user_id=uid, symbol=sym, cross_type=cross_type))
                    msgs.append(f"{sym} で {'ゴールデンクロス' if cross_type == 'golden' else 'デッドクロス'}")

                if msgs and user.email:
                    body = "\n".join(msgs)
                    send_email(user.email.strip(), "【クロス検出通知】", body)
                    print(f"{datetime.utcnow()} - メール送信済み: {user.email} → {len(msgs)}件の通知")

            db_session.commit()
            print(f"{datetime.utcnow()} - 全ユーザーのクロス判定完了。5分休憩します...\n", flush=True)
            Session.remove()
            time.sleep(300)

if __name__ == "__main__":
    main_loop()
