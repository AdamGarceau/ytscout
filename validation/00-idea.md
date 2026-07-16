# 00 — Idea + Kill Criteria (ytscout)

## The idea, in Adam's words
"Make me a tool that does the things vidIQ and TubeBuddy do but for me and for free. Anything you can do with an API to make this whole process easier, do it."

## The job it does
Give Adam the same idea-selection and packaging leverage the paid YouTube tools sell, without a subscription and without sending his channel data to a third party. Grounded in the consensus doctrine (`~/content-engine/strategy/youtube-consensus-doctrine.md`), which named the single highest-leverage function across 6 independent research corpora: **outlier hunting** (find videos whose views massively beat their channel's subscriber count, then model the concept into your niche).

## Who it's for (hypothesis)
Adam, for two channels. Not a market product (see kill criteria).

## What it must do (from the doctrine, in priority order)
1. **Outlier finder** — the #1 idea-validation method. Pull a channel's videos + comparable-niche channels, compute view-to-subscriber ratio, rank the outliers.
2. **Title/packaging analyzer** — score a proposed title against the data-study rules (6-7 words, <60 chars, no long-form emojis, psychological frames, specific numbers).
3. **Niche/keyword research** — yt-dlp search to see what ranks for a term, view distribution, saturation read.
4. **Channel audit** — pull a channel's public-visible metrics, flag packaging/length/consistency issues.

## Kill criteria (written before building, so the bar can't bend)
- **DON'T BUILD if:** the free/keyless path can't get the data (it can — yt-dlp gives channel dumps, per-video view counts, subscriber counts, and transcripts with no API key); or a good-enough free incumbent already exists as a local tool Adam would use (none does — vidIQ/TubeBuddy are paid SaaS that upload your data).
- **BUILD FOR MARKET only if:** there's a nameable audience gathering somewhere paying for or painfully working around exactly this, AND a distribution path Adam can reach. There isn't a clean one — "free YouTube tool" is a saturated red ocean and a maintenance burden. So this is capped at BUILD FOR SELF by design.
- **BUILD FOR SELF if:** the pain is Adam's, real, and the free path works. It is and it does.

## Run mode chosen
Speed-run (BUILD FOR SELF). Main-thread build under the Claude spend cap; local tooling only.
