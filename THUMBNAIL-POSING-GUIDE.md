# Thumbnail Posing Guide — for Nano Banana (and you, on the day)

This is what to feed nano-banana-pro so it makes a YouTube thumbnail that stops the scroll,
and how to stand/look when you shoot the reference photo it edits from. Grounded in your own
consensus doctrine (3 elements max, readable tiny, high contrast, show the result, closed mouth).

The best face thumbnails are a real emotion pointed at a clear payoff. Nano banana can build the
scene, but it can only preserve a face it's given. So the move is: shoot a clean reference photo of
yourself in the right pose, then let nano banana drop you into the composition.

---

## The 6 rules nano banana keeps breaking (put these in every prompt)

1. **Closed mouth.** Open-mouth shock reads as clickbait and your audience punishes it. Say
   "mouth closed, subtle expression" explicitly. Nano banana defaults to open-mouth if you don't.
2. **Three elements, no more.** Your face, one object, one piece of text. That's it. A busy thumbnail
   dies at phone size. Say "clean composition, only 3 focal elements, lots of negative space."
3. **One clear payoff object.** The thing the video delivers, shown, not described. The terminal, the
   app on the phone, the $0, the red-X'd logo. Name it concretely.
4. **High contrast, phone-legible.** "Bold high-contrast lighting, subject clearly separated from
   background, readable at thumbnail size."
5. **Eyes to camera or to the payoff.** Either you look dead at the viewer, or you look at the object
   with obvious reaction. Never look at nothing.
6. **Big, short text.** 2 to 4 words max, heavy sans-serif, one color. The title does the talking;
   the thumbnail text is the punch. Often a number or a "$0".

---

## The 5 poses that work for your channel

Pick one per thumbnail. Each has a reference-photo direction (how to stand when you shoot yourself)
and a nano-banana prompt scaffold (what to type). Fill the [BRACKETS].

### 1. THE DISBELIEF (your default — the synth panel's winner)
Best for: "I replaced/killed/cancelled X." Mild disbelief that this actually worked.
- **Shoot yourself:** chest-up, square to camera, chin slightly down, eyebrows up a touch, mouth
  closed with the faint start of a smirk. Think "I can't believe that worked." NOT wide-eyed shock.
- **Prompt scaffold:**
  > Photorealistic YouTube thumbnail, 16:9. A man looking at the camera with mild disbelief, mouth
  > closed, eyebrows slightly raised, as if he just realized something worked. On the [LEFT/RIGHT],
  > [THE PAYOFF OBJECT, e.g. "a software logo labeled '$40/mo' with a large red X through it"]; on the
  > other side [THE CONTRAST, e.g. "a laptop terminal showing '$0'"]. Bold high-contrast studio
  > lighting, subject clearly separated from a dark background, clean composition, only 3 focal
  > elements, lots of negative space, readable at small size. No open mouth, no clutter.

### 2. THE POINT
Best for: "here's the thing / look at this result." You point at the payoff.
- **Shoot yourself:** turned ~15° off-axis, one hand up pointing toward where the object will sit
  (leave that side of frame empty), looking at the object, mouth closed, slight "check this out" brow.
- **Prompt scaffold:**
  > Photorealistic YouTube thumbnail, 16:9. A man turned slightly, pointing toward [THE PAYOFF OBJECT]
  > on the [SIDE], looking at it with a confident closed-mouth expression. [OBJECT described concretely].
  > High-contrast lighting, subject separated from background, 3 elements max, big empty space for text,
  > phone-legible. Mouth closed.

### 3. THE HOLD
Best for: "I built this." You hold the thing (phone with the app, etc.).
- **Shoot yourself:** hold the phone/object up beside your face at chest height, screen toward camera,
  looking at the camera with quiet pride, mouth closed.
- **Prompt scaffold:**
  > Photorealistic YouTube thumbnail, 16:9. A man holding up [THE OBJECT, e.g. "a smartphone showing a
  > clean planner app"] beside his face, looking at the camera, calm confident closed-mouth expression.
  > The screen is clearly visible and sharp. High-contrast lighting, dark background, 3 elements, room
  > for a short bold headline, readable at thumbnail size.

### 4. THE REACTION-TO-SCREEN
Best for: the honesty/roast beats (Reggie, "it told me no," the verdict).
- **Shoot yourself:** in profile or 3/4, looking at a screen just off-frame, a wince or a flat
  "oof" reaction, mouth closed. The screen glow on your face.
- **Prompt scaffold:**
  > Photorealistic YouTube thumbnail, 16:9. A man in 3/4 view reacting to a computer screen off to one
  > side, closed-mouth wince, screen glow on his face. Beside him, [THE HARSH LINE as big text, e.g.
  > "'DON'T SHIP THIS'"]. Moody high-contrast lighting, dark background, 3 elements, phone-legible.

### 5. THE SPLIT (before / after, no reaction needed)
Best for: comparison, "$40 vs $0," "5 apps." Sometimes your face is small or absent.
- **Shoot yourself (if included):** small, corner, closed-mouth, looking at the payoff side.
- **Prompt scaffold:**
  > Photorealistic YouTube thumbnail, 16:9, split composition. LEFT: [BEFORE, e.g. "a subscription
  > bill '$40/MO' with a red X"]. RIGHT: [AFTER, e.g. "a terminal reading '$0 FREE'"]. Optional small
  > man's face in a bottom corner, closed mouth, looking toward the right side. High contrast, bold,
  > only these elements, huge readable text.

---

## Reference-photo checklist (30 seconds before you shoot)
- Even light on your face, no harsh shadow across it (nano banana edits cleaner from a clean source).
- Plain background if you can (it'll be replaced, but clean edges preserve your likeness better).
- Chest-up framing, you fill the middle third.
- Mouth closed. Shoot 3 expressions: neutral, mild disbelief, slight smirk. Pick the truest one.
- Same shirt/look you use on camera, so your thumbnail matches your video.

## How to actually make it
- In **scout studio** → the Thumbnail tab: paste a scaffold, drop your reference photo, hit Generate.
  It uses nano-banana-pro-edit so your face is kept. Generate 3, keep the best.
- Or the `media-gen` skill directly: `image --model nano-banana-pro-edit --input-image you.jpg
  --aspect-ratio 16:9 --prompt "..."`.
- Then load the winner onto your preview card in studio and see it sit in the real feed before you commit.

## The honest bit
Nano banana gets you a strong draft fast. It will occasionally add a finger or soften your face.
Regenerate rather than ship a warped one. And the only real test is A/B on the channel, which studio
can preview but only YouTube settles.
