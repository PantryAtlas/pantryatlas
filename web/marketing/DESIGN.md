# pantryatlas.org — Marketing Page Design Brief

> A single scrolling landing page at pantryatlas.org. Audience: a non-technical person — parent, kitchen coordinator, food-bank volunteer — who has never touched a Raspberry Pi. They've heard the word "Pi" once, maybe never. They want to know what this is, whether it's for them, and how to actually get it running on their countertop. The page must answer all three before they scroll past it.

## Voice

Plain language. Short sentences. Concrete nouns over abstract claims. *"A small computer that lives in your kitchen"* beats *"a local-first culinary intelligence appliance."* No jargon, no acronyms without unpacking, no "AI" used as a synonym for "magic."

The voice is the same warm-kitchen-notebook voice as the app: practical, quietly confident, friendly without being chatty. Read it aloud — if any sentence sounds like marketing copy, rewrite it.

Cite what's true. Don't cite what's aspirational. If photo recognition needs Gemma 4 vision and that's still being built, the page says *"Coming soon — photo recognition uses a vision model we're integrating now"* — not *"Just snap a photo!"*

## Visual language

Same as the navigator app — see [`../design/DESIGN.md`](../design/DESIGN.md) for the full system. Carry forward:

- Terracotta seed (`#B85C38`), warm `surface` (`#FFF8F6`), kitchen-friendly tonal palette
- Gemini-influenced gradients: `gradient-thinking` (terracotta → amber → cream radial) used **once** in the hero, then sparingly as section accents
- Circles as foundational vessels — hero illustration, step numbers, audience portraits, hardware photo halos
- Soft, blurred shadows (no hard drop shadows)
- Pill-shaped buttons and chips (full radius), 32px on cards
- Type stack: `"Google Sans Text", "Inter", system-ui, sans-serif`
- "Thoughtfully imperfect" — illustrations are hand-drawn-feeling, not corporate-rigid

What's **different** from the app:
- The marketing page can use larger gradient washes (full-bleed hero, section dividers) — it's selling a *feeling* of warmth, not running utility
- Photography (or photo-realistic illustration) of real hardware is allowed and important — buyers need to see the actual physical thing they're getting
- Section transitions can use longer animation timing (600-900ms parallax / fade-in on scroll) — the navigator app uses 320ms; here we have permission to breathe

## Page sections (top to bottom)

The page is one long scroll. Six sections. No nav menu — that's a marketing-page anti-pattern when the page is short. The brand wordmark in the top-left is the only anchor element, fixed on scroll.

---

### 1. Hero

**Goal:** in five seconds, communicate (a) what this is, (b) who it's for, (c) what makes it different.

**Layout:**

- Full viewport height (100dvh) on first scroll. Centered content column, max-width 720px.
- Background: `gradient-warmth` base wash with a single large `gradient-thinking` radial blob (60vw diameter) positioned top-right, low opacity (0.4), heavily blurred (80px). On scroll, the blob parallaxes upward at half speed.
- **Wordmark top-left** (fixed, persists through scroll): "PantryAtlas" in `title` weight, `primary` color. To its right, a `caption`-sized line: "Open source · Runs on a Raspberry Pi"
- **Center hero illustration** (above headline): a circular vessel illustration, 240px diameter, hand-drawn — a Pi 5 in a small case sitting next to a wooden cutting board with vegetables. Soft `shadow-vessel` glow behind it.
- **Headline** (`display` size, 56sp on desktop, 40sp on mobile, weight 600, tracking −0.02em): *"Your kitchen's smart pantry. Lives in your kitchen."*
- **Subhead** (`headline` size, weight 400, `on-surface-variant`, max-width 560px): *"A small computer you set up once. It helps you cook from what's actually on the shelf — at home, or for a community of hundreds. Nothing leaves your kitchen. No subscription, no account."*
- **Two CTAs in a pill row** (centered, 16px gap):
  - Primary: filled pill, `gradient-ember`, "How to set it up" → smooth-scrolls to Section 4
  - Secondary: outlined pill, `primary` border + text, "See it on GitHub →" → external link
- **Scroll cue at bottom** (40px above viewport edge): a small chevron-down icon inside a 32px pill, subtle bounce animation (translate-Y ±4px, 2s loop). On reduced-motion: static.

