---
title: Download & flash the image
description: Download the pre-built PantryAtlas SD card image and write it to a microSD card.
---

The fastest way to set up a Raspberry Pi 5 is to write our **pre-built image** to
a microSD card. It already contains PantryAtlas and everything it needs, so you
skip the manual install. About 8 minutes of writing, then plug in and go.

## Download

- **Image:** <https://dl.pantryatlas.org/img/pantryatlas-v0.2.0.img.xz>
- **Version:** v0.2.0 · **~1.9 GB** download (`.img.xz`, compressed)

Raspberry Pi Imager reads the compressed `.img.xz` directly — there's no need to
unzip it first.

## Verify the download (recommended)

A ~1.9 GB download can truncate or corrupt. Check it before flashing. The
expected **MD5** is:

```
4a2ee2424b15125a5ee5a36787aff0ce
```

Compare it against your downloaded file:

```sh
# macOS
md5 pantryatlas-v0.2.0.img.xz

# Linux
md5sum pantryatlas-v0.2.0.img.xz
```

The printed value must match exactly. If it doesn't, the download is incomplete —
delete it and download again. (MD5 here is an integrity check against corruption,
not a security signature.)

## Flash it to a microSD card

1. Install the free [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
   on your computer.
2. Open it, click **Choose OS → Use custom**, and select the
   `pantryatlas-v0.2.0.img.xz` file you downloaded.
3. **Choose Storage** and pick your microSD card (a Pi 5 kit includes one).
4. Click **Write**. It takes about 8 minutes.

## Next

Put the card in your Pi 5, plug in power and Wi-Fi or ethernet, and wait for the
solid green light (about a minute). Then open **pantryatlas.local** in any browser
on the same network and pick Home or Community Kitchen on first launch.

On first boot PantryAtlas also fetches the prebuilt
[recipe database](/developers/recipe-database/) automatically — no extra step.

Stuck? See [Troubleshooting](/maintenance/troubleshooting/).
