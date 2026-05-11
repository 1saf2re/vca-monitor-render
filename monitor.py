"""
VCA フリヴォル 在庫監視（Render常時起動版）
gunicorn対応：スレッドをモジュールロード時に起動
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
CHECK_INTERVAL_SEC  = 60  # 1分

TARGET_URLS = {
    "フリヴォル スモール YG": "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarb65700---frivole-earrings-small-model.html",
    "フリヴォル スモール WG": "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcard80200---frivole-earrings-small-model.html",
    "フリヴォル スモール RG": "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarb65r00---frivole-earrings-small-model.html",
    "フリヴォル ミニ YG":    "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarpjmn00---frivole-earrings-mini-model.html",
    "フリヴォル ミニ WG":    "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarpjmo00---frivole-earrings-mini-model.html",
    "フリヴォル ミニ RG":    "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarp7rj00---frivole-earrings-mini-model.html",
}

import random

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "ja-JP,ja;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

JST = timezone(timedelta(hours=9))

# ── 状態管理 ───────────────────────────────────────
start_time  = datetime.now(JST)
check_count = 0
last_check  = "未実行"

# ── Flask ─────────────────────────────────────────
app = Flask(__name__)

@app.route("/")
def index():
    uptime = str(datetime.now(JST) - start_time).split(".")[0]
    return (
        "<h2>VCA在庫監視Bot 稼働中</h2>"
        "<p>起動時刻: " + start_time.strftime("%Y-%m-%d %H:%M JST") + "</p>"
        "<p>稼働時間: " + uptime + "</p>"
        "<p>チェック回数: " + str(check_count) + "回</p>"
        "<p>最終チェック: " + last_check + "</p>"
        "<p>監視間隔: " + str(CHECK_INTERVAL_SEC) + "秒</p>"
        "<p><a href='/test'>通知テストを送る</a></p>"
    )

@app.route("/test")
def test_notification():
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    send_discord("[VCA監視テスト] 通知の動作確認です。このメッセージが届いていれば完璧です！ 確認時刻: " + now)
    return "<h2>テスト通知を送信しました</h2><p>Discordを確認してください。</p><a href='/'>戻る</a>"

# ── 通知 ──────────────────────────────────────────
MENTION = "<@835744502672654369>"

def send_discord(message):
    if not DISCORD_WEBHOOK_URL:
        print("[Discord未設定] " + message)
        return
    try:
        r = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": MENTION + " " + message},
            timeout=10,
        )
        print("[Discord送信] status=" + str(r.status_code))
    except Exception as e:
        print("[Discordエラー] " + str(e))

# ── 在庫チェック ───────────────────────────────────
def check(name, url):
    try:
        r = requests.get(url, headers=get_headers(), timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text()
        buy_signals = ["ショッピングバッグに入れる", "ショッピングバッグに追加", "バッグに入れる", "カートに入れる", "Add to bag", "add to bag", "カートへ", "購入する", "add to shopping bag"]
        if any(s.lower() in text.lower() for s in buy_signals):
            return True
        if soup.find(attrs={"data-action": "add-to-cart"}):
            return True
        if soup.find(attrs={"class": lambda c: c and "add-to-cart" in " ".join(c)}):
            return True
        return False
    except Exception as e:
        print("[チェックエラー] " + name + ": " + str(e))
        return False

# ── 監視ループ ─────────────────────────────────────
def monitor_loop():
    global check_count, last_check
    send_discord("[VCA監視Bot] 起動しました。" + str(CHECK_INTERVAL_SEC) + "秒ごとに監視を開始します。 起動時刻: " + start_time.strftime("%Y-%m-%d %H:%M JST"))
    while True:
        try:
            now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
            check_count += 1
            last_check   = now
            print("\n[" + now + "] 第" + str(check_count) + "回チェック")
            for name, url in TARGET_URLS.items():
                try:
                    available = check(name, url)
                    print("  " + ("在庫あり！ " if available else "在庫なし  ") + name)
                    if available:
                        send_discord("[VCA在庫出現！] " + name + " が購入できます！ " + url + " 検知時刻: " + now)
                except Exception as e:
                    print("[個別エラー] " + name + ": " + str(e))
        except Exception as e:
            print("[ループエラー] " + str(e))
        time.sleep(CHECK_INTERVAL_SEC)

# ── gunicorn対応：最初のリクエスト後にスレッド起動 ────
# gunicornはfork後にworkerを起動するため
# モジュールロード時に起動したスレッドはforkで死ぬ
# 最初のHTTPリクエストが来た時点で起動することで確実に動く
_monitor_started = False
_monitor_lock    = threading.Lock()

@app.before_request
def ensure_monitor_running():
    global _monitor_started
    with _monitor_lock:
        if not _monitor_started:
            _monitor_started = True
            t = threading.Thread(target=monitor_loop, daemon=True)
            t.start()
            print("[起動] 監視スレッドをリクエスト受信後に起動しました")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
