# Public semantic-grounding evidence

`01-public-semantic-grounding.mp4` is the public, post-submission supplementary
online evidence recording. It was produced from the adjacent Playwright WebM
capture with the explicit command used by `scripts/record_public_evidence.py`:
`ffmpeg -i input.webm -c:v libx264 -preset medium -crf 28 -pix_fmt yuv420p
-movflags +faststart output.mp4`.

It demonstrates three safe public prompts and visible answers/sources in a fresh
browser context. It does not open Google Forms Responses, log in, store cookies,
or include pilot participant data. This clip is online semantic/source evidence
only; it makes no offline, ASR, TTS, microphone, or model-identity claim.

The adjacent JSON file records both media paths, SHA-256, byte size, codec,
duration, source URL, source revision and timestamp. The WebM capture remains
local; only the small MP4 is committed for review.