---

### 2. What it is (the one-paragraph explainer)

**Goal:** the reader who isn't sure should walk away after this section knowing exactly what they'd be getting.

**Layout:**

- Centered column, max-width 640px, 96px vertical padding above and below
- Single `headline` line: *"It's a computer the size of a deck of cards that you keep in your kitchen."*
- Body paragraph (`body` size, 1.6 line-height):

> Plug it into a power outlet and your Wi-Fi. From any phone or laptop on your home network, open a browser and go to **pantryatlas.local** — that's the address of the little computer. Type what's in your pantry, or snap a photo of your shelf with your phone's camera. PantryAtlas reads what you have and shows you real recipes you can cook with it, ranked by what uses the most of what you've already got.

- A three-icon row below the paragraph (centered, 48px gap), each icon in an `outline-variant` circle (64px), label in `label` style below:
  - 🔒 *Stays local* — *"Your pantry never leaves the Pi"*
  - 📡 *No subscription* — *"Buy once. Yours forever."*
  - 🌍 *Open source* — *"Apache 2.0 — see every line of code"*

---

### 3. Two kitchens, one product

**Goal:** show the reader where they fit, with a concrete example for each.

**Layout:**

- Section heading, centered: *"Two kitchens, one product"* in `headline` weight
- Two large cards side-by-side on desktop (≥720px), stacked on mobile. 16px gap. Each card 32px radius, `surface-container-high` fill, `shadow-rest`, 32px padding.
- **Card 1: Home Kitchen**
  - Circular illustration (96px) at top: a hand-drawn family-of-four meal — bowl of stew, four spoons
  - Title in `title`: *"Home Kitchen"*
  - Subtitle in `label`, `on-surface-variant`: *"4 to 10 servings"*
  - Body in `body`: *"A weekday family meal. You open the fridge, see what's there, and PantryAtlas finds five recipes that use most of it without making you go shopping. Add 'expiring soon' tags so you cook the kale before it wilts."*
- **Card 2: Community Kitchen**
  - Circular illustration (96px): a hand-drawn institutional pot — large stockpot with serving ladle
  - Title in `title`: *"Community Kitchen"*
  - Subtitle in `label`, `on-surface-variant`: *"50 to 500 servings"*
  - Body in `body`: *"You run a soup kitchen, food pantry, or shelter meal program. A donation truck dropped off mixed produce, dry goods, and proteins. PantryAtlas ranks recipes that scale linearly, use bulk-friendly ingredients, and need minimum specialized equipment."*
- Below the two cards: a `caption`-sized line: *"You pick once on first launch. You can switch anytime from the top bar."*

---

### 4. How to set it up (the visual walkthrough)

**Goal:** make the non-technical reader believe they can do this. The whole page hinges on this section.

**Layout:**

- Section heading: *"Set it up in four steps"* in `headline`, centered
- Sub-line below, `body`, `on-surface-variant`: *"About 30 minutes the first time. Then it just sits there working."*
- Four numbered steps as full-width cards, stacked vertically, 32px radius, alternating `surface-container` and `surface-container-low` fill, 32px padding, 24px gap between cards:

**Step 1 — Get the hardware** (`label` "STEP 1" small caps above title)
- Title in `title`: *"Get the parts"*
- Body in `body`: *"You need a Raspberry Pi 5 (8GB), a microSD card (32GB or larger), a USB-C power supply, and a small case. Most kits bundle all four for around $120 from Amazon, Adafruit, or CanaKit. We list the exact kit we tested below."*
- A small product photo (illustrated or photographic) of a Pi 5 kit, 240px wide, on the right side of the card on desktop, below the body on mobile
- A pill-link below: *"See the recommended kit →"* → external link to a known kit listing

**Step 2 — Flash the card**
- Title: *"Copy PantryAtlas onto the microSD card"*
- Body: *"Download our pre-built image from GitHub. Use the free **Raspberry Pi Imager** app on your computer to write the image to the card. It takes about 8 minutes."*
- Two pill-links: *"Download image"* (filled `primary-container`) + *"Get Raspberry Pi Imager"* (outlined) → external links
- Below: a `caption`-sized expandable note: *"Already comfortable with Linux? You can also clone the repo and run our installer script — see the GitHub README."*

