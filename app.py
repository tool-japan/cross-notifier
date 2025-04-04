from flask import Flask, render_template_string, request, redirect, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "devkey")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'

# DB & Login
db = SQLAlchemy(app)
login_manager = LoginManager(app)

# Flask-Limiter（ログイン制限）
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"])

# User Model
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(10), default="user")  # "admin" or "user"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# 管理者専用アクセス用デコレーター
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
    <p><a href='/login'>ログイン</a></p>
    """

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")  # ログイン試行制限
def login():
    html = """
    <h1>ログイン</h1>
    <form method='POST'>
        ユーザー名：<input name='username'><br>
        パスワード：<input name='password' type='password'><br>
        <input type='submit' value='ログイン'>
    </form>
    """
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and check_password_hash(user.password_hash, request.form["password"]):
            login_user(user)
            return redirect("/mypage")
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
@admin_required
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

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
