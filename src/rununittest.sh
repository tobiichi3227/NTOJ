#!/bin/bash

current_pwd=$(pwd)

cat <<EOF >.coveragerc
[run]
branch = True
concurrency = thread
parallel = True
omit =
    /usr/lib/python3/*
    */site-packages/*
    */dist-packages/*
    *.generated.py
    runintegratedtest.py
    rununittest.py
    tests/*
    server.py
    upgrade.py
EOF

# Remove old coverage artifacts. These may not exist on a clean CI runner.
rm -f .coverage .coverage.*
rm -rf ./htmlcov

COVERAGE_PROCESS_START=.coveragerc $HOME/.local/bin/poetry run coverage run --branch --source=./ rununittest.py
rc=$?
$HOME/.local/bin/poetry run coverage combine
$HOME/.local/bin/poetry run coverage html

exit $rc