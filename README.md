# What is this?

This is a magic Github repo that builds release wheels for Explosion
AI projects.


# How do I use it to build wheels?

## Setup

Make a local clone of this repo:

```sh
$ git clone https://github.com/explosion/magic-build-repo.git
```

[Click here to generate a personal Github
token.](https://github.com/settings/tokens/new) Give it some memorable
description, and check the box to give it the "repo" scope. This will
give you some gibberish like:

```
f7d4d475c85ba2ae9557391279d1fc2368f95c38
```

Security notes:

* Be careful with this gibberish; anyone who gets it can impersonate you
  to Github.

* If you're ever worried that your token has been compromised, you can
  [delete it here](https://github.com/settings/tokens), and then
  generate a new one.

* This token is only used to access the magic-build-repo repository,
  so if you want to be extra-careful you could create a new Github
  user, grant them access to this repo only, and then use a token
  generated with that user's account.

Next go into your `magic-build-repo` checkout, and create a file
called `github-secret-token.txt`. Write the gibberish into this file:

```sh
$ cd magic-build-repo
$ my-editor github-secret-token.txt
$ cat github-secret-token.txt
f7d4d475c85ba2ae9557391279d1fc2368f95c38
```

Don't worry, `github-secret-token.txt` is listed in `.gitignore`, so
it's difficult to accidentally commit it.

Install our script's dependencies: `pip install -Ur mb-requirements.txt`

Now you're ready to build wheels.


## Actually building a wheel

If you want to build wheels for the `v1.31.2` tag inside the
`explosion/cymem` repository, then run:

```sh
$ cd magic-build-repo
$ python mb.py magic-build cymem v1.31.2
```

Eventually, if everything goes well, you'll end up with wheels in a
directory named `cymem-v1.31.2-wheels`:

```sh
$ ls cymem-v1.31.2-wheels
cymem-1.32.1-cp27-cp27mu-manylinux1_i686.whl
cymem-1.32.1-cp27-cp27mu-manylinux1_x86_64.whl
... and so on ...
```

Now you can upload them to PyPI:

```sh
$ twine upload cymem-v1.31.2-wheels/*.whl
```

This only uploads wheels. Don't forget to also upload an sdist!


# What did that actually do?

The `magic-build` command uses the Github API to create a Github
release in this repo, called something like `cymem-v1.31.2-wheels`.
Don't be confused: this is not a real release! We're just abusing
Github releases to have a temporary place to collect the wheel files
as we build them.

Then it creates a new branch of this repo, and in the branch it
creates a file called `build-spec.json` describing which project and
commit you want to build.

When Travis and Appveyor see this branch, they spring into action, and
start build jobs running on a variety of architectures and Python
versions. They're configured to the `build-spec.json` file, and then
check out the specified project/revision, build it, test it, and
finally attach the resulting wheel to the Github release we created
earlier.

The `magic-build` command waits until Travis and Appveyor have
finished. If they succeeded, then it downloads all the wheels from the
Github release into a local directory, ready for uploading to PyPI.


# What if something goes wrong?

If the build fails, the script will say so, and won't download any
wheels. While it runs it prints links to the Travis/Appveyor build
logs, the release object, etc., which you can use to get more details
about what went wrong.

If for some reason you want to download the wheels from an existing
release, you can do that with:

```sh
$ python mb.py download-release-assets cymem-v1.31.2-wheels
```

This might be useful if you accidentally killed a `magic-build`
command before it finished, or if you want to get partial results from
a failed build.

If you resubmit a build, then `mb.py` will notice and give it a unique
build id – so if you run `mb.py submit cymem v1.31.2` twice, the first
time it'll use the id `cymem-v1.31.2-wheels`, and the second time it
will be `cymem-v1.31.2-wheels-2`, etc. This doesn't affect the
generated wheels in any way; it's just to make sure we don't get mixed
up between the two builds.


# As a package maintainer, what do I need to know about the build process?

Essentially we run:

```sh
# Setup
$ git clone https://github.com/explosion/PROJECT-NAME.git checkout
$ cd checkout
$ git checkout REVISION

# Build
$ cd checkout
$ pip install -Ur requirements.txt
$ python setup.py bdist_wheel

# Test
$ cd empty-directory
$ pip install -Ur ../checkout/requirements.txt
$ pip install THE-BUILT-WHEEL
$ pytest --pyargs PROJECT-NAME
```

Some things to note:

The build/test phases currently have varying levels of isolation:

* On Windows, they use the same Python environment.
* On macOS, they use different virtualenvs.
* On Linux, they run in different docker containers, which are running
  different Linux distros, to make sure the binaries really are
  portable.

We use the same `requirements.txt` for both building and testing. You
could imagine splitting those into two separate files, in order to
make sure that dependency resolution is working, that we don't have
any run-time dependency on Cython, etc., but currently we don't. If
doing this then it would also make sense to be more careful about
splitting up the build/test environments, and about separating the
`mb.py` helper script from the build/test environments.

We assume that projects use pytest for testing, and that they ship
their tests inside their main package, so that you can run the tests
directly from an installed wheel without access to a source checkout.

For simplicity, we assume that the repository name (in the clone URL)
is the same as the Python import name (in the `pytest` command). You
can override this on a case-by-case basis passing `--clone-url ...` to
the `magic-build` command, but of course doing this every time is
going to be annoying.
  
Aside from modifying `setup.py`, there isn't currently any way for a
specific project to further customize the build, e.g. if they need to
build some dependency like libblis that's not available on PyPI.


# What do I need to know to maintain this repo itself?

Internally, this builds on [Matthew Brett's multibuild
project](https://github.com/matthew-brett/multibuild). A snapshot of
multibuild is included as a git submodule, in the `multibuild/`
directory. You might want to update that submodule occasionally to
pull in new multibuild fixes:

```sh
$ cd multibuild
$ git pull
$ cd ..
$ git commit -am "Updated multibuild snapshot
```

Multibuild was originally designed to do Linux and macOS builds, and
with the idea that you'd create a separate repo for each project with
custom configuration. We kluge it into working for us by reading
configuration out of the `build-spec.json` file and using it to
configure various settings.

Most of the actual configuration is in the `.travis.yml` and
`appveyor.yml` files. These use the `mb.py` script to perform various
actions, ranging from parsing the `build-spec.json` file, to uploading
wheels, to (on Windows) coordinating the whole build/test process.

Unfortunately, there are currently no automated tests. Sorry :-(. They
would need Github permissions and all kinds of things.


## Secrets

To upload the wheels, the CI builds need access to a Github token that
has write permissions on this repository. Specifically, you need a
token with `repo` access to this repo, and it should be stored in an
envvar named `GITHUB_SECRET_TOKEN`. To do this, we use
[Appveyor's](https://www.appveyor.com/docs/build-configuration/#secure-variables)
and
[Travis's](https://docs.travis-ci.com/user/environment-variables/#defining-encrypted-variables-in-travisyml)
support for encrypted environment variables.

First, create your Github token (as in the "setup" section above).
Then, for Appveyor:

* Log in as whichever Appveyor user initially enabled Appveyor for the
  magic build repo

* Go to https://ci.appveyor.com/tools/encrypt

* Paste in the token (just the token, do **not** include the
  `GITHUB_SECRET_TOKEN=` part)

* Copy the "Encrypted value" it gives you back into `appveyor.yml`

And for Travis, we need to get a copy of the `travis` program, and run
`travis encrypt GITHUB_SECRET_TOKEN=<...>` (notice that here you *do*
have to include the `GITHUB_SECRET_TOKEN=` in the encrypted text). On
Ubuntu, I was able to get it working by doing:
  
```sh
$ sudo apt install ruby-dev
$ gem install --user-install travis
$ ~/.gem/ruby/*/bin/travis encrypt GITHUB_SECRET_TOKEN=f7d4d475c85ba2ae9557391279d1fc2368f95c38
```

Then copy the gibberish it gives you into `.travis.yml`.


## Other CI configuration

Travis and Appveyor are both configured to not build tags (because we
don't want our Github releases to trigger builds), and to only build
branches matching the pattern `branch-for-*` (because we don't want
commits to `master` to trigger builds). This is all done through the
`.yml` files.

On Travis, we can also use the `.yml` to disable building of PRs, and
so we do. On Appveyor, though this, isn't possible! In fact, Appveyor
simply doesn't provide any way to disable PR builds in general. But,
there is a hack: if we stop Github from telling Appveyor about PRs,
then it can't build them.

Therefore, after setting up Appveyor, we go the Github settings for
our repository, in [the Webhooks
section](https://github.com/explosion/magic-build-repo/settings/hooks),
click "Edit" on the Appveyor webhook, **un**check the box labeled
"Pull requests", and then click "Update webhook" to save our settings.


# I'm not Explosion AI, but I want to use this too!

It's all under the MIT license, so feel free! It would be great to
somehow convert this into a generic reusable piece of infrastructure,
though it's not entirely clear how given how Rube-Goldergian the whole
thing is – you can't just slap it up on PyPI. (Maybe a cookiecutter
template that generates a repo like this?) In the mean time, you can
probably get something working by:

* forking the repo

* enabling Travis/Appveyor on your new repo

* manually disabling PR builds for Appveyor (see above)

* adding your encrypted Github token to `.travis.yml` and
  `appveyor.yml` (see above)

* editing the magic variables at the top of `mb.py` to point to your
  repo
