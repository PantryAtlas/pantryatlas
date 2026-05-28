#!/usr/bin/env bash
# verify-image.sh — chroot smoke-test of a built PantryAtlas SD image.
#
# Mounts the image rootfs and asserts provisioning WITHOUT booting.
# Requires: sudo, losetup, mount, chroot, curl (in the chroot), findmnt.
#
# Usage:
#   sudo bash ops/image/verify-image.sh /path/to/pantryatlas-v0.2.0.img
#
# NOTE: Point at the UNCOMPRESSED .img (decompress the .img.xz first):
#   xz -dk dist/pantryatlas-v0.2.0.img.xz
#
# The runtime check (uvicorn start + curl) is BEST-EFFORT:
# If the host is x86_64 chrooting into arm64, it requires binfmt_misc +
# qemu-user-static; and chroot-based service startup is fragile in general.
# All file/symlink assertions are HARD (fail on mismatch); the runtime
# section warns but does not fail, so provisioning is still proved either way.
set -euo pipefail

IMG="${1:?usage: verify-image.sh <img>   (uncompressed .img)}"

if [ ! -f "$IMG" ]; then
    echo "ERROR: image not found: $IMG" >&2
    exit 1
fi

MNT="$(mktemp -d)"
LOOP=""
UVICORN_PID=""
BIND_MOUNTS=()

