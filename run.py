import os
import os.path
import re
import sys
import glob
import shutil
import json
import subprocess
from contextlib import contextmanager
import github
import click
import requests
from pathlib import Path


LOGO = """
┬ ┬┬ ┬┌─┐┌─┐┬  ┬ ┬┬─┐┬┌─┐┬ ┬┌┬┐
│││├─┤├┤ ├┤ │  │││├┬┘││ ┬├─┤ │
└┴┘┴ ┴└─┘└─┘┴─┘└┴┘┴└─┴└─┘┴ ┴ ┴
"""

# Environment variables
ENV_BUILD_ROOT = "WHEELWRIGHT_ROOT"
ENV_WHEELS_DIR = "WHEELWRIGHT_WHEELS_DIR"
ENV_REPO_NAME = "WHEELWRIGHT_REPO"
ENV_GH_SECRET = "GITHUB_SECRET_TOKEN"

ROOT = Path(os.environ.get(ENV_BUILD_ROOT, Path(__file__).parent))
WHEELS_DIR = Path(os.environ.get(ENV_WHEELS_DIR, ROOT / "wheels"))
SECRET_FILE = "github-secret-token.txt"

# We substitute the project name into this string to get the URL to clone:
DEFAULT_CLONE_TEMPLATE = "https://github.com/{}.git"

# github.enable_console_debug_logging()

# Hack to make urllib3 SSL support work on older macOS Python builds
# (In particular, as of 2018-08-24, this is necessary to allow multibuild's
# py35 to connect to github without "[SSL: TLSV1_ALERT_PROTOCOL_VERSION] tlsv1
# alert protocol version (_ssl.c:719)" errors.)
if sys.platform == "darwin":
    import urllib3.contrib.securetransport

    urllib3.contrib.securetransport.inject_into_urllib3()


def get_gh():
    token_path = ROOT / SECRET_FILE
    if ENV_GH_SECRET in os.environ:
        token = os.environ[ENV_GH_SECRET]
    elif token_path.exists():
        with token_path.open("r", encoding="utf-8") as f:
            token = f.read().strip()
    else:
        raise RuntimeError(
            "Can't find Github token (checked {} envvar and {}".format(
                ENV_GH_SECRET, token_path
            )
        )
    return github.Github(token)


def get_release(repo_id, release_id):
    gh = get_gh()
    repo = gh.get_repo(repo_id)
    # https://pygithub.readthedocs.io/en/latest/github_objects/GitRelease.html
    release = repo.get_release(release_id)
    if release is None:
        raise RuntimeError("Release not found:", release_id)
    return release


def get_build_spec(build_spec_path):
    with open(build_spec_path) as f:
        return json.load(f)


@contextmanager
def cd(d):
    orig_dir = os.getcwd()
    try:
        os.chdir(d)
        yield
    finally:
        os.chdir(orig_dir)


def run(cmd):
    print("Running:", cmd)
    subprocess.check_call(cmd)


def _get_repo_id():
    if ENV_REPO_NAME in os.environ:
        return os.environ[ENV_REPO_NAME]
    # detect current GitHub repo from working directory
    # TODO: make less hacky? We could read from the .git/config, but that'd be
    # even more messy
    try:
        result = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"]
        )
        git_url = result.decode("utf-8").strip()
        git_ssh = re.match(r"git@github\.com:(.*/.*)\.git$", git_url)
        if git_ssh:
            return git_ssh.groups()[0]
        git_https = re.match(r"https://github\.com/(.*/.*)\.git$", git_url)
        if git_https:
            return git_https.groups()[0]
    except subprocess.CalledProcessError:
        pass
    click.secho("Error: Not a valid repository: {}.".format(Path.cwd()), fg="red")
    click.secho(
        "Make sure you're in the build repo directory or use the "
        "{} environment variable to specify the <user>/<repo> "
        "build repository.".format(ENV_REPO_NAME)
    )
    sys.exit(1)


def _do_upload(bs, paths):
    upload_config = bs["upload-to"]
    assert upload_config["type"] == "github-release"
    release = get_release(upload_config["repo-id"], upload_config["release-id"])
    # This is a gross hack, to work around the lack of globbing on Windows
    # (see https://github.com/pallets/click/issues/1096)
    # We accept either individual files, or directories, and for directories,
    # we upload all the .whl files directly inside that directory (no
    # recursion).
    for given_path in paths:
        if os.path.isdir(given_path):
            subpaths = glob.glob(os.path.join(given_path, "*.whl"))
        else:
            subpaths = [given_path]
        for actual_path in subpaths:
            print("Uploading:", actual_path)
            asset = release.upload_asset(actual_path)
            print(asset)
            print(asset.name, asset.id, asset.state, asset.created_at)


def _download_release_assets(repo_id, release_id):
    download_path = WHEELS_DIR / release_id
    click.secho("Downloading to {}/...".format(download_path), fg="yellow")
    if not download_path.exists():
        download_path.mkdir(parents=True)
    with requests.Session() as s:
        release = get_release(repo_id, release_id)
        for asset in release.get_assets():
            click.secho("  - " + asset.name)
            save_path = download_path / asset.name
            r = s.get(asset.browser_download_url)
            with save_path.open("wb") as f:
                f.write(r.content)
    click.secho("")
    click.secho("\u2714 All done!", fg="green")
    click.secho("See {}/ for your wheels.".format(download_path), fg="green")


