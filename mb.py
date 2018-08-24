import os
import os.path
import glob
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
if os.name == "darwin":
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

@click.group()
def cli():
    pass

@cli.command()
@click.option("--repo-id", required=True)
@click.option("--release-id", required=True)
@click.argument(
    "paths", nargs=-1, type=click.Path(exists=True)
)
def upload(repo_id, release_id, paths):
    release = get_release(repo_id, release_id)
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
@click.option("--repo-id", required=True)
@click.option("--release-id", required=True)
def download_all(repo_id, release_id):
    # https://pygithub.readthedocs.io/en/latest/github_objects/GitReleaseAsset.html
    for asset in get_release(repo_id, release_id).get_assets():
        print(asset.name, asset.browser_download_url)

if __name__ == "__main__":
    cli()
