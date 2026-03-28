import logging
import os
import subprocess

logger = logging.getLogger(__name__)


class GitAdapter:
    """Implements VCSPort via git CLI."""

    def __init__(self, repo_path: str):
        self.repo_path = os.path.abspath(repo_path)

    def init_repo(self) -> None:
        git_dir = os.path.join(self.repo_path, ".git")
        if os.path.isdir(git_dir):
            logger.debug("Git repo already exists at %s", self.repo_path)
            return
        self._run(["git", "init"])
        logger.info("Initialized git repo at %s", self.repo_path)

    def commit_all(self, message: str) -> None:
        self._run(["git", "add", "-A"])
        result = self._run(
            ["git", "diff", "--cached", "--quiet"],
            check=False,
        )
        if result.returncode == 0:
            logger.debug("No staged changes to commit")
            return
        self._run(["git", "commit", "-m", message])
        logger.debug("Committed: %s", message)

    def _run(
        self,
        cmd: list[str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=check,
        )
