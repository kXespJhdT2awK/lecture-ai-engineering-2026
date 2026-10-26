"""第2回 宿題（発展）: 講座の用語集から作った Q&A で Qwen3.5-0.8B を LoRA 学習し、
学習前・学習後・用語集の検索（文字列照合）の 3 つを同じ質問セットで比べる。

Colab（T4）で 1 セルとして実行する。学習データは scripts/make_sft_dataset.py の出力（glossary_sft.jsonl）、
用語集は data/glossary.json。どちらも /content に置いてから実行する。
設定はノートブック（notebooks/lora_format_tuning.ipynb）に合わせ、エポック数を 3（116 件 × 3 周 = 45 ステップ）、
定義は 1 文が長いので max_new_tokens を 200 にした。ログは 5 ステップごとに取り、チェックポイントは保存しない。
"""

import json, re, subprocess, sys, time
from pathlib import Path

PINS = {"transformers": "5.18.0", "peft": "0.21.1", "trl": "1.14.2", "accelerate": "1.15.0", "datasets": "5.1.0"}
subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "-q", "torchao"])
subprocess.run([sys.executable, "-m", "pip", "install", "-q"] + [f"{k}=={v}" for k, v in PINS.items()], check=True)

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import LoraConfig
from trl import SFTTrainer, SFTConfig
from datasets import Dataset

