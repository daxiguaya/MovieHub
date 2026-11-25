#!/bin/sh
set -eu

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

git init -q repo
cd repo
git config user.name "MovieHub CI"
git config user.email "moviehub-ci@example.invalid"

printf 'base\n' > docker-compose.yml
printf 'base\n' > backend.txt
git add docker-compose.yml backend.txt
git commit -qm base
BASE=$(git rev-parse HEAD)
git branch -M main

git checkout -qb remote-main
printf 'TMDB_API_READ_TOKEN: ${TMDB_API_READ_TOKEN:-}\n' > docker-compose.yml
printf 'new backend\n' > backend.txt
git add docker-compose.yml backend.txt
git commit -qm 'remote main update'
TARGET=$(git rev-parse HEAD)
git update-ref refs/remotes/origin/main "$TARGET"

git checkout -q main
# Simulate the NAS's unstaged local Compose change, now identical to origin/main.
printf 'TMDB_API_READ_TOKEN: ${TMDB_API_READ_TOKEN:-}\n' > docker-compose.yml
mkdir -p backup/keep-me
printf 'preserve\n' > backup/keep-me/manifest.txt

git diff --cached --quiet HEAD -- .
git diff --quiet HEAD -- . ':(exclude)docker-compose.yml'
git diff --quiet origin/main -- docker-compose.yml
git merge-base --is-ancestor HEAD origin/main
git add docker-compose.yml
git merge --ff-only origin/main >/dev/null

[ "$(git rev-parse HEAD)" = "$TARGET" ]
[ -f backup/keep-me/manifest.txt ]
grep -q 'preserve' backup/keep-me/manifest.txt

# A genuinely divergent local commit must be rejected by the ancestry guard.
git checkout -qb divergent "$BASE"
printf 'local divergent change\n' > divergent.txt
git add divergent.txt
git commit -qm divergent
if git merge-base --is-ancestor HEAD origin/main; then
  echo "FAIL: divergent history passed the fast-forward guard" >&2
  exit 1
fi
if git merge --ff-only origin/main >/dev/null 2>&1; then
  echo "FAIL: divergent history passed git merge --ff-only" >&2
  exit 1
fi

echo "PASS: verified Compose override fast-forwards; untracked backup is preserved; divergent history is rejected."
