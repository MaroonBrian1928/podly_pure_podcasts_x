#!/usr/bin/env bash
# Posts or updates the smoke-test comment on a pull request, from the
# smoke-report artifact of a "Smoke Test" run. Run by smoke-report.yml.
#
# Everything in REPORT_DIR came from a run of pull request code and is
# untrusted: only known file names of the expected type and size are used,
# and only numbers are taken from text files.
#
# With BOT_TOKEN (a user's token) the videos and screenshots are attached
# inline with `gh pr comment --attach`; GitHub refuses attachments from
# GITHUB_TOKEN. Without it, a GIF and the screenshots are uploaded to the
# smoke-media release with GITHUB_TOKEN and the videos are linked.
#
# Env: GH_TOKEN, GH_REPO, REPORT_DIR, RUN_ID, RUN_URL, HEAD_SHA, CONCLUSION,
#      STARTED_AT, UPDATED_AT, BOT_TOKEN (optional)
set -euo pipefail

MARKER='<!-- podly-smoke-test -->'
RELEASE_TAG=smoke-media
MAX_BYTES=$((10 * 1024 * 1024))

pr=$(head -c 16 "$REPORT_DIR/pr-number" 2>/dev/null | tr -d '[:space:]' || true)
if ! [[ "$pr" =~ ^[0-9]{1,7}$ ]]; then
  echo "No valid PR number in the report; nothing to post."
  exit 0
fi

# The PR number is only a claim; the PR's current head must be the commit
# that was tested.
pr_head=$(gh api "repos/$GH_REPO/pulls/$pr" --jq .head.sha)
if [ "$pr_head" != "$HEAD_SHA" ]; then
  echo "PR #$pr head is $pr_head, but the run tested $HEAD_SHA; not posting."
  exit 0
fi

media=$(mktemp -d)
accept() { # name, mime type
  local src="$REPORT_DIR/$1"
  [ -f "$src" ] && [ ! -L "$src" ] || return 1
  [ "$(file --brief --mime-type "$src")" = "$2" ] || { echo "Skipping $1: not $2"; return 1; }
  [ "$(stat -c %s "$src")" -le "$MAX_BYTES" ] || { echo "Skipping $1: over 10 MB"; return 1; }
  cp "$src" "$media/$1"
}
videos=()
for v in walkthrough.webm enable-and-process.webm; do
  accept "$v" video/webm && videos+=("$v")
done
shots=()
for s in walkthrough-failure.jpg enable-failure.jpg phone-failure.jpg \
  feed.jpg stats-overview.jpg stats-model-calls.jpg settings.jpg enable-confirm.jpg phone.jpg; do
  accept "$s" image/jpeg && shots+=("$s")
done
gif=
accept walkthrough.gif image/gif && gif=walkthrough.gif

fmt() { printf '%d:%02d' $(($1 / 60)) $(($1 % 60)); }
cuts=$(grep -oE '\(([0-9]{1,6})\.[0-9]+, ([0-9]{1,6})\.[0-9]+\)' "$REPORT_DIR/cuts.txt" 2>/dev/null | head -4 |
  sed -E 's/\(([0-9]+)\.[0-9]+, ([0-9]+)\.[0-9]+\)/\1 \2/' |
  while read -r a b; do printf '%s–%s, ' "$(fmt "$a")" "$(fmt "$b")"; done || true)
cuts=${cuts%, }

elapsed=$(($(date -d "$UPDATED_AT" +%s) - $(date -d "$STARTED_AT" +%s)))
case "$CONCLUSION" in
  success) status="✅ **Smoke test passed**" ;;
  failure) status="❌ **Smoke test failed**" ;;
  *) status="⚠️ **Smoke test $CONCLUSION**" ;;
esac

caption() {
  case "$1" in
    walkthrough-failure.jpg) echo "Walkthrough failure" ;;
    enable-failure.jpg) echo "Enable failure" ;;
    phone-failure.jpg) echo "Phone failure" ;;
    feed.jpg) echo "Processed episode" ;;
    stats-overview.jpg) echo "Stats" ;;
    stats-model-calls.jpg) echo "Model calls" ;;
    settings.jpg) echo "Settings" ;;
    enable-confirm.jpg) echo "Enable episode" ;;
    phone.jpg) echo "Phone" ;;
  esac
}

