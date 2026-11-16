"""第5回: ページ単位のベクトル検索。"""

import argparse
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from collections import defaultdict, deque
from pathlib import Path

from google import genai
from google.genai import types
from pydantic_ai.exceptions import ModelHTTPError
import sqlite_vec

from app.config import (
    EMBEDDING_DIMENSIONS, EMBEDDING_MAX_TOKENS, EMBEDDING_MODEL,
    RAG_DB, RAG_DOCUMENT_IDS, RAG_SOURCE, RAG_TOP_K, RAG_TREE, get_api_key,
    RAG_GRAPH, GRAPH_START_K, GRAPH_HOPS, GRAPH_MAX_RESULTS,
    BRIDGE_TOP_K, BRIDGE_PER_LECTURE, BRIDGE_LECTURE_MARGIN, BRIDGE_LINKS,
    BRIDGE_MAX_TERMS, BRIDGE_MAX_RESULTS,
)


def get_all_materials() -> str:
    """全資料を、講義・章・ページの情報付きで1つの文字列にまとめる。"""
    documents = json.loads(RAG_SOURCE.read_text(encoding="utf-8"))
    return "\n\n".join(
        f"資料: {document['id']} / {document['title']}\n"
        f"章: {section['section']}\n"
        f"ページ: PDF p.{page['page']} / {page['title']}\n{page['content']}"
        for document in documents
        for section in document["content"]
        for page in section["content"]
    )

def load_pages(source: Path = RAG_SOURCE) -> list[dict]:
    """資料→章→ページのJSONを、対象資料のページ一覧に変換する。"""
    documents = json.loads(source.read_text(encoding="utf-8"))
    pages = []
    for document in documents:
        if document["id"] not in RAG_DOCUMENT_IDS:
            continue
        for section in document["content"]:
            for page in section["content"]:
                pages.append({"page_id": page["id"], "document_id": document["id"],
                              "lecture": int(document["id"][3:5]), "document_title": document["title"],
                              "section": section["section"], "title": page["title"],
                              "page": page["page"], "content": page["content"]})
    return pages


def browse_tree(node_id: str | None = None) -> dict:
    """直下のページは先頭文、指定したページ自身は全文を返す。"""
    tree = json.loads(RAG_TREE.read_text(encoding="utf-8"))
    tree["children"] = [node for node in tree["children"] if node["id"] in RAG_DOCUMENT_IDS]
    node_id = node_id or tree["id"]
    pages = {page["page_id"]: page for page in load_pages(RAG_SOURCE)}

    def describe(node, full=False):
        info = {key: node[key] for key in ("id", "kind", "title")}
        if node["kind"] == "page":
            info.update({key: value for key, value in pages[node["id"]].items() if key != "page_id"})
            if not full:
                info["content"] = re.split(r"(?<=[。！？])|\n", info["content"].strip(), maxsplit=1)[0]
        return info

    remaining = [tree]
    while remaining:
        node = remaining.pop()
        if node["id"] == node_id:
            return {
                "node": describe(node, full=True),
                "children": [describe(child) for child in node.get("children", [])],
            }
        remaining.extend(node.get("children", []))
    raise ValueError("対象の目次ノードが見つかりません。")


def read_page(page_id: str) -> dict:
    """第1〜3回の本講義から、指定した1ページの本文と引用情報を返す。"""
    for page in load_pages(RAG_SOURCE):
        if page["page_id"] == page_id:
            return page
    raise ValueError("対象のページが見つかりません。")


def normalized_vector(values: list[float]) -> list[float]:
    """ベクトルの長さを1に揃える。"""
    norm = math.hypot(*values)
    if norm == 0:
        raise ValueError("埋め込みがゼロベクトルです。")
    return [value / norm for value in values]


def embed_text(text: str, task_type: str) -> list[float]:
    """Geminiで文章を埋め込む。入力上限を超えた場合は切り捨てず停止する。"""
    with genai.Client(api_key=get_api_key()) as client:
        count = client.models.count_tokens(model=EMBEDDING_MODEL, contents=text).total_tokens
        if count is None or count > EMBEDDING_MAX_TOKENS:
            raise ValueError(f"埋め込み入力が上限を超えるか計測不能です: {count} tokens。")
        response = client.models.embed_content(
            model=EMBEDDING_MODEL, contents=text,
            config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=EMBEDDING_DIMENSIONS),
        )
    embedding = response.embeddings[0]
    if embedding.statistics and embedding.statistics.truncated:
        raise ValueError("埋め込みAPIが本文を切り捨てました。")
    return normalized_vector(embedding.values)


