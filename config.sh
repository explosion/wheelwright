function pre_build {}

# This runs in an environment with just the installed package, not the source
# tree
function run_tests {
    python --version
    pytest --pyargs cymem
}
