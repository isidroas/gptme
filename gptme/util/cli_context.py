import glob
import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import click
from rich import print as rich_print
from rich.filesize import decimal
from rich.markup import escape
from rich.text import Text
from rich.tree import Tree

from . import console

logger = logging.getLogger(__name__)


def _git(cmd: list[str], check: bool = True, timeout: int = 10) -> tuple[str, bool]:
    """Run a git command and return its output and success status."""
    try:
        env = os.environ.copy()
        env.update(
            {
                "PAGER": "cat",
                "GIT_PAGER": "cat",
                "GIT_TERMINAL_PROMPT": "0",  # Disable git's terminal prompts
            }
        )
        logger.debug(f"Running git command: {cmd}")
        result = subprocess.run(
            ["git"] + cmd,
            capture_output=True,
            text=True,
            check=check,
            env=env,
            timeout=timeout,
        )
        if result.stderr:
            logger.debug(f"Git stderr: {result.stderr}")
        if result.stdout:
            logger.debug(f"Git stdout: {result.stdout}")
        return result.stdout.strip(), True
    except subprocess.TimeoutExpired:
        logger.error(f"Git command timed out after {timeout}s: git {' '.join(cmd)}")
        return "", False
    except subprocess.CalledProcessError as e:
        if check:
            logger.error(f"Git command failed: {e}")
            logger.error(f"Git stderr: {e.stderr}")
        return e.stderr.strip(), False


@click.group()
def context():
    """Commands for context generation."""
    pass


@context.command("git")
@click.option("--branch", help="Specific branch to analyze")
@click.option(
    "--max-files", type=int, default=10, help="Maximum number of files to include"
)
@click.option(
    "--show-diff/--no-diff",
    default=True,
    help="Show diffs of staged and unstaged changes",
)
def context_git(
    branch: str | None,
    max_files: int,
    show_diff: bool,
):
    """Generate a prompt about the current git repository, including git status, diffs, and recent commits."""
    # NOTE: this could be a lot easier with a simple call to `git status -vv`

    logger = logging.getLogger(__name__)
    print("## Git")

    def format_section(title: str, items: list[str]) -> list[str]:
        """Format a section with title and items."""
        if not items:
            return []

        result = [f"\n### {title}"]

        for item in items:
            item_prefix = "- "
            result.append(f"{item_prefix}{item}")
        return result

    # Check if we're in a git repo
    logger.debug("Checking if in git repo...")
    output, success = _git(["rev-parse", "--git-dir"])
    logger.debug(f"Git repo check result: {success=}, {output=}")
    if not success:
        logger.error("Not a git repository")
        return

    sections = []

    # Basic repo info
    remote_url, success = _git(["config", "--get", "remote.origin.url"])
    if success and remote_url:
        sections.extend([f"Repository: {remote_url}"])

    # Get current branch
    branch_name, success = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    if success:
        if branch_name == "HEAD":
            # We're in detached HEAD state
            commit_hash, _ = _git(["rev-parse", "--short", "HEAD"])
            sections.append(f"HEAD is detached at {commit_hash}")
            branch_name = ""
        else:
            sections.append(f"Current branch: {branch_name}")

    # Recent commits
    log_format = "--pretty=format:%h (%ad) %s"
    commits_output, success = _git(
        [
            "log",
            log_format,
            "--date=format:%Y-%m-%d %H:%M",
            "-n",
            "5",
            branch or branch_name or "HEAD",
        ]
    )
    if success and commits_output:
        commit_items = commits_output.split("\n")
        sections.extend(format_section("Recent commits", commit_items))

    # Staged files
    staged_files, success = _git(["diff", "--name-only", "--cached"])
    if success and staged_files:
        files = staged_files.split("\n")
        if files and files[0]:
            shown_files = files[:max_files]
            sections.extend(format_section("Staged files", shown_files))
            if len(files) > max_files:
                sections.append(f"... and {len(files) - max_files} more staged files")

    # Changed files
    changed_files, success = _git(["diff", "--name-only"])

    if success and changed_files:
        files = changed_files.split("\n")
        if files and files[0]:
            shown_files = files[:max_files]
            sections.extend(format_section("Changed files (unstaged)", shown_files))
            if len(files) > max_files:
                sections.append(f"... and {len(files) - max_files} more changed files")

    # Untracked files
    untracked_files, success = _git(["ls-files", "--others", "--exclude-standard"])
    if success and untracked_files:
        files = untracked_files.split("\n")
        if files and files[0]:
            shown_files = files[:max_files]
            sections.extend(format_section("Untracked files", shown_files))
            if len(files) > max_files:
                sections.append(
                    f"... and {len(files) - max_files} more untracked files"
                )

    # Add diffs if requested
    if show_diff:
        # Add staged changes
        staged_diff, success = _git(["diff", "--cached"])
        if success and staged_diff:
            sections.extend(
                ["\n### Staged changes", f"\n{codeblock("diff", staged_diff)}"]
            )

        # Add unstaged changes
        unstaged_diff, success = _git(["diff"])
        if success and unstaged_diff:
            sections.extend(
                ["\n### Unstaged changes", f"\n{codeblock("diff", unstaged_diff)}"]
            )

    print("\n".join(sections))


