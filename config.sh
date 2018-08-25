# Nothing to do currently
# function pre_build {
# }

function run_tests {
    set -x
    pwd
    ls
    env
    # On Linux, multibuild runs this test inside a docker container, so it
    # doesn't have access to the envvars we set in the main .travis.yml.
    eval $(python ./mb.py build_spec_to_shell build-spec.json)
    python --version
    pytest --pyargs ${BUILD_SPEC_PACKAGE_NAME}
}
