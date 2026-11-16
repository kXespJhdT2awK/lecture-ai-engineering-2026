"""第5回 宿題: 各取得方式が返すページに、答えを支えるページが入るかを数える（回答生成はしない）。

使い方: PYTHONPATH=. uv run python lectures/05/recall_check.py vec|graph|bridge
質問の埋め込みは qvec.pkl に保存し、方式間で同じベクトルを使う（このファイルはcommitしない）。
"""
import json, pickle, sys
from pathlib import Path
from app import retrieval as r

CACHE = Path(__file__).with_name("qvec.pkl")
cache = pickle.loads(CACHE.read_bytes()) if CACHE.exists() else {}
orig_embed = r.embed_text


def cached_embed(text, task):
    if text not in cache:
        cache[text] = orig_embed(text, task)
        CACHE.write_bytes(pickle.dumps(cache))
    return cache[text]


r.embed_text = cached_embed

CASES = {
    "QB": ({"lec02-main-p015", "lec03-main-p003"}, [
        "第2回で説明された「長い文脈を均等には使えない」という性質について、第2回ではどんな実験結果と対策が示されていますか。また第3回のエージェント設計では、この性質がどの仕組みで扱われていますか",
        "長い文脈 限界 エージェント",
        "長い文脈を均等に使えない エージェント 設計",
        "第2回 長い文脈 実験結果 対策",
        "第3回 エージェント 長い文脈 メモリ",
        "長い文脈を均等には使えない",
    ]),
    "QA": ({"lec02-main-p046", "lec03-main-p013"}, [
        "第2回のファインチューニングと第3回のエージェントのメモリは、どちらも「覚えさせる」方法に見えます。両者は何が違いますか。新しい知識や資料の内容を使わせたいときは、講義ではどうすると説明されていますか",
        "ファインチューニングとメモリの違い",
        "ファインチューニング メモリ 新しい知識",
        "メモリ 学習 違い 知識の追加",
    ]),
    "QE": ({"lec03-main-p013", "lec03-main-p039", "lec03-main-p040"}, [
        "第3回の例では、コンパクションとセッションをまたぐメモリはどう違いますか。日々のメモはすべて長期メモリに入りますか",
        "コンパクション セッション メモリ 違い",
        "日々のメモ 長期メモリ",
    ]),
}

method = sys.argv[1]
fn = {"vec": lambda q: r.search(q), "graph": lambda q: (lambda g: g["seeds"] + g["expanded"])(r.search_graph(q))}
if method == "bridge":
    fn["bridge"] = lambda q: r.search_bridge(q)["pages"]
total = hit = 0
for name, (gold, queries) in CASES.items():
    for q in queries:
        ids = [p["page_id"] for p in fn[method](q)]
        got = gold & set(ids)
        total += len(gold); hit += len(got)
        print(f"{name} {len(got)}/{len(gold)} n={len(ids):2d} {q[:30]} missing={sorted(gold - got)}")
print(f"{method}: recall {hit}/{total}")
