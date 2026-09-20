"""The repository's supply chain, asserted against the files' own contents.

Two readings of the same files, deliberately kept apart:

*Parsed* - workflows and the Dependabot config are read with a YAML parser, so
comments are structurally invisible. A guard matched against raw text is
satisfied by a file's own documentation: shyden.co.uk shipped a Dependabot
config whose explanatory NOTE spelled out the very group it lacked, and the
guard passed with nothing configured.

*Raw* - the trailing `# vX.Y.Z` beside a pinned SHA is a comment, and the
comment is the point. It is what makes a Dependabot bump reviewable instead of
an opaque hex swap, so that one assertion reads the bytes on purpose.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
DEPENDABOT = REPO / ".github" / "dependabot.yml"

SHA = re.compile(r"^[0-9a-f]{40}$")
USES_LINE = re.compile(r"^-?\s*uses:\s*(\S+)")
USES_WITH_VERSION_COMMENT = re.compile(
    r"uses:\s*\S+@[0-9a-f]{40}\s+#\s*v?\d+(?:\.\d+)*(?:[-.][0-9A-Za-z.]+)?\s*$"
)


def workflow_files() -> list[Path]:
    """Derived from the filesystem, never from a list written into this test.

    A sweep driven by a hand-written file list is not a sweep: it covers what
    its author remembered, and a workflow added next year is invisible to it.
    """
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def steps_of(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        step
        for job in (workflow.get("jobs") or {}).values()
        for step in (job.get("steps") or [])
        if isinstance(step, dict)
    ]


def third_party_uses() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for path in workflow_files():
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for step in steps_of(workflow):
            uses = step.get("uses")
            # A local composite action is referenced by path and has no SHA to
            # pin; a Docker reference is pinned by digest elsewhere.
            if isinstance(uses, str) and not uses.startswith("./"):
                found.append((path, uses))
    return found


class TestActionsArePinned:
    def test_there_are_workflows_to_check(self) -> None:
        # Positive control. Every assertion below iterates a population found
        # at runtime, and an empty population passes each of them while
        # asserting nothing at all.
        assert workflow_files(), "no workflow files found; the guard would be vacuous"
        assert third_party_uses(), "no third-party actions found; the pin guard would be vacuous"

    def test_every_third_party_action_is_pinned_to_a_full_sha(self) -> None:
        for path, uses in third_party_uses():
            ref = uses.rsplit("@", 1)[-1] if "@" in uses else ""
            assert SHA.match(ref), (
                f"{path.name}: {uses!r} is not pinned to a 40-hex commit SHA. "
                "A tag is mutable and can be repointed by anyone who can push to that "
                "action's repository; the SHA is the only immutable reference."
            )

    def test_every_pinned_action_carries_its_version_as_a_comment(self) -> None:
        # Read raw on purpose: this assertion is about the comment itself.
        examined = 0
        for path in workflow_files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                # A step is a list item, so the line reads `- uses: ...`, and
                # matching on `uses:` alone at the start of the stripped line
                # skips every step in the file.
                match = USES_LINE.match(line.strip())
                if not match or match.group(1).startswith("./"):
                    continue
                examined += 1
                assert USES_WITH_VERSION_COMMENT.search(line.strip()), (
                    f"{path.name}:{number}: {line.strip()!r} has no trailing `# vX.Y.Z`. "
                    "The comment is what makes a Dependabot bump reviewable rather than "
                    "an opaque hex swap."
                )
        # Liveness control, tying this raw scan to the parsed population. The
        # first version of this loop matched `uses:` at the start of the line,
        # examined nothing, and passed - and a mutation removing a version
        # comment stayed green. Counting what was read is what caught it.
        assert examined == len(third_party_uses()), (
            f"this test examined {examined} lines while the parser found "
            f"{len(third_party_uses())} third-party actions. A loop that skips every line "
            "passes while asserting nothing."
        )


class TestDependabot:
    @pytest.fixture()
    def config(self) -> dict[str, Any]:
        assert DEPENDABOT.exists(), (
            "no .github/dependabot.yml. Version updates are NOT inheritable "
            "organisation-wide - only security updates are - so this file is per-repository "
            "and must be created deliberately."
        )
        return yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8")) or {}

    def test_it_covers_every_ecosystem_present_and_github_actions(
        self, config: dict[str, Any]
    ) -> None:
        declared = {u["package-ecosystem"] for u in config["updates"]}
        assert "github-actions" in declared
        assert "pip" in declared, "this project's dependencies are Python"

    def test_every_ecosystem_targets_develop(self, config: dict[str, Any]) -> None:
        for update in config["updates"]:
            assert update.get("target-branch") == "develop", (
                f"{update['package-ecosystem']} has no develop target. A pull request opened "
                "against a protected main either cannot merge or bypasses the dev gate."
            )

    def test_same_repository_sub_path_actions_are_grouped_above_any_catch_all(
        self, config: dict[str, Any]
    ) -> None:
        actions = next(u for u in config["updates"] if u["package-ecosystem"] == "github-actions")
        groups = list((actions.get("groups") or {}).items())
        assert groups, (
            "github-actions declares no groups. Dependabot treats actions/cache, "
            "actions/cache/restore and actions/cache/save as separate dependencies, so "
            "ungrouped they arrive as separate pull requests, each moving one SHA while its "
            "siblings lag."
        )

        def is_sub_path_group(spec: dict[str, Any]) -> bool:
            return any(
                "/" in pattern and pattern.endswith("*") for pattern in spec.get("patterns", [])
            )

        def is_catch_all(spec: dict[str, Any]) -> bool:
            return "*" in spec.get("patterns", [])

        names = [name for name, _ in groups]
        sub_path = [i for i, (_, spec) in enumerate(groups) if is_sub_path_group(spec)]
        catch_all = [i for i, (_, spec) in enumerate(groups) if is_catch_all(spec)]
        assert sub_path, f"no sub-path group among {names}"
        if catch_all:
            assert min(sub_path) < min(catch_all), (
                f"a catch-all group sits above the sub-path group in {names}. Dependabot "
                "assigns a dependency to the FIRST matching group and stops, so the sub-path "
                "group would never receive anything."
            )


class TestProjectMetadata:
    @pytest.fixture()
    def pyproject(self) -> dict[str, Any]:
        import tomllib

        return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))

    def test_the_python_floor_matches_the_tested_matrix(self, pyproject: dict[str, Any]) -> None:
        assert pyproject["project"]["requires-python"] == ">=3.11"
        matrix_versions = set()
        for path in workflow_files():
            workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for job in (workflow.get("jobs") or {}).values():
                strategy = (job.get("strategy") or {}).get("matrix") or {}
                matrix_versions |= {str(v) for v in strategy.get("python-version", [])}
        assert matrix_versions == {"3.11", "3.12", "3.13"}, (
            f"the matrix tests {sorted(matrix_versions)} while the package claims >=3.11"
        )

    def test_it_is_licensed_apache_2_0(self, pyproject: dict[str, Any]) -> None:
        assert pyproject["project"]["license"] == {"text": "Apache-2.0"}
        assert (REPO / "LICENSE").exists()
        assert "Apache License" in (REPO / "LICENSE").read_text(encoding="utf-8")
