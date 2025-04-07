import time
import yfinance as yf
from email.mime.text import MIMEText
import smtplib
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
from itertools import islice
from sqlalchemy.orm import scoped_session, sessionmaker

# SES用 環境変数
SES_SMTP_USER = os.environ.get("SES_SMTP_USER")
SES_SMTP_PASSWORD = os.environ.get("SES_SMTP_PASSWORD")
SES_FROM_EMAIL = os.environ.get("SES_FROM_EMAIL")

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
db = SQLAlchemy(app)

# DBモデル
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    symbols = db.Column(db.Text, nullable=False)
    notify_enabled = db.Column(db.Boolean, default=True)

# メール送信関数（Amazon SES）
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
        return f"{symbol} で ゴールデンクロス"
    elif df["Cross"].iloc[-1] == -2:
        print(f"[{symbol}] デッドクロス検出")
        return f"{symbol} で デッドクロス"
    print(f"[{symbol}] クロスなし")
    return None

# 10件ずつ処理
def batch(iterable, size):
    it = iter(iterable)
    while True:
        chunk = list(islice(it, size))
        if not chunk:
            break
        yield chunk

# メイン処理ループ
def main_loop():
    with app.app_context():
        Session = scoped_session(sessionmaker(bind=db.engine))

        while True:
            print("ループ実行:", datetime.now())
            db_session = Session()

            users = db_session.query(User).filter_by(notify_enabled=True).all()
            all_symbols = set()
            user_map = {}

            for user in users:
                syms = [s.strip() for s in user.symbols.splitlines() if s.strip()]
                user_map[user.id] = (user, syms)
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

            failed = [s for s in all_symbols if s not in cache]
            if failed:
                print(f"{datetime.now()} - ⚠️ Yahoo取得失敗: {failed}")

            print(f"{datetime.now()} - Yahoo取得成功: {len(cache)}銘柄")

            for uid, (user, symbols) in user_map.items():
                print(f"ユーザーID {uid} の登録銘柄: {symbols}")
                msgs = []
                for sym in symbols:
                    if sym in cache:
                        msg = detect_cross(cache[sym].copy(), sym)
                        if msg:
                            msgs.append(msg)
                if msgs:
                    if user.email:
                        body = "\n".join(msgs)
                        send_email(user.email, "【クロス検出通知】", body)
                        print(f"{datetime.now()} - メール送信済み: {user.email}")
                    else:
                        print(f"{datetime.now()} - ⚠️ メールアドレス未設定: ユーザーID {uid}")

            print(f"{datetime.now()} - 実判定数: {sum(len(s) for _, s in user_map.values())}")
            Session.remove()
            print(f"{datetime.now()} - 次回まで待機...\n")
            time.sleep(300)

if __name__ == "__main__":
    main_loop()