**Step 3 — Plug it in**
- Title: *"Plug the Pi into power and Wi-Fi"*
- Body: *"Put the microSD card into the Pi, plug in the power supply, and either connect an ethernet cable to your router OR follow the on-first-boot Wi-Fi prompt. After about a minute, a small light on the Pi turns solid green — that means PantryAtlas is running."*
- Illustration on the right: a circular vessel showing a Pi with a green LED, gentle radial pulse on the LED (CSS animation, 2s loop, respects reduced-motion)

**Step 4 — Open it on your phone**
- Title: *"Open pantryatlas.local in any browser"*
- Body: *"On your phone, tablet, or laptop — anything on the same Wi-Fi — open a web browser and go to **pantryatlas.local**. The first time, you'll pick Home Kitchen or Community Kitchen. Then you're done. Type ingredients, snap a photo of your shelf, get recipes."*
- A small "add to home screen" callout in a `tertiary-container` chip: *"On iPhone: tap Share → Add to Home Screen. It feels like a real app."*

**Below the four steps**, a centered reassurance line in `body`, `on-surface-variant`: *"Stuck? Email us, open a GitHub issue, or ask in the community Discord."* with the three pill-links inline.

---

### 5. What it can do (feature glance)

**Goal:** the reader who's now thinking *"OK but what's it actually like to use?"* gets a concise tour.

**Layout:**

- Section heading: *"What it does"* in `headline`, centered
- A three-column layout on desktop (single column on mobile), each column a soft card with a 64px circular illustration at top:
  - **Card A — Camera + typing**
    - Title: *"Snap a photo, or just type"*
    - Body: *"PantryAtlas reads photos of your shelf using Gemma 4 — a small but capable AI model that runs entirely on your Pi. No photo ever leaves the device."*
    - Footnote in `caption`: *"Photo recognition is in active development — typing works today."* (Remove this footnote once vision endpoint ships.)
  - **Card B — Ranked by what you have**
    - Title: *"Recipes ranked by your shelf"*
    - Body: *"Every recipe shows a coverage ring — 8/10 means you have 8 of the 10 ingredients. The recipes you can fully cook tonight surface first. Expiring ingredients get a boost."*
  - **Card C — Scales with you**
    - Title: *"Home or community scale"*
    - Body: *"In Community Kitchen mode, PantryAtlas favors recipes that scale linearly to hundreds of servings, use bulk-friendly ingredients, and need minimum specialized equipment."*
- Below the three cards: a screenshot of the actual app (the merged single-screen) at 720px wide, with a soft `shadow-active` and `gradient-vessel` halo behind it. On mobile, the screenshot scales to 90vw.

---

### 6. Open source, locally hosted, no strings

**Goal:** the privacy / trust / open-source story, made concrete.

**Layout:**

- Section heading: *"Yours, not ours"* in `headline`, centered
- Body paragraph, max-width 640px, centered, `body` size:

> PantryAtlas runs entirely on the Pi sitting in your kitchen. There is no cloud account. We don't see your pantry. We don't track what you cook. We don't sell anything to anyone. The code is Apache 2.0 — read it, fork it, audit it, run it. Recipe data comes from the public RecipeNLG corpus (CC-BY-NC-4.0) curated by Bień et al. Ingredient and flavor data comes from FlavorDB (CC-BY-NC-3.0) curated by Garg et al.

- A four-pill row of trust signals (centered, 12px gap), each a chip with `outline-variant` border:
  - "Apache 2.0" · "RecipeNLG CC-BY-NC-4.0" · "FlavorDB CC-BY-NC-3.0" · "No telemetry"

---

### 7. Get it (the closing CTA)

**Goal:** three clear paths forward, depending on how technical the reader is.

**Layout:**

