# 株式クロス検出ツール

Flask + PostgreSQL で動作するツールです。

## 機能
- ユーザーごとに銘柄・通知先・Gmail設定を登録
- 5分ごとに EMA9/20 のクロスを検出してメール通知

## 起動方法

```bash
pip install -r requirements.txt
python app.py  # 初期登録画面
python run_bot.py  # 自動通知実行
```
