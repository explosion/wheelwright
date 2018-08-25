# Nothing to do currently
# function pre_build {
# }

function run_tests {
    python --version
    pytest --pyargs ${BUILD_SPEC_PACKAGE_NAME}
}