@contextmanager
def open_index(path: Path):
    """既存の検索DBを読み取り専用で開き、終了時に閉じる。"""
    if not path.is_file():
        raise FileNotFoundError("検索DBがありません。")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        db.row_factory = sqlite3.Row
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        yield db
    finally:
        db.close()


def search(query: str) -> list[dict]:
    """質問を埋め込み、近いページを最大RAG_TOP_K件返す。"""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("検索語が空です。")
    with open_index(RAG_DB) as db:
        vector = embed_text(query.strip(), "RETRIEVAL_QUERY")
        rows = db.execute("""
            SELECT page_id, document_id, lecture, document_title, section, title, page, content,
                   vec_distance_cosine(embedding, ?) AS distance
            FROM chunks ORDER BY distance, page_id LIMIT ?
        """, (sqlite_vec.serialize_float32(vector), RAG_TOP_K))
        return [dict(row) for row in rows]


def search_graph(query: str) -> dict:
    """ベクトル検索を入口に、前後ページと共通用語で候補を広げる。"""
    pages = {page["page_id"]: page for page in load_pages(RAG_SOURCE)}
    graph = json.loads(RAG_GRAPH.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in graph["nodes"]
             if node["kind"] == "term" or node["id"] in pages}
    adjacent = defaultdict(set)
    for edge in graph["edges"]:
        a, b = edge["source"], edge["target"]
        if edge["relation"] in ("next_page", "mentions") and a in nodes and b in nodes:
            adjacent[a].add(b)
            adjacent[b].add(a)

    seeds = [hit for hit in search(query) if hit["page_id"] in pages][:min(GRAPH_START_K, GRAPH_MAX_RESULTS)]
    seed_ids = {seed["page_id"] for seed in seeds}
    results, candidates = [], {}
    for rank, seed in enumerate(seeds):
        root = seed["page_id"]
        results.append({**pages[root], "distance": seed["distance"], "hops": 0,
                        "path": [{"id": root, "title": pages[root]["title"]}]})
        queue = deque([(root, [root])])
        visited = {root}
        while queue:
            current, path = queue.popleft()
            if len(path) - 1 >= GRAPH_HOPS:
                continue
            # 同じ深さなら、接続先が少ない用語からたどる。
            neighbors = sorted(adjacent[current], key=lambda n: (len(adjacent[n]), n))
            for neighbor in neighbors:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                route = path + [neighbor]
                queue.append((neighbor, route))
                if neighbor not in pages or neighbor in seed_ids:
                    continue
                frequency = max((len(adjacent[n]) for n in route if nodes[n]["kind"] == "term"), default=0)
                priority = (len(route) - 1, frequency, rank, neighbor)
                candidate = {**pages[neighbor], "hops": len(route) - 1,
                             "path": [{"id": n, "title": nodes[n]["title"]} for n in route]}
                if neighbor not in candidates or priority < candidates[neighbor][0]:
                    candidates[neighbor] = (priority, candidate)
    expanded = [candidate for _, candidate in sorted(candidates.values())]
    return {"seeds": results, "expanded": expanded[:max(0, GRAPH_MAX_RESULTS - len(results))],
            "max_hops": GRAPH_HOPS}


LECTURE_REF = re.compile(r"第\s*(\d+)\s*回")


def lecture_references(page: dict) -> set[int]:
    """ページ本文が「第N回」で参照している、対象範囲内の別の講義番号。"""
    in_scope = {int(document_id[3:5]) for document_id in RAG_DOCUMENT_IDS}
    refs = {int(n) for n in LECTURE_REF.findall(page["content"])}
    if page["title"].startswith("次回"):
        refs.add(page["lecture"] + 1)
    return (refs - {page["lecture"]}) & in_scope


def find_terms(query: str, graph: dict) -> list[dict]:
    """質問に別名が含まれる用語ノードを返す。英字の短い別名（FT・PRなど）は単語単位で照合する。"""
    found = []
    for node in graph["nodes"]:
        if node["kind"] != "term":
            continue
        for alias in node.get("aliases", []) + [node["title"]]:
            if len(alias) < 2:
                continue
            if re.fullmatch(r"[A-Za-z]{2,3}", alias):
                hit = re.search(rf"(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z])", query)
            else:
                hit = alias.casefold() in query.casefold()
            if hit:
                found.append(node)
                break
    return found


