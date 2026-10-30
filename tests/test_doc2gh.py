import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple
import unittest
from unittest.mock import patch

from tools import doc2gh

REPO_ROOT = Path(__file__).resolve().parent.parent


def create_doc2gh_fixture(
    root_dir: Path,
    subtree_prefix: Optional[str] = None,
    with_git: bool = True,
    branch: str = "main",
) -> Tuple[Path, Path]:
    """
    Create a temporary repository fixture with templates and workflows.
    Returns (repo_root, doc_base_dir).
    """
    repo_root = root_dir.resolve()
    if with_git:
        git_dir = repo_root / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)
        (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")

    doc_base = (repo_root / subtree_prefix).resolve() if subtree_prefix else repo_root
    for doc_type, cfg in doc2gh.DOC_CONFIG.items():
        src_template = REPO_ROOT / cfg["dir"] / "template.md"
        dst_dir = doc_base / cfg["dir"]
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_template, dst_dir / "template.md")

    src_wf_dir = REPO_ROOT / "workflows"
    dst_wf_dir = doc_base / "workflows"
    dst_wf_dir.mkdir(parents=True, exist_ok=True)
    for wf in src_wf_dir.glob("*.yml"):
        shutil.copy2(wf, dst_wf_dir / wf.name)

    tools_dir = doc_base / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "tools" / "doc2gh.py", tools_dir / "doc2gh.py")

    return repo_root, doc_base


