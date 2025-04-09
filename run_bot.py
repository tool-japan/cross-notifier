import os
from datetime import datetime, timedelta, time
import time as time_module
import yfinance as yf
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import scoped_session, sessionmaker
from dotenv import load_dotenv

load_dotenv()

# SES用環境変数
SES_SMTP_USER = os.environ.get("SES_SMTP_USER")
SES_SMTP_PASSWORD = os.environ.get("SES_SMTP_PASSWORD")
SES_FROM_EMAIL = os.environ.get("SES_FROM_EMAIL")

# Flask & DB初期化
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///users.db")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default_secret_key")
db = SQLAlchemy(app)

# ユーザーモデル
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    symbols = db.Column(db.Text, nullable=False)
    notify_enabled = db.Column(db.Boolean, default=True)

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
        return f"{symbol} で ゴールデンクロス"
    elif df["Cross"].iloc[-1] == -2:
        print(f"[{symbol}] デッドクロス検出")
        return f"{symbol} で デッドクロス"
    print(f"[{symbol}] クロスなし")
    return None

# バッチ処理
def batch(iterable, size):
    it = iter(iterable)
    while True:
        chunk = list([next(it, None) for _ in range(size)])
        chunk = [i for i in chunk if i]
        if not chunk:
            break
        yield chunk

# メインループ
def main_loop():
    with app.app_context():
        Session = scoped_session(sessionmaker(bind=db.engine))

        while True:
            now_utc = datetime.utcnow()
            now_jst = now_utc + timedelta(hours=9)
            now_est = now_utc - timedelta(hours=4)

            is_japan_time = now_jst.weekday() < 5 and time(9, 0) <= now_jst.time() <= time(15, 0)
            is_us_time = now_est.weekday() < 5 and time(9, 30) <= now_est.time() <= time(16, 0)

            if not is_japan_time and not is_us_time:
                print(f"{datetime.now()} - ⏸ 取引時間外のためスキップ")
                time_module.sleep(60)
                continue

            print("ループ実行:", datetime.now())

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

            if is_japan_time:
                symbols_to_fetch.update([s + ".T" for s in japan_symbols])
            if is_us_time:
                symbols_to_fetch.update(us_symbols)

            # データ取得（100アクセスごとに5秒休憩）
            cache = {}
            access_count = 0
            for batch_syms in batch(symbols_to_fetch, 10):
                for sym in batch_syms:
                    try:
                        df = yf.download(sym, period="20d", interval="1d", progress=False)
                        if not df.empty:
                            cache[sym] = df
                            access_count += 1
                            if access_count % 100 == 0:
                                print("🔄 100件取得完了、5秒待機...")
                                time_module.sleep(5)
                    except Exception as e:
                        print(f"エラー（{sym}）: {e}")

            failed_symbols = [sym for sym in symbols_to_fetch if sym not in cache]
            if failed_symbols:
                print(f"{datetime.now()} - ⚠️ Yahoo取得失敗: {len(failed_symbols)}銘柄 → {failed_symbols}")

            print(f"{datetime.now()} - Yahoo取得成功: {len(cache)}銘柄 / ユーザー登録合計: {len(all_symbols)}銘柄")

            for uid, (user, symbols) in user_map.items():
                msgs = []
                for sym in symbols:
                    actual = sym + ".T" if sym[0].isdigit() else sym
                    if actual in cache:
                        msg = detect_cross(cache[actual].copy(), actual)
                        if msg:
                            msgs.append(msg)

                if msgs:
                    email = (user.email or "").strip()
                    if email:
                        body = "\n".join(msgs)
                        send_email(email, "【クロス検出通知】", body)
                        print(f"{datetime.now()} - メール送信済み: {email} → {len(msgs)}件の通知")
                    else:
                        print(f"{datetime.now()} - ⚠️ メールアドレス未設定のため送信スキップ: ユーザーID {uid}")

            actual_checked = sum(
                1 for _, (user, symbols) in user_map.items()
                for sym in symbols if (sym + ".T" if sym[0].isdigit() else sym) in cache
            )
            total_checked = sum(len(symbols) for _, (user, symbols) in user_map.items())

            print(f"{datetime.now()} - クロス判定対象（実際に判定）: {actual_checked}銘柄")
            print(f"{datetime.now()} - クロス判定対象（登録ベース）: {total_checked}銘柄")
            print(f"{datetime.now()} - 全ユーザーのクロス判定完了。5分休憩します...\n")

            Session.remove()
            time_module.sleep(300)

if __name__ == "__main__":
    main_loop()
