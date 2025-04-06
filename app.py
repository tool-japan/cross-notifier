import os
from flask import Flask, request, redirect, render_template_string, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from cryptography.fernet import Fernet
from dotenv import load_dotenv

# Load .env
load_dotenv()

# Flask App
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "fallback_secret_key")

# PostgreSQL Config
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Fernet Encryptor
fernet = Fernet(os.environ.get("ENCRYPTION_KEY"))

# Flask-Login Setup
login_manager = LoginManager()
login_manager.init_app(app)

# --- Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120))
    smtp_email = db.Column(db.String(120))
    smtp_password = db.Column(db.Text)
    symbols = db.Column(db.Text)
    notify_enabled = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Routes ---
@app.route("/")
def home():
    if current_user.is_authenticated:
        return f"<h1>{current_user.username}さん、ようこそ！</h1><p><a href='/logout'>ログアウト</a></p>"
    return "<h1>ようこそ！cross-notifierへ</h1><p><a href='/login'>ログインはこちら</a></p>"

@app.route("/login", methods=["GET", "POST"])
def login():
    html = """<h1>ログインページ（仮）</h1><form method='POST'>
    <input name='username'><br>
    <input name='password' type='password'><br>
    <input type='submit' value='送信'></form>"""
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and user.password_hash == request.form["password"]:  # ← 本番ではハッシュチェックに変更してね！
            login_user(user)
            return redirect(url_for("mypage"))
    return render_template_string(html)

@app.route("/logout")
def logout():
    logout_user()
    return redirect("/")

@app.route("/register", methods=["GET", "POST"])
# @admin_required  ← 一時的にコメントアウト
@login_required
def register():
    html = """<h1>新規ユーザー登録（管理者専用）</h1>
    <form method='POST'>
    <input name='email' placeholder='通知先Email'><br>
    <input name='smtp_email'><br>
    <input name='smtp_password' type='password'><br>
    <input name='symbols' placeholder='銘柄リスト'><br>
    <label>通知ON <input type='checkbox' name='notify_enabled' value='true'></label><br>
    <input type='submit'></form>"""
    if request.method == "POST":
        user = current_user
        user.email = request.form["email"]
        user.smtp_email = request.form["smtp_email"]
        user.smtp_password = fernet.encrypt(request.form["smtp_password"].encode()).decode()
        user.symbols = request.form["symbols"]
        user.notify_enabled = request.form.get("notify_enabled") == "true"
        db.session.commit()
        return redirect(url_for("register"))
    return render_template_string(html)

@app.route("/mypage")
@login_required
def mypage():
    return f"<h1>{current_user.username}さん、ようこそ！</h1><p><a href='/logout'>ログアウト</a></p>"

@app.route("/users")
@login_required
def users():
    all_users = User.query.all()
    user_list = "<br>".join(f"{u.username} - {'admin' if u.is_admin else 'user'}" for u in all_users)
    return f"<h1>登録ユーザー一覧</h1><p>{user_list}</p>"

# --- Main ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
