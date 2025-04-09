from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    role = db.Column(db.String(10), default="user")
    email = db.Column(db.String(255), nullable=True)
    symbols = db.Column(db.Text, nullable=True)
    notify_enabled = db.Column(db.Boolean, default=True)
