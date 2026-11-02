"""承認画面の代わりにターミナルから職員の指示を出す（ブラウザが使えないとき用）。

    python3 staff_cli.py              通報の一覧
    python3 staff_cli.py go           一番新しい通報に「向かう」
    python3 staff_cli.py speak        「声かけ」
    python3 staff_cli.py approach     「近づいて再確認」
    python3 staff_cli.py dismiss      「誤報として閉じる」
    python3 staff_cli.py arrived      「出入口に到着した」（先導を始める）
    python3 staff_cli.py correct <record_id> <state> [メモ]   記録を修正する
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from care_db import CareDB, DB_PATH  # noqa: E402

db = CareDB(DB_PATH)
args = sys.argv[1:]
if not args:
    for a in db.conn.execute("SELECT * FROM alerts ORDER BY alert_id DESC LIMIT 5"):
        print(dict(a))
elif args[0] in ("go", "speak", "approach", "dismiss", "arrived"):
    row = db.conn.execute("SELECT alert_id FROM alerts ORDER BY alert_id DESC LIMIT 1").fetchone()
    if not row:
        sys.exit("通報がありません")
    db.set_staff_action(row["alert_id"], args[0])
    print(f"alert {row['alert_id']} に {args[0]} を指示しました")
elif args[0] == "correct" and len(args) >= 3:
    db.add_correction(int(args[1]), args[2], " ".join(args[3:]))
    print("修正を保存しました")
else:
    print(__doc__)