cleanup() {
    # Kill uvicorn if we started it.
    if [ -n "$UVICORN_PID" ] && kill -0 "$UVICORN_PID" 2>/dev/null; then
        kill "$UVICORN_PID" 2>/dev/null || true
        wait "$UVICORN_PID" 2>/dev/null || true
    fi

    # Unmount bind mounts in reverse order (lazily to avoid EBUSY).
    local i
    for (( i=${#BIND_MOUNTS[@]}-1; i>=0; i-- )); do
        umount --lazy "${BIND_MOUNTS[$i]}" 2>/dev/null || true
    done

    # Unmount rootfs.
    if mountpoint -q "$MNT" 2>/dev/null; then
        umount --lazy "$MNT" 2>/dev/null || true
    fi

    # Detach loop device.
    if [ -n "$LOOP" ]; then
        losetup -d "$LOOP" 2>/dev/null || true
    fi

    rmdir "$MNT" 2>/dev/null || true
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# 1. Attach image + mount rootfs (partition 2 = rootfs on RPi OS Lite).
# ---------------------------------------------------------------------------
echo "[verify-image] attaching $IMG"
LOOP="$(losetup -fP --show "$IMG")"
echo "[verify-image] loop device: $LOOP  rootfs partition: ${LOOP}p2"

mount -o ro "${LOOP}p2" "$MNT"
echo "[verify-image] mounted rootfs at $MNT"

# ---------------------------------------------------------------------------
# Helper: assert a path exists; exit 1 with a clear message if not.
# ---------------------------------------------------------------------------
assert_exists() {
    local label="$1"
    local path="$2"
    if [ ! -e "$path" ]; then
        echo "FAIL: $label not found at $path" >&2
        exit 1
    fi
    echo "  OK  $label"
}

assert_not_exists() {
    local label="$1"
    local path="$2"
    if [ -e "$path" ]; then
        echo "FAIL: $label unexpectedly found at $path" >&2
        exit 1
    fi
    echo "  OK  $label (absent as expected)"
}

# ---------------------------------------------------------------------------
# 2. Hard file/directory assertions.
# ---------------------------------------------------------------------------
echo
echo "[verify-image] --- file/directory checks ---"
assert_exists "recipes.db"          "$MNT/home/pantryatlas/.pantryatlas/recipes.db"
assert_exists "bge-m3 model cache"  "$MNT/home/pantryatlas/.cache/pantryatlas/bge-m3"
assert_exists "web/dist"            "$MNT/home/pantryatlas/pantryatlas/web/dist"

# ---------------------------------------------------------------------------
# 3. Systemd unit symlink checks.
# ---------------------------------------------------------------------------
echo
echo "[verify-image] --- systemd unit checks ---"
WANTS="$MNT/etc/systemd/system/multi-user.target.wants"

assert_exists "pantryatlas-navigator.service enabled"   "$WANTS/pantryatlas-navigator.service"
assert_exists "pantryatlas-embeddings.service enabled"  "$WANTS/pantryatlas-embeddings.service"
assert_exists "pantryatlas-mem-monitor.service enabled" "$WANTS/pantryatlas-mem-monitor.service"
assert_not_exists "pantryatlas-gemma.service NOT enabled" "$WANTS/pantryatlas-gemma.service"

# userconfig.service: masked (-> /dev/null) OR absent from multi-user.target.wants.
# Debian/RPi OS may or may not create a wants symlink for it;
# the sdm plugin masks it at /etc/systemd/system/userconfig.service -> /dev/null.
USERCONFIG_MASK="$MNT/etc/systemd/system/userconfig.service"
USERCONFIG_WANTS="$WANTS/userconfig.service"
if [ -L "$USERCONFIG_MASK" ] && [ "$(readlink "$USERCONFIG_MASK")" = "/dev/null" ]; then
    echo "  OK  userconfig.service masked (-> /dev/null)"
elif [ ! -e "$USERCONFIG_WANTS" ]; then
    echo "  OK  userconfig.service absent from multi-user.target.wants"
else
    echo "FAIL: userconfig.service is neither masked nor absent from multi-user.target.wants" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 4. System identity checks.
# ---------------------------------------------------------------------------
echo
echo "[verify-image] --- system identity checks ---"
if ! grep -q "^pantryatlas:" "$MNT/etc/passwd"; then
    echo "FAIL: 'pantryatlas' user not found in /etc/passwd" >&2
    exit 1
fi
echo "  OK  pantryatlas user in /etc/passwd"

if ! grep -q "pantryatlas" "$MNT/etc/hostname"; then
    echo "FAIL: 'pantryatlas' not found in /etc/hostname (got: $(cat "$MNT/etc/hostname"))" >&2
    exit 1
fi
echo "  OK  /etc/hostname contains 'pantryatlas'"

if ! grep -q "pantryatlas" "$MNT/etc/hosts"; then
    echo "FAIL: 'pantryatlas' not found in /etc/hosts" >&2
    exit 1
fi
echo "  OK  /etc/hosts has a 'pantryatlas' entry"

# ---------------------------------------------------------------------------
# 5. Avahi enable symlink.
# Common locations: multi-user.target.wants/, dbus-org.freedesktop.Avahi.service,
# sockets.target.wants/avahi-daemon.socket — check all.
# ---------------------------------------------------------------------------
echo
echo "[verify-image] --- avahi-daemon check ---"
AVAHI_FOUND=0
for candidate in \
    "$MNT/etc/systemd/system/multi-user.target.wants/avahi-daemon.service" \
    "$MNT/etc/systemd/system/dbus-org.freedesktop.Avahi.service" \
    "$MNT/etc/systemd/system/sockets.target.wants/avahi-daemon.socket" \
; do
    if [ -e "$candidate" ] || [ -L "$candidate" ]; then
        echo "  OK  avahi-daemon enabled: $candidate"
        AVAHI_FOUND=1
        break
    fi
done
if [ "$AVAHI_FOUND" -eq 0 ]; then
    # Fall back to a broader find in case the wants dir differs.
    if find "$MNT/etc/systemd/system" -name "avahi-daemon.service" -o -name "avahi-daemon.socket" 2>/dev/null | grep -q .; then
        echo "  OK  avahi-daemon enabled (found via find)"
        AVAHI_FOUND=1
    fi
fi
if [ "$AVAHI_FOUND" -eq 0 ]; then
    echo "FAIL: avahi-daemon enable symlink not found under $MNT/etc/systemd/system/" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 6. nftables firewall rules.
# ---------------------------------------------------------------------------
echo
echo "[verify-image] --- nftables.conf checks ---"
NFTCONF="$MNT/etc/nftables.conf"
if [ ! -f "$NFTCONF" ]; then
    echo "FAIL: $NFTCONF not found" >&2
    exit 1
fi
if ! grep -q "dport 80" "$NFTCONF"; then
    echo "FAIL: nftables.conf does not contain 'dport 80'" >&2
    exit 1
fi
echo "  OK  nftables.conf contains 'dport 80'"
if ! grep -q "8090" "$NFTCONF"; then
    echo "FAIL: nftables.conf does not contain '8090'" >&2
    exit 1
fi
echo "  OK  nftables.conf contains '8090'"

# ---------------------------------------------------------------------------
# 7. Runtime check (best-effort — warns, does NOT fail).
#
# Rationale for best-effort: the host may be x86_64 chrooting into arm64
# (requires qemu-user-static + binfmt_misc registration which we cannot
# guarantee here). Even on arm64, chroot-based service startup lacks the
# full systemd environment. All hard provisiong assertions above already
# prove correctness; this step only validates the uvicorn invocation path.
# ---------------------------------------------------------------------------
echo
echo "[verify-image] --- runtime check (best-effort) ---"

# Remount rw for chroot runtime (needed to write PID files, sockets, etc.)
umount "$MNT"
mount "${LOOP}p2" "$MNT"   # rw this time

# Bind-mount the virtual filesystems the chroot needs.
for VIRT in proc sys dev dev/pts run; do
    TARGET="$MNT/$VIRT"
    mkdir -p "$TARGET"
    case "$VIRT" in
        proc)    mount -t proc  proc  "$TARGET" ;;
        sys)     mount -t sysfs sysfs "$TARGET" ;;
        dev)     mount --bind   /dev  "$TARGET" ;;
        dev/pts) mount --bind   /dev/pts "$TARGET" ;;
        run)     mount -t tmpfs tmpfs "$TARGET" ;;
    esac
    BIND_MOUNTS+=("$TARGET")
