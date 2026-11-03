"""第3回 宿題（実装）: 承認付きの save_learning_log のテスト（LLMもAPIキーも使わない）。"""

from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.models.test import TestModel

from app import tools
from app.agent import agent, ask_approvals


def _first_run(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "LOG_DIR", tmp_path / "learning_log")
    model = TestModel(call_tools=["save_learning_log"])
    with agent.override(model=model):
        result = agent.run_sync("今日学んだことを記録して")
    return model, result


def test_save_is_paused_until_approved(monkeypatch, tmp_path):
    _, result = _first_run(monkeypatch, tmp_path)
    assert isinstance(result.output, DeferredToolRequests)
    assert [c.tool_name for c in result.output.approvals] == ["save_learning_log"]
    assert not (tmp_path / "learning_log").exists()  # 承認前は書かない


def test_approved_call_writes_file(monkeypatch, tmp_path):
    model, result = _first_run(monkeypatch, tmp_path)
    approvals = ask_approvals(result.output, ask=lambda _: "y")
    with agent.override(model=model):
        agent.run_sync(message_history=result.all_messages(),
                       deferred_tool_results=DeferredToolResults(approvals=approvals))
    files = list((tmp_path / "learning_log").glob("*.md"))
    assert len(files) == 1


def test_denied_call_writes_nothing(monkeypatch, tmp_path):
    model, result = _first_run(monkeypatch, tmp_path)
    approvals = ask_approvals(result.output, ask=lambda _: "n")
    with agent.override(model=model):
        final = agent.run_sync(message_history=result.all_messages(),
                               deferred_tool_results=DeferredToolResults(approvals=approvals))
    assert not (tmp_path / "learning_log").exists()
    assert isinstance(final.output, str)


def test_save_learning_log_rejects_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "LOG_DIR", tmp_path / "learning_log")
    assert "保存していません" in tools.save_learning_log("", "")
    msg = tools.save_learning_log("LoRA と QLoRA", "QLoRA は重みを4ビットに量子化する")
    saved = list((tmp_path / "learning_log").glob("*.md"))
    assert len(saved) == 1 and saved[0].name in msg
    assert "QLoRA は重みを4ビット" in saved[0].read_text(encoding="utf-8")