# shot_url NAME -> markdown image target; video_block NAME -> markdown
write_body() {
  {
    echo "$MARKER"
    echo "$status in $(fmt "$elapsed") · [run]($RUN_URL) · \`${HEAD_SHA:0:7}\`"
    echo
    if [ -n "$cuts" ]; then
      echo "Ad breaks cut: $cuts (expected 1:28–2:12, 4:02–4:35)"
      echo
    fi
    for v in "${videos[@]}"; do
      echo "**${v%.webm}**"
      echo
      video_block "$v"
      echo
    done
    if [ ${#shots[@]} -gt 0 ]; then
      local i=0 row_titles="" row_images=""
      echo "| | | |"
      echo "|---|---|---|"
      for s in "${shots[@]}"; do
        row_titles+="| $(caption "$s") "
        row_images+="| ![$(caption "$s")]($(shot_url "$s")) "
        i=$((i + 1))
        if [ $((i % 3)) -eq 0 ]; then
          echo "$row_titles|"
          echo "$row_images|"
          row_titles="" row_images=""
        fi
      done
      if [ -n "$row_titles" ]; then
        echo "$row_titles|"
        echo "$row_images|"
      fi
      echo
    fi
    echo "<sub>Mock providers; full screenshots, videos and logs are in the run's \`smoke-output\` artifact.</sub>"
  } > "$media/body.md"
}

if [ -n "${BOT_TOKEN:-}" ]; then
  shot_url() { echo "./$1"; }
  video_block() { echo "![$1](./$1)"; }
  write_body
  attach=()
  for f in "${videos[@]}" "${shots[@]}"; do attach+=(--attach "$media/$f"); done
  GH_TOKEN="$BOT_TOKEN" gh pr comment "$pr" --edit-last --create-if-none \
    --body-file "$media/body.md" "${attach[@]}"
  exit 0
fi

gh release view "$RELEASE_TAG" > /dev/null 2>&1 ||
  gh release create "$RELEASE_TAG" --prerelease --title "Smoke test media" \
    --notes "Screenshots and recordings for smoke-test comments on pull requests. Managed by smoke-report.yml."
release_id=$(gh api "repos/$GH_REPO/releases/tags/$RELEASE_TAG" --jq .id)
gh api --paginate "repos/$GH_REPO/releases/$release_id/assets" --jq ".[] | select(.name | startswith(\"pr$pr-\")) | .id" |
  while read -r id; do gh api -X DELETE "repos/$GH_REPO/releases/assets/$id"; done

prefix="pr$pr-$RUN_ID-"
upload=()
for f in "${videos[@]}" "${shots[@]}" $gif; do
  cp "$media/$f" "$media/$prefix$f"
  upload+=("$media/$prefix$f")
done
[ ${#upload[@]} -eq 0 ] || gh release upload "$RELEASE_TAG" "${upload[@]}" --clobber

asset_url() { echo "https://github.com/$GH_REPO/releases/download/$RELEASE_TAG/$prefix$1"; }
shot_url() { asset_url "$1"; }
video_block() {
  if [ "$1" = walkthrough.webm ] && [ -n "$gif" ]; then
    echo "![Walkthrough at 4× speed]($(asset_url "$gif"))"
    echo
  fi
  echo "[Download $1]($(asset_url "$1"))"
}
write_body

comment_id=$(gh api --paginate "repos/$GH_REPO/issues/$pr/comments" \
  --jq ".[] | select(.user.login == \"github-actions[bot]\" and (.body | startswith(\"$MARKER\"))) | .id" | tail -1)
if [ -n "$comment_id" ]; then
  gh api -X PATCH "repos/$GH_REPO/issues/comments/$comment_id" -F "body=@$media/body.md" > /dev/null
else
  gh api -X POST "repos/$GH_REPO/issues/$pr/comments" -F "body=@$media/body.md" > /dev/null
fi
