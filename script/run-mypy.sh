#!/usr/bin/env bash

set -o errexit

# other common virtualenvs
my_path=$(git rev-parse --show-toplevel)

for venv in venv .venv .; do
  if [ -f "${my_path}/${venv}/bin/activate" ]; then
    . "${my_path}/${venv}/bin/activate"
    break
  fi
done

mypy ${my_path}
