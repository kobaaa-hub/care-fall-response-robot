"""計測結果（care.db）を集計して、表（Markdown）とグラフ（PNG）を出す。

    python3 ~/ros2_ws/src/care_patrol/care_patrol/report.py              すべての巡回
    python3 ~/ros2_ws/src/care_patrol/care_patrol/report.py --since 7    run_id 7 以降だけ
出力: ~/ros2_ws/results/report/report.md と *.png
"""
import argparse
import os
import sqlite3
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from care_db import DB_PATH  # noqa: E402

LABELS = ["in_bed", "standing", "absent", "fall_suspected", "sitting", "eating", "uncertain"]
JP = {"in_bed": "臥床", "standing": "立位", "absent": "不在", "fall_suspected": "転倒疑い", "sitting": "座位",
      "eating": "食事中", "uncertain": "保留"}


def q(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def pct(a, b):
    return f"{100.0 * a / b:.0f}%" if b else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--since", type=int, default=0, help="この run_id 以降だけ集計")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    out_dir = os.path.join(os.path.dirname(os.path.realpath(args.db)), "report")
    os.makedirs(out_dir, exist_ok=True)

    # 入口（entry）での判定だけを対象にする（approach / recheck は初動対応用）。--no-vlm の巡回は除く
    rows = q(conn, """
        SELECT r.record_id, r.run_id, r.room, r.state, r.raw_state, r.confidence, r.seconds, r.tokens_in,
               e.truth, e.match, e.false_alarm, e.missed, u.lighting, u.n_images, u.scenario
        FROM records r JOIN evals e USING(record_id) JOIN runs u USING(run_id)
        WHERE r.state != 'skipped' AND r.run_id >= ? AND r.image_dir LIKE '%_entry'
        ORDER BY r.record_id""", (args.since,))
    if not rows:
        sys.exit("集計できる記録がありません（VLMありで巡回しましたか？）")

    md = ["# 計測結果", "", f"DB: `{args.db}`  対象レコード: {len(rows)}  "
          f"巡回数: {len({r['run_id'] for r in rows})}", ""]

    # --- A. 条件別の一致率 -------------------------------------------------------------
    md += ["## A. 条件別の一致率（H1・H2）", "", "| 条件 | 判定数 | 一致率 | 保留率 | 転倒の見逃し | 誤報 | 平均確信度 | 平均秒/判定 |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    order = {"day": 0, "night_lit": 1, "night": 2}
    conds = sorted({(r["lighting"], r["n_images"]) for r in rows}, key=lambda c: (order.get(c[0], 9), -c[1]))
    cond_stats = []
    for lt, n in conds:
        g = [r for r in rows if r["lighting"] == lt and r["n_images"] == n]
        m = sum(r["match"] for r in g); unc = sum(r["state"] == "uncertain" for r in g)
        miss = sum(r["missed"] for r in g); fa = sum(r["false_alarm"] for r in g)
        falls = sum(r["truth"] == "fall_suspected" for r in g)
        conf = statistics.mean(r["confidence"] for r in g); sec = statistics.mean(r["seconds"] for r in g)
        name = f"{ {'day': '昼', 'night': '夜', 'night_lit': '夜・常夜灯'}.get(lt, lt) }・{n}枚"
        cond_stats.append((name, 100.0 * m / len(g)))
        md.append(f"| {name} | {len(g)} | {pct(m, len(g))} | {pct(unc, len(g))} | {miss}/{falls} | {fa} | {conf:.2f} | {sec:.1f} |")

    # --- B. 場所別（屋内 vs 庭） ----------------------------------------------------------
    md += ["", "## B. 場所別の一致率", "", "| 場所 | 判定数 | 一致率 | 転倒の見逃し | 誤報 |", "| --- | --- | --- | --- | --- |"]
    for place, sel in (("居室（101〜104）", lambda r: r["room"] != "garden"), ("庭", lambda r: r["room"] == "garden")):
        g = [r for r in rows if sel(r)]
        if g:
            md.append(f"| {place} | {len(g)} | {pct(sum(r['match'] for r in g), len(g))} | "
                      f"{sum(r['missed'] for r in g)}/{sum(r['truth'] == 'fall_suspected' for r in g)} | {sum(r['false_alarm'] for r in g)} |")

    # --- C. 混同行列（昼・3枚） -------------------------------------------------------------
    base = [r for r in rows if r["lighting"] == "day" and r["n_images"] == 3] or rows
    labs = [l for l in LABELS if any(r["truth"] == l or r["state"] == l for r in base)]
    md += ["", f"## C. 混同行列（{'昼・3枚' if base is not rows else '全体'}。行=正解、列=判定）", "",
           "| 正解＼判定 | " + " | ".join(JP[l] for l in labs) + " |", "| --- |" + " --- |" * len(labs)]
    cm = {(t, s): 0 for t in labs for s in labs}
    for r in base:
        if r["truth"] in labs and r["state"] in labs:
            cm[(r["truth"], r["state"])] += 1
    for t in labs:
        if any(r["truth"] == t for r in base):
            md.append(f"| {JP[t]} | " + " | ".join(str(cm[(t, s)]) for s in labs) + " |")

    # --- D. 初動対応の時間（H3） ---------------------------------------------------------------
    inc = q(conn, "SELECT i.*, u.lighting FROM incidents i JOIN runs u USING(run_id) WHERE i.run_id >= ? AND i.t_confirm IS NOT NULL AND i.second_state != 'skipped'",
            (args.since,))
    md += ["", "## D. 初動対応の時間（H3）", ""]
    if inc:
        def med(vals):
            vals = [v for v in vals if v is not None]
            return f"{statistics.median(vals):.0f}" if vals else "-"
        md += ["| 場所 | 件数 | 確定率 | 検知→人のそば [秒] | 検知→通報 [秒] | 先導（出入口→現場）[秒] |", "| --- | --- | --- | --- | --- | --- |"]
        for place, sel in (("居室", lambda i: i["room"] != "garden"), ("庭", lambda i: i["room"] == "garden"), ("全体", lambda i: True)):
            g = [i for i in inc if sel(i)]
            if not g:
                continue
            conf = [i for i in g if i["confirmed"]]
            md.append(f"| {place} | {len(g)} | {pct(len(conf), len(g))} | "
                      f"{med([i['t_arrive_person'] - i['t_detect'] for i in g if i['t_arrive_person']])} | "
                      f"{med([i['t_alert'] - i['t_detect'] for i in conf if i['t_alert']])} | "
                      f"{med([i['t_escort_done'] - i['t_staff_arrived'] for i in conf if i['t_escort_done'] and i['t_staff_arrived']])} |")
        truths = [i for i in inc if i["truth"] == "fall_suspected"]
        wrong = [i for i in inc if i["truth"] != "fall_suspected"]
        md += ["", f"二段階確認: 本当の転倒 {len(truths)} 件のうち確定 {sum(i['confirmed'] for i in truths)} 件。"
                   f"転倒でないのに1回目で疑われたもの {len(wrong)} 件のうち、撮り直しで否定できたもの "
                   f"{sum(1 for i in wrong if not i['confirmed'])} 件（誤った駆けつけ {sum(i['confirmed'] for i in wrong)} 件）。"]
    else:
        md.append("初動対応の記録はまだありません。")

    # --- E. 費用 --------------------------------------------------------------------------------
    tok = q(conn, "SELECT SUM(tokens_in) ti, SUM(tokens_out) tout, COUNT(*) n FROM records WHERE state != 'skipped' AND run_id >= ?", (args.since,))[0]
    cost = (tok["ti"] or 0) / 1e6 * 2 + (tok["tout"] or 0) / 1e6 * 10
    md += ["", "## E. VLMの呼び出し", "", f"呼び出し {tok['n']} 回、入力 {tok['ti'] or 0:,} トークン、出力 {tok['tout'] or 0:,} トークン。"
           f"Sonnet 5.5 の単価で約 ${cost:.2f}。"]

    # --- グラフ -------------------------------------------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.family"] = ["Noto Sans CJK JP", "IPAGothic", "DejaVu Sans"]
        fig, ax = plt.subplots(figsize=(5, 3.2), dpi=150)
        names = [c[0] for c in cond_stats]; vals = [c[1] for c in cond_stats]
        bars = ax.bar(names, vals, color=["#2E7D6B" if "昼" in n else "#5FA08E" if "常夜灯" in n else "#8A9BA8" if "1枚" in n else "#6F8F9C" for n in names])
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 1.5, f"{v:.0f}%", ha="center", fontsize=9)
        ax.set_ylim(0, 105); ax.set_ylabel("正解との一致率 [%]"); ax.set_title("条件別の状態判定の一致率")
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout(); fig.savefig(os.path.join(out_dir, "accuracy_by_condition.png")); plt.close(fig)

        fig, ax = plt.subplots(figsize=(4.2, 3.6), dpi=150)
        mat = [[cm[(t, s)] for s in labs] for t in labs]
        ax.imshow(mat, cmap="Blues")
        ax.set_xticks(range(len(labs))); ax.set_xticklabels([JP[l] for l in labs], rotation=30, ha="right", fontsize=8)
        ax.set_yticks(range(len(labs))); ax.set_yticklabels([JP[l] for l in labs], fontsize=8)
        for i in range(len(labs)):
            for j in range(len(labs)):
                ax.text(j, i, mat[i][j], ha="center", va="center", fontsize=8, color="white" if mat[i][j] > max(map(max, mat)) / 2 else "black")
        ax.set_xlabel("VLMの判定"); ax.set_ylabel("正解"); ax.set_title("混同行列（昼・3枚）", fontsize=10)
        fig.tight_layout(); fig.savefig(os.path.join(out_dir, "confusion.png")); plt.close(fig)

        if inc:
            fig, ax = plt.subplots(figsize=(5.5, 2.8), dpi=150)
            ys, labels_ = [], []
            for k, i in enumerate([i for i in inc if i["confirmed"]][-8:]):
                t0 = i["t_detect"]
                segs = [("人のそば", i["t_arrive_person"]), ("通報", i["t_alert"]), ("先導完了", i["t_escort_done"])]
                ax.barh(k, (i["t_alert"] or t0) - t0, color="#C8473A", height=0.5)
                if i["t_escort_done"] and i["t_staff_arrived"]:
                    ax.barh(k, i["t_escort_done"] - i["t_staff_arrived"], left=(i["t_alert"] or t0) - t0, color="#2E7D6B", height=0.5)
                labels_.append(f"{i['room']}（{ {'day': '昼', 'night': '夜', 'night_lit': '夜・常夜灯'}.get(i['lighting'], i['lighting']) }）")
            ax.set_yticks(range(len(labels_))); ax.set_yticklabels(labels_, fontsize=8)
            ax.set_xlabel("検知からの秒数（赤: 確認〜通報、緑: 先導）"); ax.set_title("転倒検知から通報・先導までの時間", fontsize=10)
            ax.spines[["top", "right"]].set_visible(False)
            fig.tight_layout(); fig.savefig(os.path.join(out_dir, "incident_timeline.png")); plt.close(fig)
        md += ["", f"グラフ: `{out_dir}/accuracy_by_condition.png`, `confusion.png`, `incident_timeline.png`"]
    except Exception as e:  # matplotlib が無い・フォントが無いなど
        md += ["", f"（グラフは作れませんでした: {e}。`pip3 install matplotlib \"numpy<2\"` と "
                   "`sudo apt install -y fonts-noto-cjk` を試してください）"]

    text = "\n".join(md)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\n保存: {out_dir}/report.md")


if __name__ == "__main__":
    main()
