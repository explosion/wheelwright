<a href="https://explosion.ai"><img src="https://explosion.ai/assets/img/logo.svg" width="125" height="125" align="right" /></a>

# Wheelwright

This repo builds release wheels for Python libraries available as GitHub
repositories. We're currently using it to build wheels for
[spaCy](https://github.com/explosion/spaCy) and our
[other libraries](https://github.com/explosion). The build repository integrates
with
[Azure Pipelines](https://azure.microsoft.com/de-de/services/devops/pipelines/)
and builds the sdist and wheels for macOS, Linux and Windows on Python 3.5+. All
wheels are available in the
[releases](https://github.com/explosion/wheelwright/releases).

🙏 **Special thanks** to [Nathaniel J. Smith](https://github.com/njsmith/) for
helping us out with this, to [Matthew Brett](https://github.com/matthew-brett)
for [`multibuild`](https://github.com/matthew-brett/multibuild), and of course
to the [PyPA](https://www.pypa.io/en/latest/) team for their hard work on Python
packaging.

> ⚠️ This repo has been updated to use Azure Pipelines instead of Travis and
> Appveyor (see the [`v1`](https://github.com/explosion/wheelwright/tree/v1)
> branch for the old version). We also dropped support for Python 2.7. The code
> is still experimental and currently mostly intended to build wheels for our
> projects. For more details on how it works, check out the [FAQ](#faq) below.

[![Azure Pipelines](https://img.shields.io/badge/Azure%20Pipelines-view%20builds-green.svg?longCache=true&style=flat-square&logo=azure-pipelines)](https://dev.azure.com/explosion-ai/public/_build?definitionId=15)

<img width="803" alt="" src="https://user-images.githubusercontent.com/13643239/68905692-598efb00-0742-11ea-800b-630767858201.png">

## 🎡 Usage

### Quickstart

1. Fork or clone this repo and run `pip install -r requirements.txt` to install
   its requirements.
2. Generate a personal [GitHub token](https://github.com/settings/tokens/new)
   with access to the `repo`, `user` and `admin:repo_hook` scopes and put it in
   a file `github-secret-token.txt` in the root of the repo. Commit the changes.
   Don't worry, the secrets file is excluded in the `.gitignore`.
3. Set up a
   [GitHub service connection](https://docs.microsoft.com/en-us/azure/devops/pipelines/library/service-endpoints?view=azure-devops&tabs=yaml#sep-github)
   on Azure Pipelines with a personal access token and name it `wheelwright`.
   This will be used to upload the artifacts to the GitHub release.
4. Run `python run.py build your-org/your-repo [commit/tag]`.
5. Once the build is complete, the artifacts will show up in the GitHub release
   `wheelwright` created for the build. They'll also be available as release
   artifacts in Azure Pipelines, so you can add a release process that uploads
   them to PyPi.

### Setup and Installation

Make a local clone of this repo:

```bash
git clone https://github.com/explosion/wheelwright
```

Next, install its requirements (ideally in a virtual environment):

```bash
pip install -r requirements.txt
```

[Click here to generate a personal GitHub token.](https://github.com/settings/tokens/new)
Give it some memorable description, and check the box to give it the "repo"
scope. This will give you some gibberish like
`f7d4d475c85ba2ae9557391279d1fc2368f95c38`.

#### Security notes

- Be careful with this gibberish; anyone who gets it can impersonate you to
  GitHub.

- If you're ever worried that your token has been compromised, you can
  [delete it here](https://github.com/settings/tokens), and then generate a new
  one.

- This token is only used to access the `wheelwright` repository, so if you want
  to be extra-careful you could create a new GitHub user, grant them access to
  this repo only, and then use a token generated with that user's account.

Next go into your `wheelwright` checkout, and create a file called
`github-secret-token.txt`. Write the gibberish into this file:

```bash
cd wheelwright
my-editor github-secret-token.txt
cat github-secret-token.txt
f7d4d475c85ba2ae9557391279d1fc2368f95c38
```

Don't worry, `github-secret-token.txt` is listed in `.gitignore`, so it's
difficult to accidentally commit it. Instead of adding the file, you can also
provide the token via the `GITHUB_SECRET_TOKEN` environment variable.

## Building wheels

Note that the `run.py` script requires Python 3.6+. If you want to build wheels
for the `v1.31.2` tag inside the `explosion/cymem` repository, then run:

```bash
cd wheelwright
python run.py build explosion/cymem v1.31.2
```

Eventually, if everything goes well, you'll end up with wheels attached to a new
GitHub release and in Azure Pipelines. You can then either publish them via a
custom release process, or download them manually:

```bash
python run.py download cymem-v1.31.2
```

## 🎛 API

### `run.py build`

Build wheels for a given repo and commit / tag.

```bash
python run.py build explosion/cymem v1.32.1
```

| Argument         | Type       | Description                                                            |
| ---------------- | ---------- | ---------------------------------------------------------------------- |
| `repo`           | positional | The repository to build, in `user/repo` format.                        |
| `commit`         | positional | The commit to build.                                                   |
| `--package-name` | option     | Optional alternative Python package name, if different from repo name. |

### `run.py download`

Download existing wheels for a release ID (name of build repo tag). The
downloaded wheels will be placed in a directory `wheels`.

```bash
python run.py download cymem-v1.31.2
```

| Argument     | Type       | Description                      |
| ------------ | ---------- | -------------------------------- |
| `release-id` | positional | Name of the release to download. |

### Environment variables

| Name                     | Description                                                                 | Default                              |
| ------------------------ | --------------------------------------------------------------------------- | ------------------------------------ |
| `WHEELWRIGHT_ROOT`       | Root directory of the build repo                                            | Same directory as `run.py`           |
| `WHEELWRIGHT_WHEELS_DIR` | Directory for downloaded wheels                                             | `/wheels` in root directory          |
| `WHEELWRIGHT_REPO`       | Build repository in `user/repo` format                                      | Automatically read from `git config` |
| `GITHUB_SECRET_TOKEN`    | Personal GitHub access token, if not provided via `github-secret-token.txt` | -                                    |

## ⁉️ FAQ

### What does this actually do?

The `build` command uses the GitHub API to create a GitHub release in this repo,
called something like `cymem-v1.31.2`. Don't be confused: this is not a real
release! We're just abusing GitHub releases to have a temporary place to collect
the wheel files as we build them. Then it creates a new branch of this repo, and
in the branch it creates a file called `build-spec.json` describing which
project and commit you want to build.

When Azure Pipelines sees this branch, it springs into action, and starts build
jobs running on a variety of architectures and Python versions. These build jobs
read the `build-spec.json` file, and then check out the specified
project/revision, build it, test it, and finally attach the resulting wheel to
the GitHub release we created earlier.

### What if something goes wrong?

If the build fails, you'll see the failures in the Azure Pipelines build logs.
All artifacts that have completed will still be available to download from the
GitHub release.

If you resubmit a build, then `run.py` will notice and give it a unique build ID
– so if you run `run.py build explosion/cymem v1.31.2` twice, the first time
it'll use the id `cymem-v1.31.2`, and the second time it will be
`cymem-v1.31.2-2`, etc. This doesn't affect the generated wheels in any way;
it's just to make sure we don't get mixed up between the two builds.

### As a package maintainer, what do I need to know about the build process?

Essentially we run:

```console
# Setup
git clone https://github.com/USER-NAME/PROJECT-NAME.git checkout
cd checkout
git checkout REVISION

# Build
cd checkout
pip install -Ur requirements.txt
python setup.py bdist_wheel

# Test
cd empty-directory
pip install -Ur ../checkout/requirements.txt
pip install THE-BUILT-WHEEL
pytest --pyargs PROJECT-NAME
```

Some things to note:

The build/test phases currently have varying levels of isolation from each
other:

- On Windows, they use the same Python environment.
- On macOS, they use different virtualenvs.
- On Linux, they run in different docker containers, which are running different
  Linux distros, to make sure the binaries really are portable.

We use the same `requirements.txt` for both building and testing. You could
imagine splitting those into two separate files, in order to make sure that
dependency resolution is working, that we don't have any run-time dependency on
Cython, etc., but currently we don't. If doing this then it would also make
sense to be more careful about splitting up the build/test environments, and
about separating the `run.py` helper script from the build/test environments.

We assume that projects use pytest for testing, and that they ship their tests
inside their main package, so that you can run the tests directly from an
installed wheel without access to a source checkout.

For simplicity, we assume that the repository name (in the clone URL) is the
same as the Python import name (in the `pytest` command). You can override this
on a case-by-case basis passing `--package ...` to the `build` command, but of
course doing this every time is going to be annoying.

Aside from modifying `setup.py`, there isn't currently any way for a specific
project to further customize the build, e.g. if they need to build some
dependency like libblis that's not available on PyPI.

### What do I need to know to maintain this repo itself?

Internally, this builds on
[Matthew Brett's multibuild project](https://github.com/matthew-brett/multibuild).
A snapshot of multibuild is included as a git submodule, in the `multibuild/`
directory. You might want to update that submodule occasionally to pull in new
multibuild fixes:

```bash
cd multibuild
git pull
cd ..
git commit -am "Updated multibuild snapshot"
```

Multibuild was originally designed to do Linux and macOS builds, and with the
idea that you'd create a separate repo for each project with custom
configuration. We kluge it into working for us by reading configuration out of
the `build-spec.json` file and using it to configure various settings. Most of
the actual configuration is in the `azure-pipelines.yml` file.

### I'm not Explosion, but I want to use this too!

It's all under the MIT license, so feel free! It would be great to somehow
convert this into a generic reusable piece of infrastructure, though it's not
entirely clear how given how Rube-Goldergian the whole thing is – you can't just
slap it up on PyPI. (Maybe a cookiecutter template that generates a repo like
this?)