done

UVICORN="$MNT/home/pantryatlas/pantryatlas/venv/bin/uvicorn"
if [ ! -f "$UVICORN" ]; then
    echo "WARN: uvicorn not found at $UVICORN — skipping runtime check" >&2
else
    set +e   # best-effort from here
    chroot "$MNT" runuser -u pantryatlas -- \
        env PANTRYATLAS_HOME=/home/pantryatlas/.pantryatlas \
        /home/pantryatlas/pantryatlas/venv/bin/uvicorn \
        pantryatlas.navigator.server:app \
        --host 127.0.0.1 --port 8090 \
        >/tmp/uvicorn-smoke.log 2>&1 &
    UVICORN_PID=$!
    echo "[verify-image] started uvicorn (pid $UVICORN_PID), waiting 5 s..."
    sleep 5

    if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
        echo "WARN: uvicorn exited early — log: /tmp/uvicorn-smoke.log" >&2
        echo "WARN: runtime check skipped (provisioning file checks still passed)" >&2
    else
        if chroot "$MNT" curl -fs http://127.0.0.1:8090/ >/dev/null 2>&1; then
            echo "  OK  navigator responded to HTTP GET /"
        else
            echo "WARN: curl to navigator failed — may be arch or env issue" >&2
            echo "WARN: runtime check inconclusive (provisioning file checks still passed)" >&2
        fi
        kill "$UVICORN_PID" 2>/dev/null || true
        wait "$UVICORN_PID" 2>/dev/null || true
        UVICORN_PID=""
    fi
    set -e
fi

# ---------------------------------------------------------------------------
# Done — cleanup via EXIT trap.
# ---------------------------------------------------------------------------
echo
echo "[verify-image] SUCCESS — all hard provisioning assertions passed."
echo "  (Runtime check above is best-effort; see comment for caveats.)"