- Section heading: *"Ready to set up your kitchen?"* in `headline`, centered
- Three options as side-by-side cards on desktop, stacked on mobile, each 32px radius, 32px padding, `surface-container-high`:
  - **Card 1 — Easiest** (`tertiary-container` accent bar at top)
    - *"Buy a pre-flashed microSD"* — *"We're partnering with a vendor to ship a microSD card with PantryAtlas pre-installed, plus the recommended Pi 5 kit. Sign up for launch notifications."*
    - Email-capture pill input + filled "Notify me" pill button
  - **Card 2 — DIY** (`primary-container` accent bar)
    - *"Build it yourself"* — *"Buy the Pi 5 kit from Amazon / Adafruit / CanaKit, download our image, follow the four steps above. About 30 minutes."*
    - Two pill-links: *"Download image"* + *"Setup guide"*
  - **Card 3 — Developer** (`secondary-container` accent bar)
    - *"Clone the repo"* — *"Comfortable with Linux and git? Clone the repo, run the installer script, or contribute. Apache 2.0."*
    - One pill-link: *"GitHub →"* external

---

### Footer

- Background: `surface-container-high`, 48px top padding, 32px bottom
- Centered column:
  - Wordmark "PantryAtlas" in `title` + tagline *"Use what you have, not what a recipe demands."* in `caption`
  - Three-column link grid (single column on mobile): **Project** (GitHub, License, Releases) · **Data** (RecipeNLG, FlavorDB, citations) · **Connect** (GitHub Issues, Discord, Email)
  - Bottom line in `caption`, `on-surface-variant`: *"© 2026 PantryAtlas project · Apache 2.0 · Built on a Raspberry Pi 5 in [city]"*

---

## Responsive behavior

Same one-column-on-every-viewport principle as the app, with two exceptions:

1. Hero illustration shifts from above-headline (mobile) to left-of-headline (desktop, two-column flex at viewport ≥960px)
2. Step cards (Section 4) and Get-it cards (Section 7) shift from stacked (mobile) to side-by-side (desktop, ≥720px)

Otherwise the page is a single linear scroll on every device. No carousels. No hidden-behind-tabs content.

## Motion budget (more generous than the app)

- Hero gradient blob: slow parallax on scroll (0.5× scroll speed)
- Section enter: 600ms fade + 16px Y-translate as each section crosses the viewport center, intersection-observer triggered, once-only
- Step cards: number circle pulses gently (scale 1.0 → 1.04 → 1.0, 2.4s loop, low-amplitude) when the step is the first one above the fold
- All animations respect `prefers-reduced-motion: reduce` — fall back to instant fade-in 200ms

## Accessibility

- All text meets WCAG AA contrast
- Hero illustration has `alt` text describing the scene ("Illustration of a Raspberry Pi computer next to vegetables on a cutting board")
- Step numbers are decorative — the step content is the source of truth for screen readers
- All external links open in same tab (no surprise tab-opens); GitHub link uses `rel="noopener"` only because it's external
- Email-capture form has visible label and clear error states
- The "add to home screen" callout includes platform-specific guidance for Android too (footnote not shown above — add: *"On Android: tap menu → Install app"*)

## What's NOT on the marketing page

For Stitch and downstream implementers — the deliberate-exclusion list:

- **No video demo** — keeps page weight low and works without JS for browsers with autoplay disabled. The screenshot in Section 5 is the demo.
- **No testimonials / quotes** — we don't have real users yet. Don't fabricate. Add this section after launch when we have one.
- **No pricing table** — there's no pricing. The hardware costs what it costs; the software is free.
- **No comparison-to-other-products table** — there are no equivalent products. We're not competing with grocery apps.
- **No analytics / tracking pixels** — site loads zero third-party scripts. The whole point of PantryAtlas is no surveillance; the marketing page lives that.
- **No cookie banner** — see above.
- **No nav menu** — the page is short enough that a smooth-scroll CTA in the hero covers any nav need.
- **No newsletter signup beyond the "Notify me" pre-flashed-card form** — single-purpose capture, not a generic mailing list.

---

## Stitch handoff notes

When generating marketing-page mockups via Stitch against project `12279110322585036502`:

1. Submit this MARKETING.md as a **second** design brief via `upload_design_md` (use a different filename so it doesn't overwrite the navigator brief).
2. Generate **two** mockups: hero + Section-4 setup walkthrough at desktop and mobile widths (4 PNGs total). The rest of the page Stitch can extrapolate from the brief once those two are right.
3. Reference the visual-language section explicitly — Stitch should pull the gradient tokens and circle-as-vessel framing from the linked navigator DESIGN.md rather than re-deriving them.

---

*Design system version: pantryatlas.org marketing page · companion to Navigator v0.2.0 · 2026-05-27*
