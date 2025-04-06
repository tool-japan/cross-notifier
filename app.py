from flask import Flask, render_template_string, request, redirect, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
import os
from functools import wraps

# 環境変数の読み込み（Renderでは自動、ローカルで使う場合は必要）
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "devkey")

from cryptography.fernet import Fernet
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", Fernet.generate_key())
fernet = Fernet(ENCRYPTION_KEY)

# PostgreSQL URL優先（Render用）。なければSQLiteでローカル動作
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///users.db")

# DB & ログイン
db = SQLAlchemy(app)
login_manager = LoginManager(app)

# ログイン試行制限（DoS対策）
limiter = Limiter(get_remote_address, app=app, default_limits=["200/day", "50/hour"])

# ユーザーモデル
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    role = db.Column(db.String(10), default="user")  # "admin" or "user"

    email = db.Column(db.String(255), nullable=True)              # 通知先メールアドレス
    symbols = db.Column(db.Text, nullable=True)                   # 銘柄リスト（改行区切り）
    smtp_email = db.Column(db.String(255), nullable=True)         # 送信元Gmail
    smtp_password = db.Column(db.Text, nullable=True)             # Gmailアプリパスワード（暗号化）
    notify_enabled = db.Column(db.Boolean, default=True)          # 通知ON/OFF

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# 管理者だけアクセスできるデコレーター
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            abort(403)
        return f(*args, **kwargs)
    return wrapper

@app.route("/")
def home():
    return """
    <h1>ようこそ！cross-notifierへ</h1>
    <p><a href='/login'>ログインはこちら</a></p>
    """

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5/minute")  # 総当たり攻撃対策
def login():
    html = """
    <h1>ログインページ（仮）</h1>
    <form method='POST'>
        ユーザー名：<input name='username'><br>
        パスワード：<input name='password' type='password'><br>
        <input type='submit' value='送信'>
    </form>
    """
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and check_password_hash(user.password_hash, request.form["password"]):
            login_user(user)
            return redirect("/dashboard")
    return render_template_string(html)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")

@app.route("/mypage")
@login_required
def mypage():
    return f"<h1>{current_user.username}さん、ようこそ！</h1><p><a href='/logout'>ログアウト</a></p>"

@app.route("/register", methods=["GET", "POST"])
# @admin_required  ← 必要に応じてON（開発時はコメントアウト可）
def register():
    html = """
    <h1>新規ユーザー登録（管理者専用）</h1>
    <form method='POST'>
        ユーザー名：<input name='username'><br>
        パスワード：<input name='password' type='password'><br>
        権限：<select name='role'>
            <option value='user'>一般ユーザー</option>
            <option value='admin'>管理者</option>
        </select><br>
        <input type='submit' value='登録'>
    </form>
    """
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])
        role = request.form.get("role", "user")
        new_user = User(username=username, password_hash=password, role=role)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect("/mypage")
    return render_template_string(html)

@app.route("/users")
@admin_required
def show_users():
    users = User.query.all()
    html = "<h2>登録済みユーザー一覧</h2><ul>"
    for u in users:
        html += f"""
        <li>{u.username} - {u.role}
            <a href='/delete_user/{u.id}' onclick="return confirm('本当に削除しますか？');">🗑削除</a>
            <a href='/change_password/{u.id}'>🔑パスワード変更</a>
        </li>
        """
    html += "</ul>"
    return html

@app.route("/delete_user/<int:user_id>")
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    # 自分自身の削除を防止
    if user.id == current_user.id:
        return "自分自身のアカウントは削除できません", 403

    # 必要に応じて特定ユーザー（例: admin）保護
    if user.username == "admin":
        return "adminユーザーは削除できません", 403

    db.session.delete(user)
    db.session.commit()
    return redirect("/users")

@app.route("/change_password/<int:user_id>", methods=["GET", "POST"])
@admin_required
def change_password(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == "POST":
        new_password = request.form["new_password"]
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        return redirect("/users")
    
    return render_template_string(f"""
        <h1>{user.username} のパスワード変更</h1>
        <form method='POST'>
            新しいパスワード：<input name='new_password' type='password'><br>
            <input type='submit' value='変更'>
        </form>
    """)

@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    if request.method == "POST":
        current_user.notify_enabled = "notify" in request.form
        current_user.symbols = request.form["symbols"]
        current_user.email = request.form["email"]
        current_user.smtp_email = request.form["smtp_email"]

        # パスワード欄が空でなければ更新
        new_smtp_pw = request.form["smtp_password"]
        if new_smtp_pw:
            encrypted_pw = fernet.encrypt(new_smtp_pw.encode()).decode()
            current_user.smtp_password = encrypted_pw

        db.session.commit()
        return redirect("/dashboard")

    # 表示用に複合化
    try:
        decrypted_pw = fernet.decrypt(current_user.smtp_password.encode()).decode()
    except Exception:
        decrypted_pw = ""

    html = f"""
    <h1>通知設定ダッシュボード</h1>
    <form method="POST">
        🔘 通知ON：<input type="checkbox" name="notify" {"checked" if current_user.notify_enabled else ""}><br><br>
        📈 銘柄リスト（1行1銘柄）：<br>
        <textarea name="symbols" rows="10" cols="30">{current_user.symbols or ""}</textarea><br><br>
        📩 通知先メールアドレス：<br>
        <input name="email" value="{current_user.email or ''}"><br><br>
        ✉️ 送信用Gmailアドレス：<br>
        <input name="smtp_email" value="{current_user.smtp_email or ''}"><br><br>
        🔐 アプリパスワード（変更時のみ入力）：<br>
        <input type="password" name="smtp_password" value=""><br><br>
        <input type="submit" value="保存">
    </form>
    <br>
    <a href="/mypage">← マイページに戻る</a>
    """
    return render_template_string(html)

@app.route("/me")
@login_required
def show_my_info():
    try:
        decrypted_pw = fernet.decrypt(current_user.smtp_password.encode()).decode()
    except Exception:
        decrypted_pw = "(復号失敗)"

    return f"""
    <h1>現在の通知設定</h1>
    <ul>
        <li>通知ON: {'✅ 有効' if current_user.notify_enabled else '❌ 無効'}</li>
        <li>銘柄リスト:<pre>{current_user.symbols or '(未設定)'}</pre></li>
        <li>通知先メール: {current_user.email or '(未設定)'}</li>
        <li>送信元Gmail: {current_user.smtp_email or '(未設定)'}</li>
        <li>アプリパスワード: {decrypted_pw}</li>
    </ul>
    <p><a href='/dashboard'>← ダッシュボードに戻る</a></p>
    """



if __name__ == "__main__":
    # with app.app_context():
        # db.drop_all()   # ← 一時的に追加（既存テーブルを削除）
        # db.create_all() # ← テーブル作成
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
