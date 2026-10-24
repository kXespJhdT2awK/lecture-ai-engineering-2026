"""第1回 宿題（発展）: 応答時間とトークン数を、複数のモデル・質問で計測する。

使い方:
    uv run python scripts/lec01_benchmark.py                 # モデル×質問×回数を計測
    uv run python scripts/lec01_benchmark.py --burst 20      # 1モデルに連続で投げ、429 が出るまでの回数を見る

結果は lectures/01/results/ に CSV で保存する（APIキーは書き出さない）。
"""

import argparse
import csv
import time
from datetime import datetime
from pathlib import Path

import httpx
from google import genai
from google.genai import errors

from app.config import MODEL, get_api_key

RESULTS_DIR = Path(__file__).resolve().parent.parent / "lectures" / "01" / "results"

# gemini-2.5-flash / gemini-2.5-flash-lite は一覧に出るが、新規ユーザーには 404 が返るので外した
MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemma-4-31b-it",
]

# 一般用語・講座に固有・短い答えで済む、の3種類
QUESTIONS = {
    "general": "LoRAとは何ですか？",
    "course": "AIE2026の講座の宿題にある「3レベル」とは何ですか？",
    "short": "日本の首都はどこですか？一語で答えてください。",
}

FIELDS = [
    "model", "question", "trial", "status", "latency_s",
    "prompt_tokens", "output_tokens", "thoughts_tokens", "total_tokens", "chars", "error",
]


def measure(client: genai.Client, model: str, question: str) -> dict:
    """1回呼び出し、応答時間（秒）とトークン数を返す。API エラーも記録として返す。"""
    start = time.perf_counter()
    try:
        response = client.models.generate_content(model=model, contents=question)
    except errors.APIError as e:
        return {"status": e.code, "latency_s": round(time.perf_counter() - start, 2), "error": (e.message or "")[:120]}
    except httpx.HTTPError as e:  # 回線断など、API に届かなかった場合
        return {"status": "network", "latency_s": round(time.perf_counter() - start, 2), "error": repr(e)[:120]}
    latency = time.perf_counter() - start
    usage = response.usage_metadata
    return {
        "status": 200,
        "latency_s": round(latency, 2),
        "prompt_tokens": usage.prompt_token_count,
        "output_tokens": usage.candidates_token_count,
        "thoughts_tokens": usage.thoughts_token_count or 0,
        "total_tokens": usage.total_token_count,
        "chars": len(response.text or ""),
    }


def write_csv(rows: list[dict], name: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name}_{datetime.now():%Y%m%d_%H%M}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def run_matrix(client: genai.Client, models: list[str], trials: int, interval: float) -> None:
    rows = []
    for model in models:
        for qkey, question in QUESTIONS.items():
            for trial in range(1, trials + 1):
                row = {"model": model, "question": qkey, "trial": trial, **measure(client, model, question)}
                print(row)
                rows.append(row)
                time.sleep(interval)  # 無料枠の 1 分あたりの上限に当たらないよう間を空ける
    print(f"saved: {write_csv(rows, 'matrix')}")


def run_burst(client: genai.Client, n: int) -> None:
    """間を空けずに同じモデルへ n 回投げ、何回目で 429 が返るかを見る。"""
    rows = []
    for trial in range(1, n + 1):
        row = {"model": MODEL, "question": "short", "trial": trial, **measure(client, MODEL, QUESTIONS["short"])}
        print(row)
        rows.append(row)
    print(f"saved: {write_csv(rows, 'burst')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="応答時間とトークン数を計測する")
    parser.add_argument("--models", nargs="+", default=MODELS)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--interval", type=float, default=4.0, help="呼び出しの間隔（秒）")
    parser.add_argument("--burst", type=int, default=0, help="指定すると連続呼び出しの試験だけを行う")
    args = parser.parse_args()

    client = genai.Client(api_key=get_api_key())
    if args.burst:
        run_burst(client, args.burst)
    else:
        run_matrix(client, args.models, args.trials, args.interval)


if __name__ == "__main__":
    main()