CONFIG = {
    "base_model": "Qwen/Qwen3.5-0.8B",
    "revision": "2fc06364715b967f1860aea9cf38778875588b17",
    "seed": 42, "num_train_epochs": 3, "warmup_steps": 6, "lr": 2e-4,
    "lora_r": 16, "lora_alpha": 32, "max_seq_len": 512, "max_new_tokens": 200,
    "gen": {"do_sample": False},
}
WORK = Path("/content/hatten"); WORK.mkdir(parents=True, exist_ok=True)
TERMS = json.loads(Path("/content/glossary.json").read_text(encoding="utf-8"))["terms"]
TRAIN = [json.loads(l) for l in Path("/content/glossary_sft.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
DEF = {t["term"]: t["definition"] for t in TERMS}

# 評価の質問。seen＝学習と同じ言い回し、para＝言い回しや別名を変えた質問、unknown＝用語集に無い語、general＝学習と無関係な質問
# keys は答えに含まれてほしい語句（用語集の定義から取った）
EVAL = [
    *[{"cat": "seen", "term": t, "q": f"「{t}」とは何ですか？", "keys": k} for t, k in [
        ("LoRA", ["固定", "小さな行列"]), ("エポック", ["1周"]), ("過学習", ["学習データ", "未知"]),
        ("量子化", ["ビット", "メモリ"]), ("temperature", ["低い", "高い"]), ("ハルシネーション", ["事実"]),
        ("MCP（Model Context Protocol）", ["標準", "プロトコル"]), ("宿題の3レベル", ["基礎", "実装", "発展"]),
        ("既定モデル", ["gemini-3.5-flash-lite"]), ("lecNN-start タグ", ["開始"])]],
    *[{"cat": "para", "term": t, "q": q, "keys": k} for t, q, k in [
        ("LoRA", "Low-Rank Adaptationってどういう仕組み？", ["固定", "小さな行列"]),
        ("エポック", "学習の「epoch」という単位は何を数えているの？", ["1周"]),
        ("過学習", "overfittingが起きているとはどういう状態？", ["学習データ", "未知"]),
        ("量子化", "モデルのquantizationをすると何が変わるの？", ["ビット", "メモリ"]),
        ("temperature", "温度パラメータを上げ下げすると何が起きる？", ["低い", "高い"]),
        ("ハルシネーション", "LLMの「幻覚」って何のこと？", ["事実"]),
        ("MCP（Model Context Protocol）", "Model Context Protocolは何のための仕組み？", ["標準", "プロトコル"]),
        ("宿題の3レベル", "AIE2026の宿題の3レベルにはどんな区分がある？", ["基礎", "実装", "発展"]),
        ("既定モデル", "この講座の演習で標準に使うモデルはどれ？", ["gemini-3.5-flash-lite"]),
        ("lecNN-start タグ", "lec03-startのようなタグは何に使う？", ["開始"])]],
    *[{"cat": "unknown", "term": None, "q": f"「{t}」とは何ですか？", "keys": []} for t in [
        "RAG", "RLHF", "蒸留", "MoE", "プロンプトインジェクション", "ナレッジカットオフ", "宿題の4レベル", "lec14-final タグ"]],
    *[{"cat": "general", "term": None, "q": q, "keys": k} for q, k in [
        ("日本の首都はどこですか？一語で答えてください。", ["東京"]),
        ("1から10までの整数の和はいくつですか？", ["55"]),
        ("「ありがとう」を英語にしてください。", ["thank"])]],
]
ABSTAIN = re.compile(r"わかりません|分かりません|記載がありません|存じません|不明です|確認が必要")


def bigrams(s):
    s = re.sub(r"\s+", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def f1(a, b):
    A, B = bigrams(a), bigrams(b)
    if not A or not B: return 0.0
    p, r = len(A & B) / len(A), len(A & B) / len(B)
    return 0.0 if p + r == 0 else round(2 * p * r / (p + r), 3)


def score(ex, ans):
    row = {"cat": ex["cat"], "q": ex["q"], "answer": ans,
           "keys_ok": all(k.lower() in ans.lower() for k in ex["keys"]) if ex["keys"] else None,
           "abstain": bool(ABSTAIN.search(ans))}
    if ex["term"]:
        row["f1_gold"] = f1(ans, DEF[ex["term"]])
    # 用語集の他の定義をどれだけ写しているか（unknown で既存の定義を流用していないかを見る）
    best = max(TERMS, key=lambda t: f1(ans, t["definition"]))
    row["nearest_term"], row["nearest_f1"] = best["term"], f1(ans, best["definition"])
    return row


def summarize(rows, label, seconds=None):
    out = {"label": label}
    for cat in ["seen", "para", "unknown", "general"]:
        rs = [r for r in rows if r["cat"] == cat]
        d = {"n": len(rs), "abstain_rate": round(sum(r["abstain"] for r in rs) / len(rs), 3)}
        if cat in ("seen", "para", "general"):
            d["keys_rate"] = round(sum(bool(r["keys_ok"]) for r in rs) / len(rs), 3)
        if cat in ("seen", "para"):
            d["mean_f1_gold"] = round(sum(r["f1_gold"] for r in rs) / len(rs), 3)
            d["copied_rate"] = round(sum(r["f1_gold"] >= 0.8 for r in rs) / len(rs), 3)   # 定義をほぼそのまま返した割合
        if cat == "unknown":
            d["copied_other_rate"] = round(sum(r["nearest_f1"] >= 0.5 for r in rs) / len(rs), 3)  # 他の用語の定義を流用
        out[cat] = d
    if seconds is not None: out["seconds"] = seconds
    return out


# 用語集の検索（比較用）: 質問に含まれる用語名・別名のうち最も長いものを探し、その定義を返す
CANDS = []
for t in TERMS:
    for name in [t["term"], re.sub(r"（.*?）", "", t["term"]), *t["aliases"]]:
        if len(name) >= 2: CANDS.append((name.lower(), t["term"]))


def lookup(q):
    hits = [(n, term) for n, term in CANDS if n in q.lower()]
    if not hits: return "用語集に記載がありません。"
    return DEF[max(hits, key=lambda h: len(h[0]))[1]]


torch.manual_seed(CONFIG["seed"])
tok = AutoTokenizer.from_pretrained(CONFIG["base_model"], revision=CONFIG["revision"])
if tok.pad_token is None: tok.pad_token = tok.eos_token
model = AutoModelForCausalLM.from_pretrained(CONFIG["base_model"], revision=CONFIG["revision"], dtype=torch.float32).to("cuda")


def generate(m, q):
    prompt = tok.apply_chat_template([{"role": "user", "content": q}], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    inputs = tok(prompt, return_tensors="pt").to(m.device)
    with torch.no_grad():
        out = m.generate(**inputs, max_new_tokens=CONFIG["max_new_tokens"], pad_token_id=tok.pad_token_id, **CONFIG["gen"])
    return tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def evaluate(m, label):
    t0 = time.time()
    rows = [score(ex, generate(m, ex["q"])) for ex in EVAL]
    s = summarize(rows, label, round(time.time() - t0, 1))
    print(json.dumps(s, ensure_ascii=False))
    return s, rows


before, before_rows = evaluate(model, "before")
lookup_rows = [score(ex, lookup(ex["q"])) for ex in EVAL]
lookup_sum = summarize(lookup_rows, "lookup")
print(json.dumps(lookup_sum, ensure_ascii=False))

model.config.use_cache = False
lora = LoraConfig(r=CONFIG["lora_r"], lora_alpha=CONFIG["lora_alpha"], lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                  target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
sft = SFTConfig(output_dir=str(WORK / "ckpt"), num_train_epochs=CONFIG["num_train_epochs"], per_device_train_batch_size=4,
                gradient_accumulation_steps=2, learning_rate=CONFIG["lr"], lr_scheduler_type="cosine", warmup_steps=CONFIG["warmup_steps"],
                logging_steps=5, save_strategy="no", max_length=CONFIG["max_seq_len"], packing=False, report_to="none", seed=CONFIG["seed"])
trainer = SFTTrainer(model=model, args=sft, train_dataset=Dataset.from_list(TRAIN), peft_config=lora, processing_class=tok)
trainable, total = trainer.model.get_nb_trainable_parameters()
t0 = time.time()
trainer.train()
train_seconds = round(time.time() - t0, 1)
losses = [{"step": h["step"], "loss": h["loss"]} for h in trainer.state.log_history if "loss" in h]
print("学習時間", train_seconds, "秒 | ステップ", trainer.state.global_step, "| loss", losses)
tuned = trainer.model
tuned.config.use_cache = True
tuned.eval()
after, after_rows = evaluate(tuned, "after")

result = {"config": CONFIG, "versions": {m.__name__: m.__version__ for m in [__import__("transformers"), __import__("peft"), __import__("trl"), torch]},
          "train_records": len(TRAIN), "trainable_params": trainable, "all_params": total,
          "train_seconds": train_seconds, "steps": trainer.state.global_step, "losses": losses,
          "before": before, "after": after, "lookup": lookup_sum,
          "rows": [{"q": ex["q"], "cat": ex["cat"], "before": b, "after": a, "lookup": l}
                   for ex, b, a, l in zip(EVAL, before_rows, after_rows, lookup_rows)],
          "executed_training_myself": True}
(WORK / "hatten_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("HATTEN_DONE")
