until pg_isready -h ${DB_CONTAINER_NAME} -p 5432; do
    echo "Postgres is unavailable - sleeping"
    sleep 2
done

should_install_first_problem=false
if [[ -f docker-dev || -f docker-release ]] && [ -d static-tmp ]; then
    should_install_first_problem=true
    ./scripts/docker-init.sh
fi

if [ -d migration ] && [[ -f docker-dev || -f docker-release ]];
then
    cp config.py migration/
    cd migration

    if [ -f ../docker-release ]; then
        python3 migration.py
        cd ..
        rm -rf migration

        if [ "$should_install_first_problem" = true ] ; then
            python3 scripts/install_first_pro.py
        fi
    else
        poetry run python3 migration.py
        cd ..
        if [ "$should_install_first_problem" = true ] ; then
            poetry run python3 scripts/install_first_pro.py
        fi
    fi

    if [ "$should_install_first_problem" = true ] ; then
        rm scripts/install_first_pro.py
    fi
fi

if [[ -n "${NTOJ_COVERAGE_FILE:-}" ]]; then
    if [ ! -f docker-dev ]; then
        echo "NTOJ_COVERAGE_FILE is supported only by the development image" >&2
        exit 1
    fi
    export COVERAGE_FILE="$NTOJ_COVERAGE_FILE"
    exec "$HOME/.local/bin/poetry" run coverage run \
        --rcfile="${NTOJ_COVERAGE_RCFILE:-.coveragerc}" server.py
elif [ -f docker-release ]; then
    exec python3 server.py
elif [ -f docker-dev ]; then
    exec "$HOME/.local/bin/poetry" run python3 server.py
else
    exec "$HOME/.local/bin/poetry" run python3 server.py --log_rotate_mode=time --log_file_prefix=/var/log/ntoj/access.log
fi
