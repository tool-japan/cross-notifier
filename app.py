from flask import Flask, render_template_string, request, redirect, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from functools import wraps
import os

# モデルとDBをインポート
from models import db, User

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "devkey")
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///users.db")
db.init_app(app)

login_manager = LoginManager(app)
limiter = Limiter(get_remote_address, app=app, default_limits=["200/day", "50/hour"])

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

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
@limiter.limit("5/minute")
def login():
    html = """
    <h1>ログインページ</h1>
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

@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    if request.method == "POST":
        current_user.email = request.form["email"]
        current_user.symbols = request.form["symbols"]
        current_user.notify_enabled = "notify_enabled" in request.form
        db.session.commit()
        return redirect("/dashboard")

    return render_template_string("""
        <h2>{{ user.username }}さんの通知設定</h2>
        <form method="POST">
            通知先メールアドレス：<input name="email" value="{{ user.email }}"><br>
            銘柄コード（改行で複数）：<br>
            <textarea name="symbols" rows="5" cols="30">{{ user.symbols }}</textarea><br>
            通知ON：<input type="checkbox" name="notify_enabled" {% if user.notify_enabled %}checked{% endif %}><br>
            <input type="submit" value="保存">
        </form>
        <p><a href='/logout'>ログアウト</a></p>
    """, user=current_user)

@app.route("/register", methods=["GET", "POST"])
# @admin_required  # 管理者のみ有効にしたい場合ここを有効に
def register():
    html = """
    <h1>新規ユーザー登録</h1>
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
        return redirect("/dashboard")
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
    if user.id == current_user.id:
        return "自分自身のアカウントは削除できません", 403
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

if __name__ == "__main__":
    app.run(debug=True)