@context.command("journal")
@click.option("--days", type=int, default=7, help="Number of days to look back")
@click.option(
    "--path",
    type=click.Path(exists=True),
    help="Journal directory path (optional)",
)
def context_journal(days: int, path: str | None, silent_fail: bool = True):
    """Generate a prompt from journal entries."""

    logger = logging.getLogger(__name__)

    # Common journal locations to try
    locations = [
        path,  # User-specified path first
        os.path.expanduser("~/journal"),
        os.path.expanduser("~/Documents/journal"),
        os.path.expanduser("~/notes"),
        os.path.expanduser("~/Documents/notes"),
    ]

    journal_dir = None
    for loc in locations:
        if loc and os.path.exists(loc):
            journal_dir = loc
            if loc != path:  # Only log if we're using a default location
                logger.info(f"Using journal directory: {loc}")
            break

    if not journal_dir:
        locations_str = "\n  ".join(
            [loc for loc in locations[1:] if loc]
        )  # Skip None from path
        if not silent_fail:
            print(f"No journal directory found. Tried:\n  {locations_str}")
            print("\nPlease specify a path with --path")
        return False

    # Get dates for the last N days
    dates = [
        (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)
    ]

    entries = []
    for date in dates:
        # Look for files matching the date pattern
        pattern = os.path.join(journal_dir, f"*{date}*.md")
        files = glob.glob(pattern)

        for file in files:
            with open(file) as f:
                content = f.read()
                entries.append(f"\n# {date}\n{content}")

    if entries:
        print(f"Journal entries from the last {days} days:\n")
        print("\n".join(entries))
    else:
        print(f"No journal entries found for the last {days} days")


def get_file_type(path: str) -> str:
    """Get file type from extension."""
    ext = os.path.splitext(path)[1].lower()
    if not ext:
        return "no extension"
    return ext[1:]  # Remove the dot


def list_files(path: str, excludes: list[str]) -> list[tuple[str, int]]:
    """List all files with their sizes, respecting excludes."""
    result = []
    for root, dirs, files in os.walk(path):
        # Skip excluded directories
        dirs[:] = [
            d
            for d in dirs
            if not any(
                os.path.join(root, d).startswith(os.path.join(path, e))
                for e in excludes
            )
        ]

        for file in files:
            file_path = os.path.join(root, file)
            # Skip excluded files
            if any(file_path.startswith(os.path.join(path, e)) for e in excludes):
                continue
            try:
                size = os.path.getsize(file_path)
                rel_path = os.path.relpath(file_path, path)
                result.append((rel_path, size))
            except OSError:
                continue
    return result