################################################################


@click.group()
def cli():
    """Build release wheels for Python projects"""
    pass


@cli.command(name="build-spec")
@click.argument(
    "build_spec", type=click.Path(exists=True, dir_okay=False), required=True
)
def build_spec_to_shell(build_spec):
    bs = get_build_spec(build_spec)
    sys.stdout.write(
        "BUILD_SPEC_CLONE_URL='{clone-url}'\n"
        "BUILD_SPEC_COMMIT='{commit}'\n"
        "BUILD_SPEC_PACKAGE_NAME='{package-name}'\n".format(**bs)
    )
    release_id = bs.get("upload-to", {}).get("release-id", "")
    sys.stdout.write("BUILD_SPEC_RELEASE_ID='{}'\n".format(release_id))


@cli.command(name="upload")
@click.option(
    "--build-spec", type=click.Path(exists=True, dir_okay=False), required=True
)
@click.argument("paths", nargs=-1, type=click.Path(exists=True))
def upload(build_spec, paths):
    bs = get_build_spec(build_spec)
    _do_upload(bs, paths)


@cli.command(name="windows-build")
@click.option(
    "--build-spec", type=click.Path(exists=True, dir_okay=False), required=True
)
def appveyor_build(build_spec):
    bs = get_build_spec(build_spec)
    run(["git", "clone", bs["clone-url"], "checkout"])
    with cd("checkout"):
        run(["git", "checkout", bs["commit"]])
        run(["pip", "install", "-Ur", "requirements.txt"])
        run(["python", "setup.py", "bdist_wheel"])
    wheels = []
    for wheel in glob.glob("checkout\\dist\\*.whl"):
        # No idea what I'm doing here... https://github.com/pypa/pip/issues/6951
        if "cp38m-win" in wheel:
            fixed_wheel = wheel.replace("cp38m-win", "cp38-win")
            shutil.move(wheel, fixed_wheel)
            wheels.append(fixed_wheel)
        else:
            wheels.append(wheel)
    run(["pip", "install"] + wheels)
    os.mkdir("tmp_for_test")
    with cd("tmp_for_test"):
        run(["pytest", "--pyargs", bs["package-name"]])


@cli.command(name="build")
@click.argument("repo", required=True)
@click.argument("commit", required=True)
@click.option("--package-name")
def build(repo, commit, package_name=None):
    """Build wheels for a given repo and commit / tag."""
    click.secho(LOGO, fg="cyan")
    repo_id = _get_repo_id()
    user, package = repo.split("/", 1)
    if package_name is None:
        package_name = package
    click.secho("Building in repo {}".format(repo_id))
    click.secho("Building wheels for {}/{}\n".format(user, package))
    clone_url = DEFAULT_CLONE_TEMPLATE.format("{}/{}".format(user, package))
    repo = get_gh().get_repo(repo_id)
    click.secho("Finding a unique name for this release...", fg="yellow")
    # Pick the release_name by finding an unused one
    i = 1
    while True:
        release_name = "{}-{}".format(package_name, commit)
        if i > 1:
            release_name += "-{}".format(i)
        try:
            repo.get_release(release_name)
        except github.UnknownObjectException:
            break
        i += 1
    branch_name = "branch-for-" + release_name
    bs = {
        "clone-url": clone_url,
        "package-name": package_name,
        "commit": commit,
        "upload-to": {
            "type": "github-release",
            "repo-id": repo_id,
            "release-id": release_name,
        },
    }
    bs_json = json.dumps(bs)
    click.secho(
        "Creating release {} to collect assets...".format(release_name), fg="yellow"
    )
    release_template = "https://github.com/{}/{}\n\n### Build spec\n\n```json\n{}\n```"
    release = repo.create_git_release(
        release_name,
        release_name,
        release_template.format(user, package, json.dumps(bs, indent=4)),
    )
    click.secho("Creating build branch...", fg="yellow")
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
        "Building: {}".format(release_name), tree, [master_gitcommit]
    )
    repo.create_git_ref("refs/heads/" + branch_name, our_gitcommit.sha)
    print("Commit is {} in branch {}".format(our_gitcommit.sha[:8], branch_name))
    checks_template = "https://github.com/{}/{}/commit/{}/checks"
    print("Release:", release.html_url)
    # TODO: use correct repo
    print("Checks: ", checks_template.format(user, package, our_gitcommit.sha))


@cli.command(name="download")
@click.argument("release-id", required=True)
def download_release_assets(release_id):
    """Download existing wheels for a release ID (name of build repo tag)."""
    click.secho(LOGO, fg="cyan")
    repo_id = _get_repo_id()
    click.secho("Downloading from repo {}".format(repo_id))
    _download_release_assets(repo_id, release_id)


if __name__ == "__main__":
    cli()
