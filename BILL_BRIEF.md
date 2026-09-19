# Bill: the robot band in two minutes

**The lamp is the frontperson. The guitar is its bandmate.** The lamp takes requests, talks to the crowd, sings through the audio system, dances, introduces solos, and visibly reacts to the guitarist. The guitarist plays accompaniment and takes the spotlight when invited.

First perfect five prepared songs that judges can request in any order. Unfamiliar songs need an arrangement the mechanism can play, prepared vocals, and validation before performance.

## How it works

```mermaid
flowchart TD
    Crowd[Audience requests and reactions] --> Master[Master Astra: musical director]
    Master --> Lamp[Lamp specialist: voice, movement, attention]
    Master --> Guitar[Guitar specialist: two instrument arms]
    Lamp --> Timing[One shared musical clock and scheduler]
    Guitar --> Timing
    Timing --> Show[Lamp motion + guitar playing + vocal audio]
```

Astra decides **what happens next**. Local controllers execute **when and how it happens**. Preparing phrases ahead keeps cloud response time off the beat. Both robots share one song timeline.

New abilities become registered actions: `groove`, `look_at_guitar`, `say`, `sing_phrase`, `give_solo`, and `bow`. Each declares its timing, requirements, and limits.

## What we learned by moving the lamp

- Five axes: base turn, lower-arm tilt, elbow, head roll, and head pitch. Commands use **-100 to 100 values, not degrees**.
- **21 physical trials** covered every axis, three yaw speeds, and coordinated sway. Yaw/roll were promising for precise accents. The loaded elbow missed targets by roughly 6–8 units in this pose.
- “OK” arrives before movement finishes. The band needs measured completion and a scheduled-start extension to the existing guarded runtime.
- Normal idle was restored. Visual naturalness still needs the laptop camera view.

## What needs fixing before a show

The lamp selects **Dummy Output**; audible singing is not ready. The directional microphone array was not detected. Its camera view is obstructed and vision inference disabled. The SDK needs a token.

The guitar reference provides simulation/transcription work; real arms and note timing remain unverified. We currently have only lamp access.

Use prepared singing audio and separately generated banter. A reliable PA carries vocals/backing alongside the actual live guitar.

## What makes them feel like a band

The lamp cues a solo, faces the guitar, gives it space, celebrates its final phrase, then leads a shared downbeat. Crowd reactions happen at musical boundaries. Stillness and anticipation matter as much as dancing.

Duet video references are linked in the architecture; playback retrieval was blocked, so visual study remains pending.

## Recommended next step

**Commission lamp camera/audio and build a reliable gesture harness.** Rehearse one short song scene with a simulated guitar, connect the real arms, then expand to five songs with recovery from network/model failures.

Candidates: *Seven Nation Army*, *Country Roads*, *Stand by Me*, *Jolene*, and *Billie Jean*. Song/version choices are pending; none is ready yet.

Full protocol, measurements, source references, failure behavior, and build gates: [ARCHITECTURE.md](ARCHITECTURE.md).
