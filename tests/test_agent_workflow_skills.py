from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SKILLS = [
    ROOT / ".agents/skills/run-dart-qa-agent-workflow/SKILL.md",
    ROOT / ".claude/skills/run-dart-qa-agent-workflow/SKILL.md",
]


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    _, raw, _ = text.split("---", 2)
    return yaml.safe_load(raw)


@pytest.mark.parametrize("path", SKILLS)
def test_agent_workflow_skill_has_shared_identity_and_controller(path: Path) -> None:
    metadata = _frontmatter(path)
    body = path.read_text(encoding="utf-8")

    assert metadata["name"] == "run-dart-qa-agent-workflow"
    assert metadata["description"].strip()
    assert "scripts/run_agent_workflow.py" in body
    assert "--authorize-external-transmission" in body
    assert "Pass every configured user question to the target model verbatim" in body


def test_codex_skill_interface_references_the_skill() -> None:
    interface = yaml.safe_load(
        (
            ROOT
            / ".agents/skills/run-dart-qa-agent-workflow/agents/openai.yaml"
        ).read_text(encoding="utf-8")
    )["interface"]

    assert "$run-dart-qa-agent-workflow" in interface["default_prompt"]
    assert (ROOT / "scripts/run_agent_workflow.py").is_file()
