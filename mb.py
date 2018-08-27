MAGIC_BUILD_REPO = "njsmith/cymem-wheels"
DEFAULT_GITHUB_CLONE_TEMPLATE = "https://github.com/explosion/{}.git"

# All the statuses we want to wait for
# maps github name -> our display name
STATUSES = {
    "continuous-integration/appveyor/branch": "appveyor",
    "continuous-integration/travis-ci/push": "travis",
}

import os
import os.path
import sys
import glob
import json
from textwrap import dedent
import subprocess
from contextlib import contextmanager
import time

import github
import click
import requests

#github.enable_console_debug_logging()

# Hack to make urllib3 SSL support work on older macOS Python builds
# (In particular, as of 2018-08-24, this is necessary to allow multibuild's
# py35 to connect to github without "[SSL: TLSV1_ALERT_PROTOCOL_VERSION] tlsv1
# alert protocol version (_ssl.c:719)" errors.)
if sys.platform == "darwin":
    import urllib3.contrib.securetransport
    urllib3.contrib.securetransport.inject_into_urllib3()


def get_gh():
    token_path = os.path.join(
        os.path.dirname(__file__), "github-secret-token.txt"
    )
    if "GITHUB_SECRET_TOKEN" in os.environ:
        token = os.environ["GITHUB_SECRET_TOKEN"]
    elif os.path.exists(token_path):
        with open("github-secret-token.txt") as f:
            token = f.read().strip()
    else:
        raise RuntimeError(
            "can't find github token (checked in GITHUB_SECRET_TOKEN envvar, "
            "and {}".format(token_path)
        )
    return github.Github(token)


def get_release(repo_id, release_id):
    gh = get_gh()
    repo = gh.get_repo(repo_id)
    # https://pygithub.readthedocs.io/en/latest/github_objects/GitRelease.html
    release = repo.get_release(release_id)
    if release is None:
        raise RuntimeError("release not found:", release_id)
    return release


def get_build_spec(build_spec_path):
    with open(build_spec_path) as f:
        return json.load(f)


################################################################


@click.group()
def cli():
    pass


@cli.command()
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


@cli.command()
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


@cli.command()
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


def _download_release_assets(repo_id, release_id):
    print("Downloading to {}/...".format(release_id))
    try:
        os.mkdir(release_id)
    except OSError:
        pass
    with requests.Session() as s:
        release = get_release(repo_id, release_id)
        for asset in release.get_assets():
            print("    " + asset.name)
            save_name = os.path.join(release_id, asset.name)
            r = s.get(asset.browser_download_url)
            with open(save_name, "wb") as f:
                f.write(r.content)
    print("...all done! See {}/ for your wheels.".format(release_id))


@cli.command(name="magic-build")
@click.option("--magic-build-repo-id", default=MAGIC_BUILD_REPO)
@click.option("--clone-url")
@click.argument("package-name", required=True)
@click.argument("commit", required=True)
def magic_build(magic_build_repo_id, clone_url, package_name, commit):
    if clone_url is None:
        clone_url = DEFAULT_GITHUB_CLONE_TEMPLATE.format(package_name)

    repo = get_gh().get_repo(magic_build_repo_id)

    print("Finding a unique name for this release...")
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
            "repo-id": MAGIC_BUILD_REPO,
            "release-id": release_name,
        },
    }
    bs_json = json.dumps(bs)

    print("Creating release {!r} to collect assets...".format(release_name))
    release = repo.create_git_release(
        release_name,
        release_name,
        "Build spec:\n\n```json\n{}\n```".format(bs_json),
    )
    print("  {}".format(release.html_url))

    print("Creating build branch...".format(MAGIC_BUILD_REPO))
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
    print("  Commit is {} in branch {!r}."
          .format(our_gitcommit.sha[:8], branch_name))

    print("Waiting for build to complete...")
    # get_combined_status needs a Commit, not a GitCommit
    our_commit = repo.get_commit(our_gitcommit.sha)
    showed_urls = set()
    while True:
        time.sleep(10)
        combined_status = our_commit.get_combined_status()
        display_name_to_state = {}
        for display_name in STATUSES.values():
            display_name_to_state[display_name] = "not available"
        for status in combined_status.statuses:
            if status.context in STATUSES:
                display_name = STATUSES[status.context]
                display_name_to_state[display_name] = status.state
                if display_name not in showed_urls:
                    print("  {}: {}".format(display_name, status.target_url))
                    showed_urls.add(display_name)
        displays = [
            "[{} - {}]".format(display_name, state)
            for (display_name, state) in display_name_to_state.items()
        ]
        print(" ".join(displays))
        pending = False
        succeeded = True
        # The Github states are: "error", "failure", "success", "pending"
        for state in display_name_to_state.values():
            if state not in {"error", "failure", "success"}:
                pending = True
            if state != "success":
                succeeded = False
        if not pending:
            break

    if succeeded:
        _download_release_assets(magic_build_repo_id, release_name)
    else:
        print("*** Failed! ***")
        sys.exit(1)


@cli.command(name="download-release-assets")
@click.option("--repo-id", default=MAGIC_BUILD_REPO)
@click.argument("release-id", required=True)
def download_release_assets(repo_id, release_id):
    _download_release_assets(repo_id, release_id)


if __name__ == "__main__":
    cli()
