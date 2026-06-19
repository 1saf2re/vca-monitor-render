"""
VCA フリヴォル 在庫監視（Render常時起動版 / 連続通知スパム防止版 / キャッシュ対策URL版）
"""

import os
import time
import threading
import json
from datetime import datetime, timezone, timedelta
from flask import Flask
from curl_cffi import requests
import concurrent.futures
import random

# ── 設定 ──────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
CHECK_INTERVAL_SEC  = 20  # 20秒

TARGET_URLS = {
    # ── スモールモデル ──────────────────────────
    "フリヴォル スモール PG": "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarpfbk00---frivole-earrings-small-model.html",
    "フリヴォル スモール YG": "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarb65700---frivole-earrings-small-model.html",
    "フリヴォル スモール WG": "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcard80200---frivole-earrings-small-model.html",
    
    # ── ミニ・ラージモデル ──────────────────────
    "フリヴォル ミニ YG": "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarpjmn00---frivole-earrings-mini-model.html",
    "フリヴォル ラージ YG": "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarb65900---frivole-earrings-large-model.html",
    "フリヴォル ミニ WG": "https://www.vancleefarpels.com/jp/ja/collections/jewelry/flora/frivole/vcarpjmo00---frivole-earrings-mini-model.html",
}

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
        "Accept": "text/html,application/json,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

JST = timezone(timedelta(hours=9))

# ── 状態管理 ───────────────────────────────────────
start_time  = datetime.now(JST)
check_count = 0
last_check  = "未実行"

# 各アイテムの前回の在庫状態を記憶する辞書（初期値はすべてFalse）
previous_stock_state = {name: False for name in TARGET_URLS.keys()}

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
    json_url = url.replace(".html", ".productinfo.JP.json")
    timestamp = int(time.time() * 1000)
    nocache_url = f"{json_url}?_={timestamp}"
    
    try:
        r = requests.get(nocache_url, headers=get_headers(), impersonate="chrome", timeout=10)
        r.raise_for_status()
        
        try:
            data = r.json()
        except json.JSONDecodeError:
            print("  [警告] " + name + ": URLが無効か、ページが存在しません（HTML応答）")
            return False

        if not data:
            return False

        product_info = list(data.values())[0]
        sellable = product_info.get("sellable", False)
        stock    = product_info.get("stock",    False)
        
        return sellable and stock
        
    except Exception as e:
        print("[通信エラー] " + name + ": " + str(e))
        return False

# ── 監視ループ ─────────────────────────────────────
def monitor_loop():
    global check_count, last_check, previous_stock_state
    send_discord("[VCA監視Bot] 起動しました。" + str(CHECK_INTERVAL_SEC) + "秒ごとに監視を開始します。")
    
    while True:
        try:
            now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
            check_count += 1
            last_check   = now
            print("\n[" + now + "] 第" + str(check_count) + "回チェック")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(TARGET_URLS)) as executor:
                future_to_url = {executor.submit(check, name, url): name for name, url in TARGET_URLS.items()}
                
                for future in concurrent.futures.as_completed(future_to_url):
                    name = future_to_url[future]
                    try:
                        available = future.result()
                        
                        was_available_last_time = previous_stock_state[name]
                        
                        if available:
                            if not was_available_last_time:
                                # 前回Falseで今回Trueなら新規入荷として通知
                                print(f"  [新規入荷！] {name}")
                                
                                # 【キャッシュ対策】URLの末尾に現在のタイムスタンプを強制付与
                                timestamp_sec = int(time.time())
                                nocache_url = f"{TARGET_URLS[name]}?t={timestamp_sec}"
                                
                                send_discord(f"[VCA在庫出現！] {name} が購入可能な状態です！(※ゴースト在庫の可能性あり) \n{nocache_url} \n検知時刻: {now}")
                            else:
                                # 前回もTrueなら継続中として通知はスキップ（ログだけ出す）
                                print(f"  [継続] 在庫あり維持（通知スキップ）: {name}")
                        else:
                            print(f"  [在庫なし] {name}")
                        
                        # 今回の取得結果を「次回の前回値」として記憶
                        previous_stock_state[name] = available

                    except Exception as e:
                        print("[個別エラー] " + name + ": " + str(e))
        except Exception as e:
            print("[ループエラー] " + str(e))
        
        time.sleep(CHECK_INTERVAL_SEC)

# ── gunicorn対応 ───────────────────────────────────
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