def search_bridge(query: str) -> dict:
    """講義をまたぐ質問向けの取得。目次の講義単位で候補を分け、講義間の参照と用語でつなぐ。

    1. 質問を1回だけ埋め込み、対象214ページ全部との距離を検索DBの埋め込みで計算する。
       通常のベクトル検索と同じ上位BRIDGE_TOP_K件は必ず入れる
    2. 対象の講義を決める：質問に「第N回」がある回と、最良距離との差がBRIDGE_LECTURE_MARGIN以内の講義
    3. 講義ごとに近いページを入れる（片方の講義だけに偏らないようにする）
    4. 対象の講義どうしを「第N回」「次回」で参照しているページを、講義間の橋として入れる
    5. 質問に含まれる用語（graph.jsonの用語ノード）ごとに、その用語に触れる最も近いページを入れる
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("検索語が空です。")
    pages = {page["page_id"]: page for page in load_pages(RAG_SOURCE)}
    graph = json.loads(RAG_GRAPH.read_text(encoding="utf-8"))
    with open_index(RAG_DB) as db:
        vector = embed_text(query.strip(), "RETRIEVAL_QUERY")
        rows = db.execute("SELECT page_id, vec_distance_cosine(embedding, ?) AS distance FROM chunks",
                          (sqlite_vec.serialize_float32(vector),))
        distance = {row["page_id"]: row["distance"] for row in rows if row["page_id"] in pages}
    ranked = sorted(distance, key=lambda page_id: (distance[page_id], page_id))
    if not ranked:
        raise ValueError("検索DBに対象ページがありません。")

    in_scope = {int(document_id[3:5]) for document_id in RAG_DOCUMENT_IDS}
    named = {int(n) for n in LECTURE_REF.findall(query)} & in_scope
    best = {}
    for page_id in ranked:
        best.setdefault(pages[page_id]["lecture"], distance[page_id])
    top = distance[ranked[0]]
    lectures = named | {lecture for lecture, d in best.items() if d <= top + BRIDGE_LECTURE_MARGIN}

    reasons: dict[str, list[str]] = {}
    order: list[str] = []

    def add(page_id: str, reason: str) -> None:
        if page_id not in reasons:
            reasons[page_id] = []
            order.append(page_id)
        reasons[page_id].append(reason)

    # 通常のベクトル検索と同じ上位を先に入れ、その上に講義・参照・用語で足す（上限で切るのは足した側）
    for page_id in ranked[:BRIDGE_TOP_K]:
        add(page_id, "講義を問わず質問に近い")

    for lecture in sorted(lectures):
        for page_id in [p for p in ranked if pages[p]["lecture"] == lecture][:BRIDGE_PER_LECTURE]:
            add(page_id, f"第{lecture}回の中で質問に近い")
    if len(lectures) >= 2:
        links = [p for p in ranked if pages[p]["lecture"] in lectures
                 and lecture_references(pages[p]) & (lectures - {pages[p]["lecture"]})]
        for page_id in links[:BRIDGE_LINKS]:
            refs = "・".join(f"第{n}回" for n in sorted(lecture_references(pages[page_id]) & lectures))
            add(page_id, f"第{pages[page_id]['lecture']}回から{refs}を参照するページ")
    terms = find_terms(query, graph)[:BRIDGE_MAX_TERMS]
    mentions = defaultdict(set)
    for edge in graph["edges"]:
        if edge["relation"] == "mentions":
            mentions[edge["target"]].add(edge["source"])
    for term in terms:
        candidates = [p for p in ranked if p in mentions[term["id"]]
                      and (not lectures or pages[p]["lecture"] in lectures)]
        if candidates:
            add(candidates[0], f"用語「{term['title']}」に触れるページで質問に近い")

    chosen = order[:BRIDGE_MAX_RESULTS]
    results = []
    for page_id in sorted(chosen, key=lambda p: (pages[p]["lecture"], pages[p]["page"])):
        page = pages[page_id]
        results.append({**page, "distance": distance[page_id], "reasons": reasons[page_id],
                        "path": f"第{page['lecture']}回 {page['document_title']} > {page['section']} > {page['title']}"})
    return {"lectures": sorted(lectures), "terms": [term["title"] for term in terms], "pages": results}



def run_full_context(agent, question: str, model, instructions: str, prompt_template: str):
    """全資料を一括投入し、検索ツールを使わずに回答する。"""
    prompt = prompt_template.format(materials=get_all_materials(), question=question)
    print(f"[full-context] 入力{len(prompt):,}文字")
    try:
        with agent.override(tools=[], instructions=instructions):
            return agent.run_sync(prompt, model=model)
    except ModelHTTPError as e:
        print(f"[full-context] APIエラー HTTP {e.status_code}: {e.body}")
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="エージェントを使わず、講義資料の検索だけを実行する")
    parser.add_argument("query", help="調べたい内容")
    args = parser.parse_args()
    for i, result in enumerate(search(args.query), 1):
        print(f"\n{'=' * 60}\n検索結果 {i}\n{'=' * 60}")
        print(f"講義: {result['document_title']}")
        print(f"章: {result['section']}")
        print(f"タイトル: {result['title']}")
        print(f"ページ: {result['page']}")
        print(f"\n{result['content']}")
