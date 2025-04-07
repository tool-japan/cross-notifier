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
from itertools import islice
from sqlalchemy.orm import scoped_session, sessionmaker
from dotenv import load_dotenv

load_dotenv()

# SES設定
SES_SMTP_USER = os.environ.get("SES_SMTP_USER")
SES_SMTP_PASSWORD = os.environ.get("SES_SMTP_PASSWORD")
SES_FROM_EMAIL = os.environ.get("SES_FROM_EMAIL")

# Flask & DB初期化
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///users.db")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default_secret_key")
db = SQLAlchemy(app)

# 暗号化キー（未使用だが互換性保持）
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", Fernet.generate_key())
fernet = Fernet(ENCRYPTION_KEY)

# ユーザーテーブル
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    symbols = db.Column(db.Text, nullable=False)
    notify_enabled = db.Column(db.Boolean, default=True)

# 通知履歴テーブル
class NotificationHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    cross_type = db.Column(db.String(10), nullable=False)  # 'golden' or 'dead'
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

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

# 10分以内の同一通知履歴があるか
def recently_notified(db_session, user_id, symbol, cross_type):
    ten_minutes_ago = datetime.utcnow() - timedelta(minutes=10)
    return db_session.query(NotificationHistory).filter_by(
        user_id=user_id, symbol=symbol, cross_type=cross_type
    ).filter(NotificationHistory.timestamp >= ten_minutes_ago).first() is not None

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
                syms = [s.strip() for s in u.symbols.splitlines() if s.strip()]
                user_map[u.id] = (u, syms)
                all_symbols.update(syms)

            # データ取得
            cache = {}
            for batch_syms in batch(all_symbols, 10):
                for sym in batch_syms:
                    try:
                        df = yf.download(sym, period="20d", interval="1d")
                        if not df.empty:
                            cache[sym] = df
                    except Exception as e:
                        print(f"エラー（{sym}）: {e}")

            failed_symbols = [sym for sym in all_symbols if sym not in cache]
            if failed_symbols:
                print(f"{datetime.now()} - ⚠️ Yahoo取得失敗: {len(failed_symbols)}銘柄 → {failed_symbols}")

            print(f"{datetime.now()} - Yahoo取得成功: {len(cache)}銘柄 / ユーザー登録合計: {len(all_symbols)}銘柄")

            # 各ユーザー通知処理
            for uid, (user, symbols) in user_map.items():
                print(f"ユーザーID {uid} の登録銘柄: {symbols}")
                msgs = []
                for sym in symbols:
                    if sym in cache:
                        cross = detect_cross(cache[sym].copy(), sym)
                        if cross and not recently_notified(db_session, uid, sym, cross):
                            msgs.append(f"{sym} で {'ゴールデンクロス' if cross == 'golden' else 'デッドクロス'}")
                            db_session.add(NotificationHistory(
                                user_id=uid, symbol=sym, cross_type=cross,
                                timestamp=datetime.utcnow()
                            ))
                if msgs and user.email:
                    body = "\n".join(msgs)
                    send_email(user.email, "【クロス検出通知】", body)
                    print(f"{datetime.now()} - メール送信済み: {user.email} → {len(msgs)}件の通知")
                elif not user.email:
                    print(f"{datetime.now()} - ⚠️ メールアドレス未設定のためスキップ: ユーザーID {uid}")

            db_session.commit()

            # ログ
            print(f"{datetime.now()} - ダウンロード成功: {len(cache)}銘柄")
            actual_checked = sum(1 for _, (user, symbols) in user_map.items() for sym in symbols if sym in cache)
            total_checked = sum(len(symbols) for _, (user, symbols) in user_map.items())
            print(f"{datetime.now()} - クロス判定対象（実際に判定）: {actual_checked}銘柄")
            print(f"{datetime.now()} - クロス判定対象（登録ベース）: {total_checked}銘柄")
            print(f"{datetime.now()} - 全ユーザーのクロス判定完了。5分休憩します...\n")

            Session.remove()
            time.sleep(100)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    main_loop()
