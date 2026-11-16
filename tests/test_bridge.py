"""第5回 宿題（発展）の search_bridge を、同梱の資料と検索DBで確かめる。APIは呼ばない。"""

import json

from app import retrieval
from app.config import BRIDGE_MAX_RESULTS, RAG_GRAPH


def stored_vector(page_id):
    """検索DBに入っているページの埋め込みを、質問の埋め込みの代わりに使う。"""
    with retrieval.open_index(retrieval.RAG_DB) as db:
        blob = db.execute("SELECT embedding FROM chunks WHERE page_id = ?", (page_id,)).fetchone()[0]
    return list(memoryview(blob).cast("f"))


def test_lecture_references_and_terms():
    pages = {page["page_id"]: page for page in retrieval.load_pages()}
    assert retrieval.lecture_references(pages["lec03-main-p003"]) == {2}
    assert retrieval.lecture_references(pages["lec02-main-p062"]) == {3}  # 「次回：」は次の回を参照
    graph = json.loads(RAG_GRAPH.read_text(encoding="utf-8"))
    ids = [term["id"] for term in retrieval.find_terms("FTとメモリの違い", graph)]
    assert ids == ["term:fine-tuning", "term:memory"]
    assert retrieval.find_terms("AFTER SHIFT", graph) == []  # 英字の短い別名は単語の一部に当てない


def test_bridge_keeps_vector_hits_and_covers_named_lectures(monkeypatch):
    vector = stored_vector("lec02-main-p015")
    monkeypatch.setattr(retrieval, "embed_text", lambda *_: vector)
    plain = [hit["page_id"] for hit in retrieval.search("第2回と第3回")]
    result = retrieval.search_bridge("第2回と第3回")
    ids = [page["page_id"] for page in result["pages"]]
    assert set(plain) <= set(ids)  # 通常のベクトル検索の5件は必ず含む
    assert {2, 3} <= set(result["lectures"])
    assert {page["lecture"] for page in result["pages"]} >= {2, 3}
    assert len(ids) <= BRIDGE_MAX_RESULTS
    assert all(page["reasons"] for page in result["pages"])
