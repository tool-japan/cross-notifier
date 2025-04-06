import os
from flask import Flask, request, redirect, url_for, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

# .env 読み込み（RenderではWebから環境変数登録する）
load_dotenv()

# Flask アプリ初期化
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY')
db = SQLAlchemy(app)

# 暗号化用キー
fernet = Fernet(os.getenv('ENCRYPTION_KEY'))

# ログイン管理
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ユーザーモデル
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(120))
    smtp_email = db.Column(db.String(120))
    smtp_password = db.Column(db.String(256))
    symbols = db.Column(db.String(256))
    notify_enabled = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)

# ユーザー取得関数
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# ホーム画面
@app.route("/")
def home():
    if current_user.is_authenticated:
        return f"<h1>{current_user.username}さん、ようこそ！</h1><p><a href='/logout'>ログアウト</a></p>"
    return "<h1>ようこそ！cross-notifierへ</h1><p><a href='/login'>ログインはこちら</a></p>"

# ログイン
@app.route("/login", methods=["GET", "POST"])
def login():
    html = """<h1>ログインページ</h1><form method='POST'>
    <input name='username' placeholder='ユーザー名'><br>
    <input name='password' type='password' placeholder='パスワード'><br>
    <input type='submit' value='ログイン'>
    </form>"""
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and check_password_hash(user.password_hash, request.form["password"]):
            login_user(user)
            return redirect(url_for("register"))
    return render_template_string(html)

# ログアウト
@app.route("/logout")
def logout():
    logout_user()
    return redirect("/login")

# 登録画面（仮）
@app.route("/register", methods=["GET", "POST"])
@login_required
def register():
    html = """
    <h1>新規ユーザー登録（管理者専用）</h1>
    <form method='POST'>
        <input name='email' placeholder='通知用メール'><br>
        <input name='smtp_email' placeholder='SMTPログイン用メール'><br>
        <input name='smtp_password' type='password' placeholder='SMTPパスワード'><br>
        <input name='symbols' placeholder='通知銘柄 (例: AAPL,GOOG)'><br>
        <label><input type='checkbox' name='notify_enabled' value='true'>通知ON</label><br>
        <input type='submit' value='更新'>
    </form>
    """
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

# 登録ユーザー確認ページ（開発用）
@app.route("/users")
def show_users():
    users = User.query.all()
    html = "<h1>登録済みユーザー一覧</h1><ul>"
    for user in users:
        html += f"<li>{user.username} - {'admin' if user.is_admin else 'user'} - password: {user.password_hash}</li>"
    html += "</ul>"
    return html

# --- この行を追加！ ---
with app.app_context():
    db.create_all()

# アプリ起動
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
