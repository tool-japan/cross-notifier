@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    if request.method == "POST":
        # 入力された銘柄を整形（空行削除・重複排除・空白除去）
        raw_symbols = request.form["symbols"]
        cleaned_symbols = []
        seen = set()
        for line in raw_symbols.splitlines():
            symbol = line.strip()
            if symbol and symbol not in seen:
                cleaned_symbols.append(symbol)
                seen.add(symbol)

        # ロールに応じて最大数を決定
        max_symbols = 10000 if current_user.role == "admin" else 100
        if len(cleaned_symbols) > max_symbols:
            return f"""
                <h2>⚠️ 銘柄数が上限を超えています（{len(cleaned_symbols)}件 / 上限: {max_symbols}件）</h2>
                <p><a href='/dashboard'>戻る</a></p>
            """

        # DBに保存（整形後の銘柄を保存）
        current_user.symbols = "\n".join(cleaned_symbols)
        current_user.email = request.form["email"]
        current_user.notify_enabled = "notify" in request.form
        db.session.commit()
        return redirect("/dashboard")

    # GETリクエスト時の表示
    html = f"""
    <h1>通知設定ダッシュボード</h1>
    <form method="POST">
        🔘 通知ON：<input type="checkbox" name="notify" {"checked" if current_user.notify_enabled else ""}><br><br>
        📈 銘柄リスト（1行1銘柄）：<br>
        <textarea name="symbols" rows="10" cols="30">{current_user.symbols or ""}</textarea><br><br>
        📩 通知先メールアドレス：<br>
        <input name="email" value="{current_user.email or ''}"><br><br>
        <input type="submit" value="保存">
    </form>
    <br>
    <a href="/mypage">← マイページに戻る</a>
    """
    return render_template_string(html)
