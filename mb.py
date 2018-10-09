import os
import os.path
import sys
import glob
import json
import subprocess
from contextlib import contextmanager
import time

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
ENV_BUILD_ROOT = 'WHEELWRIGHT_ROOT'
ENV_WHEELS_DIR = 'WHEELWRIGHT_WHEELS_DIR'
ENV_REPO_NAME  = 'WHEELWRIGHT_REPO'
ENV_GH_SECRET  = 'GITHUB_SECRET_TOKEN'

ROOT = Path(os.environ.get(ENV_BUILD_ROOT, Path(__file__).parent))
WHEELS_DIR = Path(os.environ.get(ENV_WHEELS_DIR, Path(__file__).parent / 'wheels'))
SECRET_FILE = 'github-secret-token.txt'

# We substitute the project name into this string to get the URL to clone:
DEFAULT_CLONE_TEMPLATE = "https://github.com/{}.git"

# All the statuses we want to wait for, maps github name -> our display name
STATUSES = {
    "continuous-integration/appveyor/branch": "Appveyor",
    "continuous-integration/travis-ci/push": "Travis",
}
NA_STATE = "n/a"
FINAL_STATES = {"error", "failure", "success"}
BAD_STATES = {"error", "failure"}
STATUS_COLORS = {
    'pending': 'blue',
    'success': 'green',
    'failure': 'red',
    'error': 'red'
}


#github.enable_console_debug_logging()

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
        with token_path.open('r', encoding='utf-8') as f:
            token = f.read().strip()
    else:
        raise RuntimeError(f"Can't find Github token (checked {ENV_GH_SECRET} "
                           f"envvar and {token_path})")
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
        result = subprocess.check_output(['git', 'config', '--get', 'remote.origin.url'])
        git_url = result.decode('utf-8').strip()
        return '/'.join(git_url.split('.git')[0].rsplit('/', 2)[1:3])
    except subprocess.CalledProcessError:
        click.secho(f'Error: Not a valid repository: {Path.cwd()}.', fg='red')
        click.secho(f"Make sure you're in the build repo directory or use the "
                    f"{ENV_REPO_NAME} environment variable to specify the "
                    f"<user>/<repo> build repository.")
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
    click.secho(f"Downloading to {download_path}/...", fg='yellow')
    if not download_path.exists():
        download_path.mkdir(parents=True)
    with requests.Session() as s:
        release = get_release(repo_id, release_id)
        for asset in release.get_assets():
            click.secho("  - " + asset.name)
            save_path = download_path / asset.name
            r = s.get(asset.browser_download_url)
            with save_path.open('wb') as f:
                f.write(r.content)
    click.secho('')
    click.secho("\u2714 All done!", fg='green')
    click.secho(f"See {download_path}/ for your wheels.", fg='green')


################################################################


@click.group()
def cli():
    """Build release wheels for Python projects"""
    pass


@cli.command(name='build-spec')
@click.argument(
    "build_spec",
    type=click.Path(exists=True, dir_okay=False),
    required=True
)
def build_spec_to_shell(build_spec):
    bs = get_build_spec(build_spec)
    sys.stdout.write(
        "BUILD_SPEC_CLONE_URL='{clone-url}'\n"
        "BUILD_SPEC_COMMIT='{commit}'\n"
        "BUILD_SPEC_PACKAGE_NAME='{package-name}'\n"
        .format(**bs)
    )


@cli.command(name='upload')
@click.option(
    "--build-spec",
    type=click.Path(exists=True, dir_okay=False),
    required=True
)
@click.argument(
    "paths", nargs=-1, type=click.Path(exists=True)
)
def upload(build_spec, paths):
    bs = get_build_spec(build_spec)
    _do_upload(bs, paths)


@cli.command(name='appveyor-build')
@click.option(
    "--build-spec",
    type=click.Path(exists=True, dir_okay=False),
    required=True
)
def appveyor_build(build_spec):
    bs = get_build_spec(build_spec)
    run(["git", "clone", bs["clone-url"], "checkout"])
    run(["pip", "install", "-Ur", "checkout\\requirements.txt"])
    with cd("checkout"):
        run(["git", "checkout", bs["commit"]])
        run(["python", "setup.py", "bdist_wheel"])
    wheels = glob.glob("checkout\\dist\\*.whl")
    run(["pip", "install"] + wheels)
    os.mkdir("tmp_for_test")
    with cd("tmp_for_test"):
        run(["pytest", "--pyargs", bs["package-name"]])
    _do_upload(bs, wheels)


@cli.command(name="build")
@click.argument("repo", required=True)
@click.argument("commit", required=True)
def build(repo, commit):
    """Build wheels for a given repo and commit / tag."""
    click.secho(LOGO, fg='cyan')
    repo_id = _get_repo_id()
    user, package_name = repo.split('/', 1)
    click.secho(f"Building in repo {repo_id}")
    click.secho(f"Building wheels for {user}/{package_name}\n")
    clone_url = DEFAULT_CLONE_TEMPLATE.format(f"{user}/{package_name}")
    repo = get_gh().get_repo(repo_id)

    click.secho("Finding a unique name for this release...", fg='yellow')
    # Pick the release_name by finding an unused one
    i = 1
    while True:
        release_name = "{}-{}-wheels".format(package_name, commit)
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

    click.secho(f"Creating release {release_name} to collect assets...", fg='yellow')
    release = repo.create_git_release(
        release_name,
        release_name,
        "Build spec:\n\n```json\n{}\n```".format(json.dumps(bs, indent=4)),
    )
    print(release.html_url)
    click.secho("Creating build branch...", fg='yellow')
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
    print(f"Commit is {our_gitcommit.sha[:8]} in branch {branch_name}.")

    click.secho("Waiting for build to complete...", fg='yellow')
    # get_combined_status needs a Commit, not a GitCommit
    our_commit = repo.get_commit(our_gitcommit.sha)
    showed_urls = {}
    while True:
        time.sleep(10)
        combined_status = our_commit.get_combined_status()
        display_name_to_state = {}
        for display_name in STATUSES.values():
            display_name_to_state[display_name] = NA_STATE
        for status in combined_status.statuses:
            if status.context in STATUSES:
                display_name = STATUSES[status.context]
                display_name_to_state[display_name] = status.state
                if display_name not in showed_urls:
                    print("{} logs: {}".format(
                        display_name, status.target_url
                    ))
                    showed_urls[display_name] = status.target_url

        displays = [
            click.style(f"[{name} - {state}]", fg=STATUS_COLORS.get(state, 'white'))
            for name, state in display_name_to_state.items()
        ]
        click.echo(" ".join(displays))
        pending = False
        failed = False
        # The Github states are: "error", "failure", "success", "pending"
        for state in display_name_to_state.values():
            if state == NA_STATE:
                continue
            if state not in FINAL_STATES:
                pending = True
            if state in BAD_STATES:
                failed = True
        if failed or not pending:
            break

    if failed:
        click.secho("*** Failed! ***", bg='red', fg='black')
        for display_name, url in showed_urls.items():
            print(f"{display_name} logs: {url}")
        sys.exit(1)
    else:
        _download_release_assets(repo_id, release_name)


@cli.command(name="download")
@click.argument("release-id", required=True)
def download_release_assets(release_id):
    """Download existing wheels for a release ID (name of build repo tag)."""
    click.secho(LOGO, fg='cyan')
    repo_id = _get_repo_id()
    click.secho(f"Downloading from repo {repo_id}")
    _download_release_assets(repo_id, release_id)


if __name__ == "__main__":
    cli()
