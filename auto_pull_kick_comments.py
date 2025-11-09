import subprocess
import os
import shutil
from datetime import datetime
from pathlib import Path
import time

# === 設定 ===
REPO_PATH = Path(__file__).resolve().parent  # スクリプトが置かれているリポジトリのパス
BRANCH = "main"                              # デフォルトブランチ名
SRC_DIR = REPO_PATH / "comments_github"      # GitHub側コメント保存先
DST_DIR = REPO_PATH / "comments_local"       # ローカル保存先
LOG_FILE = REPO_PATH / "auto_pull_log.txt"   # ログ出力用ファイル

# === ログ出力関数 ===
def log(msg: str):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} {msg}\n")
    print(msg)

# === GitHubからpull ===
def pull_repo():
    try:
        log("📡 GitHubから最新データを取得中...")
        subprocess.run(["git", "-C", str(REPO_PATH), "pull", "origin", BRANCH, "--rebase"], check=True)
        log("✅ リポジトリの更新が完了しました。")
    except subprocess.CalledProcessError as e:
        log(f"❌ git pullに失敗しました: {e}")
        raise

# === コメントJSONをコピー ===
def sync_comments():
    if not SRC_DIR.exists():
        log("⚠️ comments_github フォルダが見つかりません。")
        return

    DST_DIR.mkdir(exist_ok=True)
    copied_files = 0

    for file in SRC_DIR.glob("*_comments.json"):
        dst = DST_DIR / file.name
        # ファイルが存在しない、または更新日時が新しければコピー
        if not dst.exists() or file.stat().st_mtime > dst.stat().st_mtime:
            shutil.copy2(file, dst)
            copied_files += 1
            log(f"📁 {file.name} を comments_local にコピーしました。")

    if copied_files == 0:
        log("🟢 新しいコメントファイルはありません。")
    else:
        log(f"✅ {copied_files} 件のコメントファイルをコピーしました。")

# === 実行 ===
def main():
    log("🚀 自動コメント同期スクリプト開始")
    try:
        pull_repo()
        sync_comments()
        log("✨ 同期処理が完了しました。")
    except Exception as e:
        log(f"⚠️ エラー発生: {e}")
    log("----\n")

if __name__ == "__main__":
    main()
    time.sleep(5)
