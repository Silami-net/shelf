#!/bin/bash
# Builds dist/Shelf-full-<version>-x86_64.AppImage: Python, GTK and every library
# included, built on Ubuntu 20.04 (glibc 2.31) so it runs on most x86_64 Linux
# systems from about 2018 on, with nothing installed.
# Runs appimage-builder inside an Ubuntu 20.04 podman container. Its downloads and
# container storage stay in build/ (kept out of git).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import shelf; print(shelf.__version__)' "$ROOT")"
mkdir -p "$ROOT/build/full" "$ROOT/build/podman" "$ROOT/dist"

# Own storage under build/, ignoring file-ownership changes, so it also works for
# rootless podman without subordinate user ids (e.g. network logins).
PODMAN=(podman --root "$ROOT/build/podman/root" --runroot "$ROOT/build/podman/run"
        --storage-driver vfs --storage-opt vfs.ignore_chown_errors=true)

"${PODMAN[@]}" run --rm \
    -v "$ROOT:/src:Z" -w /src/build/full \
    -e VERSION="$VERSION" -e SHELF_SRC=/src -e SHELF_BUILD=/src/build/full \
    -e DEBIAN_FRONTEND=noninteractive \
    docker.io/library/ubuntu:20.04 bash -euc '
        # With a single user id, apt cannot drop to its _apt download user.
        echo "APT::Sandbox::User \"root\";" > /etc/apt/apt.conf.d/99no-sandbox
        apt-get update -qq
        apt-get install -y -qq --no-install-recommends python3-pip python3-setuptools \
            patchelf desktop-file-utils libgdk-pixbuf2.0-dev fakeroot squashfs-tools \
            gtk-update-icon-cache file wget ca-certificates gnupg binutils zsync >/dev/null
        pip3 install -q --upgrade "pip<24"
        # Newer lief releases ship no prebuilt wheels for Python 3.8, and packaging 22+
        # rejects Debian version numbers, which appimage-builder 1.1.0 compares.
        pip3 install -q "lief==0.12.3" "packaging==21.3" appimage-builder==1.1.0
        # appimage-builder runs its own apt with its own settings; give it the same
        # no-sandbox setting (its recipe format has no place for apt options).
        VENV="$(python3 -c "import appimagebuilder, os; print(os.path.dirname(appimagebuilder.__file__))")/modules/deploy/apt/venv.py"
        sed -i "s/\"APT::Install-Recommends\": False,/&\n            \"APT::Sandbox::User\": \"root\",/" "$VENV"
        grep -q "APT::Sandbox::User" "$VENV"
        appimage-builder --recipe /src/packaging/appimage-builder.yml --skip-tests
        mv /src/build/full/Shelf-full-*.AppImage /src/dist/
        rm -f /src/build/full/*.zsync  # only useful with update-information
    '
echo "Built $ROOT/dist/Shelf-full-$VERSION-x86_64.AppImage"