def walk_directory(
    directory: Path,
    tree: Tree,
    excludes: list[str] | None = None,
    max_depth: int | None = None,
    depth: int = 1,
    show_size: bool = True,
    icons: bool = False,
) -> None:
    """Recursively build a Tree with directory contents."""
    if excludes is None:
        excludes = []

    if max_depth is not None and depth > max_depth:
        return

    try:
        # Sort dirs first then by filename
        paths = sorted(
            Path(directory).iterdir(),
            key=lambda path: (path.is_file(), path.name.lower()),
        )

        for path in paths:
            # Skip excluded paths with fnmatch
            if any(path.match(e) for e in excludes):
                continue

            try:
                if path.is_dir():
                    style = "dim" if path.name.startswith("__") else ""
                    branch = tree.add(
                        f"[bold magenta]{':open_file_folder: ' if icons else ''}[link file://{path}]{escape(path.name)}/",
                        style=style,
                        guide_style=style,
                    )
                    walk_directory(
                        path, branch, excludes, max_depth, depth + 1, show_size
                    )
                else:
                    text_filename = Text(path.name, "green")
                    text_filename.highlight_regex(r"\..*$", "bold red")
                    text_filename.stylize(f"link file://{path}")

                    if show_size:
                        file_size = path.stat().st_size
                        text_filename.append(f" ({decimal(file_size)})", "blue")

                    # Choose icon based on file type
                    icon = "🐍 " if path.suffix == ".py" else "📄 "
                    tree.add((Text(icon if icons else "")) + text_filename)
            except OSError as e:
                tree.add(f"[red]{path.name} [Error: {e}]")

    except PermissionError:
        tree.add("[red][Permission denied]")
    except OSError as e:
        tree.add(f"[red][Error: {e}]")


def print_tree(
    path: str,
    excludes: list[str] | None = None,
    max_depth: int | None = None,
    show_size: bool = False,
    icons: bool = False,
) -> None:
    """Print directory structure as a rich tree.

    Args:
        path: Path to print tree for
        excludes: List of patterns to exclude
        max_depth: Maximum depth to traverse
        show_size: Whether to show file sizes
    """

    abs_path = os.path.abspath(path)
    tree = Tree(
        f":open_file_folder: [link file://{abs_path}]{abs_path}" if icons else abs_path,
        guide_style="bold bright_blue",
    )
    walk_directory(Path(path), tree, excludes, max_depth, show_size=show_size)
    rich_print(tree)


def show_file_contents(file_path: str) -> None:
    """Show contents of a file."""
    try:
        with open(file_path) as f:
            content = f.read().strip()
            if content:
                console.print(codeblock(file_path, content))
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")


def codeblock(langtag: str, content: str) -> str:
    """Wrap content in a markdown code block with langtag."""
    return f"```{langtag}\n{content}\n```"


def read_gitignore(path: str) -> list[str]:
    """Read .gitignore file and return list of patterns."""
    gitignore_path = os.path.join(path, ".gitignore")
    ignores = []
    if os.path.exists(gitignore_path):
        with open(gitignore_path) as f:
            ignores += [
                line.strip() for line in f if line.strip() and not line.startswith("#")
            ]
    # check global gitignore
    global_gitignore_path = os.path.expanduser("~/.config/git/ignore")
    if os.path.exists(global_gitignore_path):
        with open(global_gitignore_path) as f:
            ignores += [
                line.strip() for line in f if line.strip() and not line.startswith("#")
            ]
    return ignores


@context.command("workspace")
@click.option(
    "--path", type=click.Path(exists=True), default=".", help="Workspace path"
)
@click.option("--max-depth", type=int, default=1, help="Maximum depth to show in tree")
def context_workspace(path: str, max_depth: int):
    """Generate a prompt about the current workspace directory structure.

    Shows the directory structure as a tree and provides statistics about file types
    and sizes. Can optionally show contents of important files like README and
    configuration files.

    Respects .gitignore if present. Useful for giving an AI assistant context about
    the project structure.
    """
    # Build excludes list from .gitignore
    excludes = read_gitignore(path) + [".git"]

    print("## Workspace structure\n\n```tree")
    print_tree(path, excludes=excludes, max_depth=max_depth)
    print("```")