def make_completed_process(
    args: List[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


class FakeCommandRunner:
    """Configurable mock for subprocess.run handling git and gh invocations."""

    def __init__(
        self,
        origin_url: Optional[str] = "https://github.com/acme/demo-repo.git",
        other_remotes: Optional[List[str]] = None,
        branch: str = "main",
        dirty_output: str = "",
        has_upstream: bool = True,
        auth_ok: bool = True,
        repo_exists: bool = True,
        repo_permission: str = "ADMIN",
        default_branch: str = "main",
        repo_view_error: str = "",
        projects: Optional[List[Dict[str, Any]]] = None,
        project_create_fails: bool = False,
        existing_labels: Optional[List[Dict[str, Any]]] = None,
        issues: Optional[List[Dict[str, Any]]] = None,
        issue_create_fails: bool = False,
        project_items: Optional[List[Dict[str, Any]]] = None,
        open_prs: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.origin_url = origin_url
        self.other_remotes = other_remotes or []
        self.branch = branch
        self.dirty_output = dirty_output
        self.has_upstream = has_upstream
        self.auth_ok = auth_ok
        self.repo_exists = repo_exists
        self.repo_permission = repo_permission
        self.default_branch = default_branch
        self.repo_view_error = repo_view_error
        self.projects = list(projects) if projects is not None else []
        self.project_create_fails = project_create_fails
        self.existing_labels = list(existing_labels) if existing_labels is not None else []
        self.issues = list(issues) if issues is not None else []
        self.issue_create_fails = issue_create_fails
        self.project_items = list(project_items) if project_items is not None else []
        self.open_prs = list(open_prs) if open_prs is not None else []
        self.calls: List[List[str]] = []

    def __call__(self, cmd: List[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        str_cmd = [str(c) for c in cmd]
        self.calls.append(str_cmd)
        binary = str_cmd[0]

        if binary == "git":
            if "remote" in str_cmd and "get-url" in str_cmd and "origin" in str_cmd:
                if self.origin_url:
                    return make_completed_process(str_cmd, 0, f"{self.origin_url}\n")
                return make_completed_process(str_cmd, 2, "", "error: No such remote 'origin'")
            if str_cmd[-1] == "remote":
                remotes = list(self.other_remotes)
                if self.origin_url and "origin" not in remotes:
                    remotes.insert(0, "origin")
                return make_completed_process(str_cmd, 0, "\n".join(remotes) + ("\n" if remotes else ""))
            if "remote" in str_cmd and "add" in str_cmd and "origin" in str_cmd:
                self.origin_url = str_cmd[-1]
                return make_completed_process(str_cmd, 0, "")
            if "symbolic-ref" in str_cmd:
                if self.branch == "DETACHED":
                    return make_completed_process(str_cmd, 128, "", "fatal: ref HEAD is not a symbolic ref")
                return make_completed_process(str_cmd, 0, f"{self.branch}\n")
            if "status" in str_cmd and "--porcelain" in str_cmd:
                return make_completed_process(str_cmd, 0, self.dirty_output)
            if "rev-parse" in str_cmd and "@{u}" in str_cmd:
                if self.has_upstream:
                    return make_completed_process(str_cmd, 0, f"origin/{self.branch}\n")
                return make_completed_process(str_cmd, 128, "", "fatal: no upstream configured")
            if "rev-parse" in str_cmd and "--is-inside-work-tree" in str_cmd:
                return make_completed_process(str_cmd, 0, "true\n")
            if "push" in str_cmd:
                self.has_upstream = True
                return make_completed_process(str_cmd, 0, "Branch pushed\n")
            return make_completed_process(str_cmd, 0, "")

        if binary == "gh":
            sub = str_cmd[1:3]
            if sub == ["auth", "status"]:
                if self.auth_ok:
                    return make_completed_process(str_cmd, 0, "Logged in to github.com\n")
                return make_completed_process(str_cmd, 1, "", "You are not logged into any GitHub hosts.")

            if sub == ["repo", "view"]:
                if not self.repo_exists:
                    err = self.repo_view_error or "GraphQL: Could not resolve to a Repository (404)"
                    return make_completed_process(str_cmd, 1, "", err)
                target = str_cmd[3]
                owner, name = target.split("/", 1) if "/" in target else ("acme", target)
                payload = {
                    "name": name,
                    "owner": {"login": owner},
                    "url": f"https://github.com/{owner}/{name}",
                    "defaultBranchRef": {"name": self.default_branch},
                    "viewerPermission": self.repo_permission,
                }
                return make_completed_process(str_cmd, 0, json.dumps(payload))

            if sub == ["repo", "create"]:
                self.repo_exists = True
                target = str_cmd[3]
                return make_completed_process(str_cmd, 0, f"https://github.com/{target}\n")

            if sub == ["project", "list"]:
                return make_completed_process(str_cmd, 0, json.dumps({"projects": self.projects}))

            if sub == ["project", "create"]:
                if self.project_create_fails:
                    return make_completed_process(
                        str_cmd, 1, "", "error: missing required scope 'project'"
                    )
                title_idx = str_cmd.index("--title") + 1
                owner_idx = str_cmd.index("--owner") + 1
                proj = {
                    "number": len(self.projects) + 1,
                    "id": f"PVT_{len(self.projects) + 1}",
                    "title": str_cmd[title_idx],
                    "url": f"https://github.com/orgs/{str_cmd[owner_idx]}/projects/{len(self.projects) + 1}",
                }
                self.projects.append(proj)
                return make_completed_process(str_cmd, 0, json.dumps(proj))

            if sub == ["project", "link"]:
                return make_completed_process(str_cmd, 0, "Linked project\n")

            if sub == ["project", "item-list"]:
                return make_completed_process(str_cmd, 0, json.dumps({"items": self.project_items}))

            if sub == ["project", "item-add"]:
                url_idx = str_cmd.index("--url") + 1
                url = str_cmd[url_idx]
                self.project_items.append({"content": {"url": url}})
                return make_completed_process(str_cmd, 0, json.dumps({"id": "PVTI_1"}))

            if sub == ["label", "list"]:
                return make_completed_process(str_cmd, 0, json.dumps(self.existing_labels))

            if sub == ["label", "create"]:
                lbl_name = str_cmd[3]
                self.existing_labels.append({"name": lbl_name})
                return make_completed_process(str_cmd, 0, f"Label {lbl_name} created\n")

            if sub == ["issue", "list"]:
                return make_completed_process(str_cmd, 0, json.dumps(self.issues))

            if sub == ["issue", "view"]:
                num = int(str_cmd[3])
                for item in self.issues:
                    if item.get("number") == num:
                        return make_completed_process(str_cmd, 0, json.dumps(item))
                return make_completed_process(str_cmd, 1, "", "issue not found")

            if sub == ["issue", "create"]:
                if self.issue_create_fails:
                    return make_completed_process(str_cmd, 1, "", "HTTP 500: Internal Server Error")
                repo_idx = str_cmd.index("--repo") + 1
                title_idx = str_cmd.index("--title") + 1
                body_idx = str_cmd.index("--body") + 1
                label_idx = str_cmd.index("--label") + 1
                num = len(self.issues) + 1
                labels = [{"name": l} for l in str_cmd[label_idx].split(",") if l]
                issue_obj = {
                    "number": num,
                    "title": str_cmd[title_idx],
                    "body": str_cmd[body_idx],
                    "labels": labels,
                    "state": "OPEN",
                }
                self.issues.append(issue_obj)
                return make_completed_process(
                    str_cmd, 0, f"https://github.com/{str_cmd[repo_idx]}/issues/{num}\n"
                )

            if sub == ["issue", "edit"]:
                num = int(str_cmd[3])
                for item in self.issues:
                    if item.get("number") == num:
                        if "--title" in str_cmd:
                            item["title"] = str_cmd[str_cmd.index("--title") + 1]
                        if "--body" in str_cmd:
                            item["body"] = str_cmd[str_cmd.index("--body") + 1]
                        cur_lbls = [
                            l["name"] if isinstance(l, dict) else l for l in item.get("labels", [])
                        ]
                        if "--remove-label" in str_cmd:
                            to_rem = set(str_cmd[str_cmd.index("--remove-label") + 1].split(","))
                            cur_lbls = [l for l in cur_lbls if l not in to_rem]
                        if "--add-label" in str_cmd:
                            for l in str_cmd[str_cmd.index("--add-label") + 1].split(","):
                                if l and l not in cur_lbls:
                                    cur_lbls.append(l)
                        item["labels"] = [{"name": l} for l in cur_lbls]
                return make_completed_process(str_cmd, 0, "Edited issue\n")

            if sub in (["issue", "close"], ["issue", "reopen"]):
                num = int(str_cmd[3])
                for item in self.issues:
                    if item.get("number") == num:
                        item["state"] = "CLOSED" if sub[1] == "close" else "OPEN"
                return make_completed_process(str_cmd, 0, "")

            if sub == ["pr", "list"]:
                return make_completed_process(str_cmd, 0, json.dumps(self.open_prs))

            if sub == ["pr", "create"]:
                repo_idx = str_cmd.index("--repo") + 1
                title_idx = str_cmd.index("--title") + 1
                body_idx = str_cmd.index("--body") + 1
                num = len(self.open_prs) + 10
                url = f"https://github.com/{str_cmd[repo_idx]}/pull/{num}"
                pr_obj = {
                    "number": num,
                    "url": url,
                    "title": str_cmd[title_idx],
                    "body": str_cmd[body_idx],
                }
                self.open_prs.append(pr_obj)
                return make_completed_process(str_cmd, 0, f"{url}\n")

        return make_completed_process(str_cmd, 0, "")


class Doc2GhInitAndSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.tmp_dir.name)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _run_cli(
        self,
        argv: List[str],
        runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
        which_map: Optional[Dict[str, Optional[str]]] = None,
        user_input: Optional[str] = None,
    ) -> Tuple[int, str, str]:
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        def fake_which(cmd: str) -> Optional[str]:
            if which_map and cmd in which_map:
                return which_map[cmd]
            return f"/usr/bin/{cmd}"

        patches = [
            patch("tools.doc2gh.shutil.which", side_effect=fake_which),
            patch("sys.stdout", stdout_buf),
            patch("sys.stderr", stderr_buf),
        ]
        if runner is not None:
            patches.append(patch("tools.doc2gh.subprocess.run", side_effect=runner))
        if user_input is not None:
            patches.append(patch("builtins.input", return_value=user_input))

        with patches[0], patches[1], patches[2]:
            if len(patches) == 4:
                with patches[3]:
                    rc = doc2gh.main(argv)
            elif len(patches) == 5:
                with patches[3], patches[4]:
                    rc = doc2gh.main(argv)
            else:
                rc = doc2gh.main(argv)

        return rc, stdout_buf.getvalue(), stderr_buf.getvalue()

    def test_ac01_init_from_root_and_doc_subtree_validates_and_bootstraps(self) -> None:
        # Test packaged doc/ subtree invocation
        repo_root, doc_base = create_doc2gh_fixture(self.root_path, subtree_prefix="doc")
        rc, _, _ = self._run_cli(["--root", str(doc_base), "new", "spec", "Bootstrap Feature"])
        self.assertEqual(rc, 0)

        runner = FakeCommandRunner(origin_url="https://github.com/acme/subtree-app.git")
        rc, out, err = self._run_cli(["--root", str(doc_base), "init"], runner=runner)
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("Validated 4 local document(s) and template(s).", out)
        self.assertIn("Target GitHub repository: acme/subtree-app", out)

        # Verify relative workflow symlinks point into ../../doc/workflows/*.yml
        wf_link = repo_root / ".github" / "workflows" / "doc-lint.yml"
        self.assertTrue(wf_link.is_symlink())
        self.assertEqual(os.readlink(wf_link), "../../doc/workflows/doc-lint.yml")
        self.assertEqual(wf_link.resolve(), (doc_base / "workflows" / "doc-lint.yml").resolve())

        # Verify SPEC-0001 was linked to Issue #1 and remains valid
        spec_file = doc_base / "specs" / "0001-bootstrap-feature.md"
        fields, _ = doc2gh.parse_frontmatter(spec_file.read_text(encoding="utf-8"))
        self.assertEqual((fields or {}).get("github_issue"), "#1")
        val_rc, _, val_err = self._run_cli(
            ["--root", str(doc_base), "validate", "--include-templates"]
        )
        self.assertEqual(val_rc, 0, msg=val_err)

        # Verify direct invocation of packaged doc/tools/doc2gh.py without --root resolves repo_root and base_dir
        sub_res = subprocess.run(
            ["python3", str(doc_base / "tools" / "doc2gh.py"), "init", "--dry-run"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(sub_res.returncode, 0, msg=sub_res.stderr)
        self.assertIn("Validated 4 local document(s) and template(s).", sub_res.stdout)

    def test_ac02_missing_remote_creates_repo_and_pushes_with_confirmation_without_force(self) -> None:
        repo_root, doc_base = create_doc2gh_fixture(self.root_path)
        runner = FakeCommandRunner(origin_url=None, repo_exists=False, branch="main")

        # 1. Without confirmation (user answers 'n'), init aborts before creating remote or pushing
        rc_decline, _, err_decline = self._run_cli(
            ["--root", str(doc_base), "init", "--repo", "acme/new-service"],
            runner=runner,
            user_input="n",
        )
        self.assertEqual(rc_decline, 1)
        self.assertIn("not confirmed", err_decline)
        self.assertFalse(any(c[:3] == ["gh", "repo", "create"] for c in runner.calls))

        # 2. With confirmation ('y'), init creates repository, adds origin, and pushes without --force
        runner_confirm = FakeCommandRunner(origin_url=None, repo_exists=False, branch="main")
        rc_ok, out_ok, err_ok = self._run_cli(
            ["--root", str(doc_base), "init", "--repo", "acme/new-service"],
            runner=runner_confirm,
            user_input="y",
        )
        self.assertEqual(rc_ok, 0, msg=err_ok)
        self.assertIn("Created GitHub repository 'acme/new-service'", out_ok)
        self.assertTrue(
            any(c[:4] == ["gh", "repo", "create", "acme/new-service"] for c in runner_confirm.calls)
        )
        push_calls = [c for c in runner_confirm.calls if c[0] == "git" and "push" in c]
        self.assertEqual(len(push_calls), 1)
        self.assertIn("origin", push_calls[0])
        self.assertIn("main", push_calls[0])
        self.assertNotIn("--force", push_calls[0])
        self.assertNotIn("-f", push_calls[0])

    def test_ac03_existing_remote_reused_without_replacing_history(self) -> None:
        _, doc_base = create_doc2gh_fixture(self.root_path)
        runner = FakeCommandRunner(
            origin_url="https://github.com/acme/existing-repo.git",
            repo_exists=True,
        )
        rc, out, err = self._run_cli(["--root", str(doc_base), "init"], runner=runner)
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("Reusing existing GitHub repository 'acme/existing-repo'.", out)
        self.assertFalse(any(c[:3] == ["gh", "repo", "create"] for c in runner.calls))
        self.assertFalse(any(c[0] == "git" and "push" in c for c in runner.calls))

    def test_ac04_and_ac05_idempotent_sync_preserves_manual_descriptions_and_labels(self) -> None:
        _, doc_base = create_doc2gh_fixture(self.root_path)
        self._run_cli(["--root", str(doc_base), "new", "adr", "Use SQLite"])
        self._run_cli(["--root", str(doc_base), "new", "rfc", "Async Events"])
        self._run_cli(["--root", str(doc_base), "new", "spec", "Auth API"])

        # Pre-populate an existing Issue for SPEC-0001 with manual description and unrelated label
        existing_spec_issue = {
            "number": 42,
            "title": "[SPEC-0001] Auth API",
            "body": "Manual context written by engineer.\n\nMore notes here.",
            "labels": [{"name": "priority:high"}, {"name": "status:ready"}, {"name": "spec"}],
            "state": "OPEN",
        }
        runner = FakeCommandRunner(
            origin_url="https://github.com/acme/demo-repo.git",
            issues=[existing_spec_issue],
        )

        # First init run
        rc1, out1, err1 = self._run_cli(["--root", str(doc_base), "init"], runner=runner)
        self.assertEqual(rc1, 0, msg=err1)
        self.assertEqual(len(runner.issues), 3)

        # Check that SPEC-0001 reused Issue #42, preserved manual text and 'priority:high', and removed stale 'status:ready'
        spec_issue = next(i for i in runner.issues if i["number"] == 42)
        self.assertIn("Manual context written by engineer.", spec_issue["body"])
        self.assertIn("<!-- DOC2GH:ISSUE:START -->", spec_issue["body"])
        spec_labels = [l["name"] for l in spec_issue["labels"]]
        self.assertIn("priority:high", spec_labels)
        self.assertIn("spec", spec_labels)
        self.assertIn("status:draft", spec_labels)
        self.assertNotIn("status:ready", spec_labels)

        # Second init run (AC-05: idempotency - zero duplicate Projects, labels, Issues, or Project items)
        calls_before_second_run = len(runner.calls)
        rc2, out2, err2 = self._run_cli(["--root", str(doc_base), "init"], runner=runner)
        self.assertEqual(rc2, 0, msg=err2)
        second_run_calls = runner.calls[calls_before_second_run:]

        self.assertFalse(any(c[:3] == ["gh", "project", "create"] for c in second_run_calls))
        self.assertFalse(any(c[:3] == ["gh", "label", "create"] for c in second_run_calls))
        self.assertFalse(any(c[:3] == ["gh", "issue", "create"] for c in second_run_calls))
        self.assertFalse(any(c[:3] == ["gh", "issue", "edit"] for c in second_run_calls))
        self.assertFalse(any(c[:3] == ["gh", "project", "item-add"] for c in second_run_calls))

    def test_ac06_failures_on_invalid_docs_missing_auth_permissions_and_bad_remotes(self) -> None:
        _, doc_base = create_doc2gh_fixture(self.root_path)
        self._run_cli(["--root", str(doc_base), "new", "spec", "Broken Spec"])
        spec_path = doc_base / "specs" / "0001-broken-spec.md"

        # 1. Tamper with document status so frontmatter and management block disagree
        tampered = spec_path.read_text(encoding="utf-8").replace("status: draft", "status: done", 1)
        spec_path.write_text(tampered, encoding="utf-8")

        runner = FakeCommandRunner()
        rc_val, _, err_val = self._run_cli(["--root", str(doc_base), "init"], runner=runner)
        self.assertEqual(rc_val, 1)
        self.assertIn("Validation failed before initialization", err_val)
        self.assertEqual(len(runner.calls), 0)
        self.assertFalse((self.root_path / ".github" / "workflows").exists())

        # Fix document
        self._run_cli(["--root", str(doc_base), "status", "SPEC-0001", "draft"])

        # 2. Unauthenticated gh CLI exits 1 before mutations
        unauth_runner = FakeCommandRunner(auth_ok=False)
        rc_auth, _, err_auth = self._run_cli(["--root", str(doc_base), "init"], runner=unauth_runner)
        self.assertEqual(rc_auth, 1)
        self.assertIn("not authenticated", err_auth)
        self.assertFalse((self.root_path / ".github" / "workflows").exists())

        # 3. Insufficient repository permissions ('READ') exits 1 before mutations
        read_only_runner = FakeCommandRunner(repo_permission="READ")
        rc_perm, _, err_perm = self._run_cli(
            ["--root", str(doc_base), "init"], runner=read_only_runner
        )
        self.assertEqual(rc_perm, 1)
        self.assertIn("Insufficient permissions", err_perm)
        self.assertFalse((self.root_path / ".github" / "workflows").exists())

        # 4. Non-GitHub remote without explicit target fails without guessing owner
        gitlab_runner = FakeCommandRunner(origin_url="https://gitlab.com/acme/repo.git")
        rc_gl, _, err_gl = self._run_cli(["--root", str(doc_base), "init"], runner=gitlab_runner)
        self.assertEqual(rc_gl, 1)
        self.assertIn("not a GitHub remote", err_gl)

        # 5. Ambiguous remotes without origin fails
        ambig_runner = FakeCommandRunner(origin_url=None, other_remotes=["upstream", "fork"])
        rc_amb, _, err_amb = self._run_cli(["--root", str(doc_base), "init"], runner=ambig_runner)
        self.assertEqual(rc_amb, 1)
        self.assertIn("Ambiguous Git remote", err_amb)

        # 6. Conflicting remote fails
        conflict_rem_runner = FakeCommandRunner(origin_url="https://github.com/acme/repo-a.git")
        rc_conf, _, err_conf = self._run_cli(
            ["--root", str(doc_base), "init", "--repo", "acme/repo-b"],
            runner=conflict_rem_runner,
        )
        self.assertEqual(rc_conf, 1)
        self.assertIn("Conflicting remote", err_conf)

        # 7. Dirty worktree before push fails
        dirty_runner = FakeCommandRunner(
            origin_url=None, repo_exists=False, dirty_output=" M README.md\n"
        )
        rc_dirty, _, err_dirty = self._run_cli(
            ["--root", str(doc_base), "init", "--repo", "acme/new-repo", "--yes"],
            runner=dirty_runner,
        )
        self.assertEqual(rc_dirty, 1)
        self.assertIn("Dirty worktree", err_dirty)

        # 8. Unsupported default branch fails
        unsupported_branch_runner = FakeCommandRunner(default_branch="trunk")
        rc_br, _, err_br = self._run_cli(
            ["--root", str(doc_base), "init"], runner=unsupported_branch_runner
        )
        self.assertEqual(rc_br, 1)
        self.assertIn("Unsupported default branch", err_br)

    def test_ac07_dry_run_reports_plan_without_local_or_remote_writes(self) -> None:
        repo_root, doc_base = create_doc2gh_fixture(self.root_path, branch="spec/0001-plan")
        self._run_cli(["--root", str(doc_base), "new", "spec", "Dry Run Spec"])

        runner = FakeCommandRunner(
            origin_url="https://github.com/acme/demo-repo.git",
            branch="spec/0001-plan",
            auth_ok=False,
        )
        rc, out, err = self._run_cli(
            ["--root", str(doc_base), "init", "--dry-run", "--create-pr"], runner=runner
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("[dry-run] Would verify and reuse existing GitHub repository", out)
        self.assertIn("[dry-run] Would create workflow symlink", out)
        self.assertIn("[dry-run] Would create/ensure GitHub Project", out)
        self.assertIn("[dry-run] Would provision 16 doc2gh labels", out)
        self.assertIn("[dry-run] Would synchronize SPEC-0001", out)
        self.assertIn("[dry-run] Would create or reuse Pull Request", out)

        # Verify no symlinks or .doc2gh.json were written and no gh commands were called
        self.assertFalse((repo_root / ".github").exists())
        self.assertFalse((doc_base / ".doc2gh.json").exists())
        self.assertFalse(any(c[0] == "gh" for c in runner.calls))

    def test_ac08_and_ac09_workflow_symlink_repair_and_conflict_preservation(self) -> None:
        repo_root, doc_base = create_doc2gh_fixture(self.root_path)
        wf_target_dir = repo_root / ".github" / "workflows"
        wf_target_dir.mkdir(parents=True, exist_ok=True)

        # Create a broken symlink for doc-lint.yml and a misdirected symlink for pr-doc-link.yml
        os.symlink("../../nonexistent.yml", wf_target_dir / "doc-lint.yml")
        os.symlink(
            str((doc_base / "workflows" / "doc-lint.yml").resolve()),
            wf_target_dir / "pr-doc-link.yml",
        )

        rc_repair, out_repair, err_repair = self._run_cli(
            ["--root", str(doc_base), "init", "--skip-github"]
        )
        self.assertEqual(rc_repair, 0, msg=err_repair)
        self.assertIn("Repaired workflow symlink: .github/workflows/doc-lint.yml", out_repair)
        self.assertIn("Repaired workflow symlink: .github/workflows/pr-doc-link.yml", out_repair)
        self.assertEqual(
            os.readlink(wf_target_dir / "doc-lint.yml"), "../../workflows/doc-lint.yml"
        )
        self.assertEqual(
            os.readlink(wf_target_dir / "pr-doc-link.yml"), "../../workflows/pr-doc-link.yml"
        )

        # Now replace doc-lint.yml symlink with a regular file (AC-09 conflict preservation)
        (wf_target_dir / "doc-lint.yml").unlink()
        custom_content = "# Custom user workflow - must not be overwritten\n"
        (wf_target_dir / "doc-lint.yml").write_text(custom_content, encoding="utf-8")

        rc_conf, _, err_conf = self._run_cli(
            ["--root", str(doc_base), "init", "--skip-github", "--force"]
        )
        self.assertEqual(rc_conf, 1)
        self.assertIn("Conflict at '.github/workflows/doc-lint.yml'", err_conf)
        self.assertFalse((wf_target_dir / "doc-lint.yml").is_symlink())
        self.assertEqual(
            (wf_target_dir / "doc-lint.yml").read_text(encoding="utf-8"), custom_content
        )

    def test_ac10_gh_event_updates_documents_and_maintains_validity(self) -> None:
        _, doc_base = create_doc2gh_fixture(self.root_path)
        self._run_cli(["--root", str(doc_base), "new", "spec", "Event Driven Spec"])
        spec_path = doc_base / "specs" / "0001-event-driven-spec.md"

        # 1. Issue labeled 'status:ready'
        event_file = self.root_path / "event.json"
        event_file.write_text(
            json.dumps(
                {
                    "action": "labeled",
                    "label": {"name": "status:ready"},
                    "issue": {"number": 7, "title": "[SPEC-0001] Event Driven Spec", "body": ""},
                }
            ),
            encoding="utf-8",
        )
        rc1, _, err1 = self._run_cli(
            [
                "--root",
                str(doc_base),
                "gh-event",
                "--event-name",
                "issues",
                "--event-path",
                str(event_file),
            ]
        )
        self.assertEqual(rc1, 0, msg=err1)
        fields, _ = doc2gh.parse_frontmatter(spec_path.read_text(encoding="utf-8"))
        self.assertEqual((fields or {}).get("status"), "ready")
        self.assertEqual((fields or {}).get("github_issue"), "#7")

        # 2. Pull Request opened referencing SPEC-0001 transitions ready -> in-progress and links PR
        event_file.write_text(
            json.dumps(
                {
                    "action": "opened",
                    "pull_request": {
                        "number": 15,
                        "state": "open",
                        "merged": False,
                        "title": "feat: implement SPEC-0001",
                        "body": "Implements SPEC-0001",
                    },
                }
            ),
            encoding="utf-8",
        )
        rc2, _, err2 = self._run_cli(
            [
                "--root",
                str(doc_base),
                "gh-event",
                "--event-name",
                "pull_request",
                "--event-path",
                str(event_file),
            ]
        )
        self.assertEqual(rc2, 0, msg=err2)
        fields, _ = doc2gh.parse_frontmatter(spec_path.read_text(encoding="utf-8"))
        self.assertEqual((fields or {}).get("status"), "in-progress")
        self.assertEqual((fields or {}).get("github_pr"), "#15")

        # 3. Issue comment slash command transitions SPEC-0001 -> done
        event_file.write_text(
            json.dumps(
                {
                    "action": "created",
                    "comment": {"body": "/doc2gh status SPEC-0001 done"},
                    "issue": {"number": 7},
                }
            ),
            encoding="utf-8",
        )
        rc3, _, err3 = self._run_cli(
            [
                "--root",
                str(doc_base),
                "gh-event",
                "--event-name",
                "issue_comment",
                "--event-path",
                str(event_file),
            ]
        )
        self.assertEqual(rc3, 0, msg=err3)
        fields, _ = doc2gh.parse_frontmatter(spec_path.read_text(encoding="utf-8"))
        self.assertEqual((fields or {}).get("status"), "done")
        self.assertEqual(doc2gh.validate_single_document(spec_path, "spec"), [])

    def test_ac11_optional_pull_request_creation_and_reuse_on_feature_branch(self) -> None:
        _, doc_base = create_doc2gh_fixture(self.root_path, branch="spec/0001-pr-flow")
        self._run_cli(["--root", str(doc_base), "new", "spec", "PR Flow Spec"])
        spec_path = doc_base / "specs" / "0001-pr-flow-spec.md"

        runner = FakeCommandRunner(
            origin_url="https://github.com/acme/demo-repo.git",
            branch="spec/0001-pr-flow",
        )

        # 1. Without --create-pr, no PR is created
        rc1, _, err1 = self._run_cli(["--root", str(doc_base), "init"], runner=runner)
        self.assertEqual(rc1, 0, msg=err1)
        self.assertEqual(len(runner.open_prs), 0)

        # 2. With --create-pr on feature branch, PR #10 is created and linked to SPEC-0001
        rc2, out2, err2 = self._run_cli(
            ["--root", str(doc_base), "init", "--create-pr"], runner=runner
        )
        self.assertEqual(rc2, 0, msg=err2)
        self.assertIn("Created Pull Request #10", out2)
        self.assertEqual(len(runner.open_prs), 1)
        fields, _ = doc2gh.parse_frontmatter(spec_path.read_text(encoding="utf-8"))
        self.assertEqual((fields or {}).get("github_pr"), "#10")

        # 3. Repeat run with --create-pr reuses existing PR #10 without creating a duplicate
        rc3, out3, err3 = self._run_cli(
            ["--root", str(doc_base), "init", "--create-pr"], runner=runner
        )
        self.assertEqual(rc3, 0, msg=err3)
        self.assertIn("Reusing existing Pull Request #10", out3)
        self.assertEqual(len(runner.open_prs), 1)

        # 4. On default branch 'main', --create-pr exits nonzero
        main_runner = FakeCommandRunner(
            origin_url="https://github.com/acme/demo-repo.git",
            branch="main",
        )
        rc4, _, err4 = self._run_cli(
            ["--root", str(doc_base), "init", "--create-pr"], runner=main_runner
        )
        self.assertEqual(rc4, 1)
        self.assertIn("Cannot create a Pull Request from default/base branch 'main'", err4)

    def test_nfr03_partial_failure_reports_completed_actions_and_safe_retry(self) -> None:
        _, doc_base = create_doc2gh_fixture(self.root_path)
        self._run_cli(["--root", str(doc_base), "new", "spec", "Retry Spec"])

        failing_runner = FakeCommandRunner(
            origin_url="https://github.com/acme/demo-repo.git",
            issue_create_fails=True,
        )
        rc_fail, _, err_fail = self._run_cli(
            ["--root", str(doc_base), "init"], runner=failing_runner
        )
        self.assertEqual(rc_fail, 1)
        self.assertIn("Partial setup completed before failure:", err_fail)
        self.assertIn("Completed: Configured 4 workflow link(s)", err_fail)
        self.assertIn("Completed: Provisioned GitHub Project", err_fail)
        self.assertIn("Failed during: document-to-GitHub Issue synchronization", err_fail)
        self.assertIn("Safe to retry", err_fail)

        # Retry after transient issue failure resolves
        failing_runner.issue_create_fails = False
        rc_retry, _, err_retry = self._run_cli(
            ["--root", str(doc_base), "init"], runner=failing_runner
        )
        self.assertEqual(rc_retry, 0, msg=err_retry)
        self.assertEqual(len(failing_runner.projects), 1)
        self.assertEqual(len(failing_runner.issues), 1)


if __name__ == "__main__":
    unittest.main()
