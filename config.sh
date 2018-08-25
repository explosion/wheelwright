# Nothing to do currently
# function pre_build {
# }

function run_tests {
    set -x
    # On Linux, multibuild runs this test inside a docker container, so it
    # doesn't have access to the envvars we set in the main .travis.yml.
    # This runs in /io/tmp_for_test, so the actual
    if [ -z "${BUILD_SPEC_PACKAGE_NAME}" ]; then
        pushd ..
        pip install -U pygithub click
        eval $(python ./mb.py build_spec_to_shell build-spec.json)
        popd
    fi
    python --version
    pytest --pyargs ${BUILD_SPEC_PACKAGE_NAME}
}
