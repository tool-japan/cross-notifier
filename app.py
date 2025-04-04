from flask import Flask, render_template_string, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from cryptography.fernet import Fernet
import os, secrets
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default_secret_key")
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///users.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)

ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", Fernet.generate_key())
fernet = Fernet(ENCRYPTION_KEY)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    symbols = db.Column(db.Text, nullable=False)
    smtp_email = db.Column(db.String(255), nullable=False)
    smtp_password = db.Column(db.Text, nullable=False)
    notify_enabled = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(10), default='user')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route("/register", methods=["GET", "POST"])
@login_required
def register():
    html = """<form method='POST'>
        <label>通知ON/OFF</label>
        <select name='notify_enabled'>
            <option value='true'>通知する</option>
            <option value='false'>通知しない</option>
        </select><br>
        <label>銘柄リスト（1行に1銘柄）</label><br>
        <textarea name='symbols' rows='10' cols='30'></textarea><br>
        <label>通知先メールアドレス</label><input type='email' name='email'><br>
        <label>送信用Gmailアドレス</label><input type='email' name='smtp_email'><br>
        <label>アプリパスワード</label><input type='password' name='smtp_password'><br>
        <input type='submit'>
    </form>"""
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

@app.route("/login", methods=["GET", "POST"])
def login():
    html = """<form method='POST'>
        <input name='username'><br>
        <input name='password' type='password'><br>
        <input type='submit'>
    </form>"""
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and check_password_hash(user.password_hash, request.form["password"]):
            login_user(user)
            return redirect(url_for("register"))
    return render_template_string(html)

@app.route("/logout")
def logout():
    logout_user()
    return redirect("/login")

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))  # Renderが使うPORT環境変数を取得
    app.run(host="0.0.0.0", port=port)
