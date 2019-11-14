import os
import re
import sys
import json
import subprocess
import github
import click
import requests
from pathlib import Path
from wasabi import msg, color

# Hack to make urllib3 SSL support work on older macOS Python builds
# (In particular, as of 2018-08-24, this is necessary to allow multibuild's
# py35 to connect to github without "[SSL: TLSV1_ALERT_PROTOCOL_VERSION] tlsv1
# alert protocol version (_ssl.c:719)" errors.)
if sys.platform == "darwin":
    import urllib3.contrib.securetransport

    urllib3.contrib.securetransport.inject_into_urllib3()


LOGO_TEXT = """
█░░░█ █░░█ █▀▀ █▀▀ █░░ █░░░█ █▀▀█ ░▀░ █▀▀▀ █░░█ ▀▀█▀▀
█▄█▄█ █▀▀█ █▀▀ █▀▀ █░░ █▄█▄█ █▄▄▀ ▀█▀ █░▀█ █▀▀█ ░░█░░
░▀░▀░ ▀░░▀ ▀▀▀ ▀▀▀ ▀▀▀ ░▀░▀░ ▀░▀▀ ▀▀▀ ▀▀▀▀ ▀░░▀ ░░▀░░
"""
LOGO = color(LOGO_TEXT, fg=183)


class ENV:  # Environment variables
    BUILD_ROOT = "WHEELWRIGHT_ROOT"
    WHEELS_DIR = "WHEELWRIGHT_WHEELS_DIR"
    REPO_NAME = "WHEELWRIGHT_REPO"
    GH_SECRET = "GITHUB_SECRET_TOKEN"


ROOT = Path(os.environ.get(ENV.BUILD_ROOT, Path(__file__).parent))
WHEELS_DIR = Path(os.environ.get(ENV.WHEELS_DIR, ROOT / "wheels"))
SECRET_FILE = "github-secret-token.txt"
# We substitute the project name into this string to get the URL to clone:
DEFAULT_CLONE_TEMPLATE = "https://github.com/{}.git"

# Uncomment this for more GitHub integration debugging info
# github.enable_console_debug_logging()


@click.group()
def cli():
    """Build release wheels for Python projects"""
    pass


@cli.command(name="build")
@click.argument("repo", required=True)
@click.argument("commit", required=True)
@click.option("--package-name", help="Python package name, if different from repo")
@click.option("--llvm", is_flag=True, help="Requires LLVM to be installed")
def build(repo, commit, package_name=None, llvm=False):
    """Build wheels for a given repo and commit / tag."""
    print(LOGO)
    repo_id = get_repo_id()
    user, package = repo.split("/", 1)
    if package_name is None:
        package_name = package
    msg.info(f"Building in repo {repo_id}")
    msg.info(f"Building wheels for {user}/{package}\n")
    clone_url = DEFAULT_CLONE_TEMPLATE.format(f"{user}/{package}")
    repo = get_gh().get_repo(repo_id)
    with msg.loading("Finding a unique name for this release..."):
        # Pick the release_name by finding an unused one
        i = 1
        while True:
            release_name = f"{package_name}-{commit}"
            if i > 1:
                release_name += f"-{i}"
            try:
                repo.get_release(release_name)
            except github.UnknownObjectException:
                break
            i += 1
    branch_name = f"branch-for-{release_name}"
    bs = {
        "clone-url": clone_url,
        "package-name": package_name,
        "commit": commit,
        "options": {"llvm": llvm},
        "upload-to": {
            "type": "github-release",
            "repo-id": repo_id,
            "release-id": release_name,
        },
    }
    bs_json = json.dumps(bs)
    bs_json_formatted = json.dumps(bs, indent=4)
    msg.text(f"Creating release {release_name} to collect assets")
    release_text = f"https://github.com/{user}/{package}\n\n### Build spec\n\n```json\n{bs_json_formatted}\n```"
    release = repo.create_git_release(release_name, release_name, release_text)
    with msg.loading("Creating build branch..."):
        # 'master' is a 'Commit'. 'master.commit' is a 'GitCommit'. These are
        # different types that are mostly *not* interchangeable:
        #   https://pygithub.readthedocs.io/en/latest/github_objects/Commit.html
        #   https://pygithub.readthedocs.io/en/latest/github_objects/GitCommit.html
        master = repo.get_commit("master")
        master_gitcommit = master.commit
        patch = github.InputGitTreeElement(
            "build-spec.json", "100644", "blob", content=bs_json,
        )
        tree = repo.create_git_tree([patch], master_gitcommit.tree)
        our_gitcommit = repo.create_git_commit(
            f"Building: {release_name}", tree, [master_gitcommit]
        )
        repo.create_git_ref(f"refs/heads/{branch_name}", our_gitcommit.sha)
    msg.good(f"Commit is {our_gitcommit.sha[:8]} in branch {branch_name}")
    checks = f"https://github.com/{user}/{package}/commit/{our_gitcommit.sha}/checks"
    msg.text(f"Release: {release.html_url}")
    msg.text(f"Checks:  {checks}")


@cli.command(name="download")
@click.argument("release-id")
def download_release_assets(release_id):
    """Download existing wheels for a release ID (name of build repo tag)."""
    print(LOGO)
    repo_id = get_repo_id()
    msg.info(f"Downloading from repo {repo_id}")
    download_path = WHEELS_DIR / release_id
    msg.info(f"Downloading to {download_path}/...")
    if not download_path.exists():
        download_path.mkdir(parents=True)
    with requests.Session() as s:
        release = get_release(repo_id, release_id)
        for asset in release.get_assets():
            print(f"  - {asset.name}")
            save_path = download_path / asset.name
            r = s.get(asset.browser_download_url)
            with save_path.open("wb") as f:
                f.write(r.content)
    msg.good("All done!", f"See {download_path}/ for your wheels.")


def get_gh():
    token_path = ROOT / SECRET_FILE
    if ENV.GH_SECRET in os.environ:
        token = os.environ[ENV.GH_SECRET]
    elif token_path.exists():
        with token_path.open("r", encoding="utf-8") as f:
            token = f.read().strip()
    else:
        err = f"Can't find GitGub token. Not {ENV.GH_SECRET} envvar or in {token_path}"
        msg.fail(err, exits=1)
    return github.Github(token)


def get_release(repo_id, release_id):
    gh = get_gh()
    repo = gh.get_repo(repo_id)
    # https://pygithub.readthedocs.io/en/latest/github_objects/GitRelease.html
    release = repo.get_release(release_id)
    if release is None:
        msg.fail(f"Release not found: {release_id}", exits=1)
    return release


def get_repo_id():
    if ENV.REPO_NAME in os.environ:
        return os.environ[ENV.REPO_NAME]
    # detect current GitHub repo from working directory
    try:
        cmd = ["git", "config", "--get", "remote.origin.url"]
        result = subprocess.check_output(cmd)
        git_url = result.decode("utf-8").strip()
        git_ssh = re.match(r"git@github\.com:(.*/.*)\.git$", git_url)
        if git_ssh:
            return git_ssh.groups()[0]
        git_https = re.match(r"https://github\.com/(.*/.*)\.git$", git_url)
        if git_https:
            return git_https.groups()[0]
    except subprocess.CalledProcessError:
        pass
    msg.fail(
        f"Error: Not a valid repository: {Path.cwd()}.",
        f"Make sure you're in the build repo directory or use the "
        f"{ENV.REPO_NAME} environment variable to specify the <user>/<repo> "
        f"build repository.",
        exits=1,
    )


if __name__ == "__main__":
    cli()
