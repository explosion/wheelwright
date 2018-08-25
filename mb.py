import os
import os.path
import sys
import glob
import json
from textwrap import dedent
import subprocess
from contextlib import contextmanager

from github import Github
import click

# - Upload files to a given release
# - Do windows build
# - parse stuff for linux build
# - setup build, wait for finish, download files

# Hack to make SSL work with older macOS Python builds
# (In particular, as of 2018-08-24, this is necessary to allow multibuild's
# py35 to connect to github without "[SSL: TLSV1_ALERT_PROTOCOL_VERSION] tlsv1
# alert protocol version (_ssl.c:719)" errors.)
if sys.platform == "darwin":
    import urllib3.contrib.securetransport
    urllib3.contrib.securetransport.inject_into_urllib3()

def get_gh():
    if "GITHUB_TOKEN" in os.environ:
        token = os.environ["GITHUB_TOKEN"]
    else:
        # XX FIXME
        with open("../github-token.txt") as f:
            token = f.read().strip()
    return Github(token)


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


@cli.command()
@click.option("--repo-id", required=True)
@click.option("--release-id", required=True)
def download_all(repo_id, release_id):
    # https://pygithub.readthedocs.io/en/latest/github_objects/GitReleaseAsset.html
    for asset in get_release(repo_id, release_id).get_assets():
        print(asset.name, asset.browser_download_url)

if __name__ == "__main__":
    cli()
