---
title: Troubleshooting
description: Fix common problems and keep PantryAtlas healthy.
---

## I can't reach pantryatlas.local

- Make sure your phone or laptop is on the **same Wi-Fi** as the device.
- Wait for the **solid green light** — that means PantryAtlas is running.
- Some networks block `.local` names. Try the device's IP address instead (check
  your router's device list).

## The camera scan misreads my shelf

- Improve lighting and hold the phone steady.
- You can always correct items by typing — the photo is only a shortcut.

## Recipes are slow to appear

- The first search after boot warms up the model and is slower; later searches
  are faster.
- On a busy network, give it a few extra seconds.

## Back up or move your data

Your data lives on the microSD card. Power down, remove the card, and copy its
image with Raspberry Pi Imager (or any disk-image tool) to back up. Restore by
writing that image to a fresh card.

## Update PantryAtlas

Pull the latest version from GitHub and re-run the installer (a one-click update
image is coming soon). Back up first if you want to keep your current data.

## Start over

Re-run the install from GitHub onto the microSD card. This erases everything on
the card.
