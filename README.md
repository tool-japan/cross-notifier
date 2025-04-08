# 📈 Cross Notifier（クロス検出通知ツール）

> 自動でゴールデンクロス・デッドクロスを検出して、メールで通知！  
> 日本株・米国株対応、マルチユーザー、管理者銘柄共有機能も搭載！

---

## 🔧 概要

**Cross Notifier** は、株式のテクニカル指標である **移動平均線のクロス（EMA9とEMA20）** を使い、  
**ゴールデンクロス**・**デッドクロス**の発生を自動で検出してメールで通知する**Webアプリ**です。

### 特徴：
- 📨 **クロス発生をリアルタイムで通知**
- 👤 **ユーザーごとの銘柄管理**
- 🧑‍💼 **管理者が設定した銘柄は全ユーザーに共有**
- 🔁 **20分以内の重複通知はスキップ**
- 🕘 **日本・米国市場の取引時間を自動判定**
- 📬 **Amazon SESによる高速メール配信**

---

## 🌐 使用技術

| 分類         | 内容                                     |
|--------------|------------------------------------------|
| バックエンド | Python / Flask / SQLAlchemy              |
| フロント     | Flaskテンプレート（HTML）               |
| データベース | PostgreSQL（Renderホスティング）        |
| メール通知   | Amazon SES                               |
| データ取得   | yfinance（Yahoo! Finance API）           |
| サーバー     | Render（無料/有料プラン）                |

---

## 🧪 機能詳細

### 🔍 クロス検出ロジック
- EMA9とEMA20の乖離をチェック
- クロス発生時に通知（ゴールデン/デッドクロス）

### 👥 ユーザー管理
- ログイン / 登録（管理者による）
- ダッシュボードで銘柄・通知設定可能

### 🔔 通知履歴管理
- 通知内容はDBに記録（`NotificationHistory`）
- 同一内容の通知は**20分以内はスキップ**

### 🧠 管理者機能
- 他ユーザーの管理・削除・パスワード変更
- 管理者が登録した銘柄は全ユーザーに適用

### 🌏 対応市場
- 日本株：平日 9:00〜15:00（祝日除外）
- 米国株：平日 22:30〜翌 5:00（日本時間）

---

## 📦 セットアップ方法

### 1. 環境変数（`.env`）
DATABASE_URL=postgresql://xxx:xxx@xxx:5432/xxx
FLASK_SECRET_KEY=your_flask_secret ENCRYPTION_KEY=your_fernet_key SES_SMTP_USER=your_smtp_user
SES_SMTP_PASSWORD=your_smtp_pass SES_FROM_EMAIL=verified@yourdomain.com

### 2. 初回DBセットアップ（必要なとき）
```python
with app.app_context():
    db.drop_all()
    db.create_all()

