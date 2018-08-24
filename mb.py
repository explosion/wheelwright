# Uses pygithub
import os
from github import Github
import click

# - Upload files to a given release
# - Do windows build
# - parse stuff for linux build
# - setup build, wait for finish, download files

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
    "paths", nargs=-1, type=click.Path(exists=True, dir_okay=False)
)
def upload(repo_id, release_id, paths):
    release = get_release(repo_id, release_id)
    # https://pygithub.readthedocs.io/en/latest/github_objects/GitReleaseAsset.html
    for path in paths:
        print("Uploading:", path)
        release.upload_asset(path)

@cli.command()
@click.option("--repo-id", required=True)
@click.option("--release-id", required=True)
def download_all(repo_id, release_id):
    for asset in get_release(repo_id, release_id).get_assets():
        print(asset.name, asset.browser_download_url)

if __name__ == "__main__":
    cli()
