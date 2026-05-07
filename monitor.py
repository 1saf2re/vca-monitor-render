"""
VCA フリヴォル 在庫監視（Render常時起動版）
- Flaskで最小限のWebサーバーを立ち上げ、Renderに「生きてる」と伝える
- バックグラウンドスレッドで2分ごとにVCAサイトを監視
- 在庫検知→Discord Webhook通知
"""

import os
import time
import threading
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from flask import Flask

# ── 設定 ──────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
CHECK_INTERVAL_SEC  = 1 * 60  # 1分

TARGET_URLS = {
    "フリヴォル スモール YG": "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarb65700---frivole-earrings-small-model.html",
    "フリヴォル スモール WG": "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcard80200---frivole-earrings-small-model.html",
    "フリヴォル スモール RG": "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarb65r00---frivole-earrings-small-model.html",
    "フリヴォル ミニ YG":    "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarp24200---frivole-earrings-mini-model.html",
    "フリヴォル ミニ WG":    "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarp0j600---frivole-earrings-mini-model.html",
    "フリヴォル ミニ RG":    "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarp7rj00---frivole-earrings-mini-model.html",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

JST = timezone(timedelta(hours=9))

# ── Flask アプリ ───────────────────────────────────
app = Flask(__name__)
start_time = datetime.now(JST)
check_count = 0
last_check  = "未実行"

@app.route("/test")
def test_notification():
    """ブラウザからアクセスするだけでDiscordにテスト通知を送る"""
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    send_discord("[VCA監視テスト] 通知の動作確認です。このメッセージが届いていれば完璧です！ 確認時刻: " + now)
    return "<h2>テスト通知を送信しました</h2><p>Discordを確認してください。</p><p><a href='/'>ステータスページに戻る</a></p>"

@app.route("/")
def index():
    """Renderのヘルスチェック兼ステータス確認ページ"""
    uptime = str(datetime.now(JST) - start_time).split(".")[0]
    return (
        f"<h2>VCA在庫監視Bot 稼働中</h2>"
        f"<p>起動時刻: {start_time.strftime('%Y-%m-%d %H:%M JST')}</p>"
        f"<p>稼働時間: {uptime}</p>"
        f"<p>チェック回数: {check_count}回</p>"
        f"<p>最終チェック: {last_check}</p>"
        f"<p>監視間隔: {CHECK_INTERVAL_SEC}秒</p>"
        f"<p>監視対象: {list(TARGET_URLS.keys())}</p>"
    )

# ── 通知 ──────────────────────────────────────────
def send_discord(message: str) -> None:
    if not DISCORD_WEBHOOK_URL:
        print("[Discord未設定]", message)
        return
    try:
        r = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": message},
            timeout=10,
        )
        print(f"[Discord送信] status={r.status_code}")
    except Exception as e:
        print(f"[Discordエラー] {e}")

# ── 在庫チェック ───────────────────────────────────
def check(name: str, url: str) -> bool:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text()

        buy_signals = ["カートに入れる", "Add to bag", "カートへ", "購入する", "add to bag"]
        if any(s.lower() in text.lower() for s in buy_signals):
            return True
        if soup.find(attrs={"data-action": "add-to-cart"}):
            return True
        if soup.find(attrs={"class": lambda c: c and "add-to-cart" in " ".join(c)}):
            return True
        return False
    except Exception as e:
        print(f"[チェックエラー] {name}: {e}")
        return False

# ── 監視ループ（バックグラウンドスレッド）──────────────
def monitor_loop():
    global check_count, last_check

    # 起動通知
    send_discord("[VCA監視Bot] 起動しました。2分ごとに監視を開始します。 起動時刻: " + datetime.now(JST).strftime("%Y-%m-%d %H:%M JST"))

    while True:
        now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
        check_count += 1
        last_check   = now
        print(f"\n[{now}] 第{check_count}回チェック")

        for name, url in TARGET_URLS.items():
            available = check(name, url)
            print(f"  {'在庫あり！' if available else '在庫なし'} {name}")

            if available:
                msg = (
                    "[VCA在庫出現！] " + name +
                    " が購入できます！ " + url +
                    " 検知時刻: " + now
                )
                send_discord(msg)

        time.sleep(CHECK_INTERVAL_SEC)

# ── エントリーポイント ─────────────────────────────
if __name__ == "__main__":
    # 監視スレッドをバックグラウンドで起動
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()

    # FlaskサーバーをRenderが指定するポートで起動
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
