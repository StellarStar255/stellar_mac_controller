#!/bin/sh
# Self-contained per-user installer, with atomic replacement of the app folder.
set -eu
base="${XDG_DATA_HOME:-$HOME/.local/share}"
root="$base/stellar-mac-controller"
mkdir -p "$base" "$base/applications" "$HOME/.local/bin"
stage=$(mktemp -d "$base/.mac-controller-install.XXXXXX")
trap 'rm -rf "$stage"' EXIT HUP INT TERM
line=$(awk '/^__ARCHIVE_BELOW__$/ { print NR + 1; exit }' "$0")
tail -n +"$line" "$0" | tar xz -C "$stage"
test -x "$stage/MacController/MacController"
touch "$stage/MacController/.user-install"
# Rename existing code out of the way; conversation data lives elsewhere.
backup="$base/.mac-controller-backup-$$"
if [ -e "$root" ]; then mv "$root" "$backup"; fi
if ! mv "$stage/MacController" "$root"; then
  if [ -d "$backup" ]; then mv "$backup" "$root"; fi
  exit 1
fi
ln -sfn "$root/MacController" "$HOME/.local/bin/mac-controller"
# Quote paths according to the freedesktop Exec field format.
exec_path=$(printf '%s' "$root/MacController" | sed 's/\\/\\\\/g; s/"/\\"/g; s/`/\\`/g; s/\$/\\$/g; s/%/%%/g')
cat > "$base/applications/stellar-mac-controller.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Mac Controller
Comment=Desktop AI assistant
Exec="$exec_path"
Terminal=false
Categories=Utility;
EOF
chmod +x "$base/applications/stellar-mac-controller.desktop"
if [ -d "$backup" ]; then rm -rf "$backup"; fi
printf '%s\n' "Mac Controller installed. Launch it from your applications menu."
if [ "${1:-}" = "--update" ]; then
  sleep 2
  "$root/MacController" >/dev/null 2>&1 &
fi
exit 0
__ARCHIVE_BELOW__
