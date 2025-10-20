# Creative Synthesis Roadmap (Beginner Friendly)

This guide collects the open synthesis ideas that keep appearing in Ambiance's TODO list and support conversations.  It is written for curious musicians who may be new to coding but want to understand where the project is headed and how they can experiment today.

## 1. Strudel-style pattern sequencing

Strudel is a browser-based spin on TidalCycles.  It lets you describe rhythmic patterns with tiny snippets such as `bd sn bd sn` and immediately hear them loop.  The Ambiance TODO currently tracks “Integrate Strudel-style pattern language into audio engine (parser, scheduler, UI).”

To make that happen inside Ambiance, we can break the work into approachable steps:

1. **Embed a pattern scratchpad.**  Add a text panel beside the stream controls where you can type Strudel patterns.  Start with a handful of built-in examples and a “play” button so you can hear something without writing code.
2. **Parse patterns in Python.**  Use a small parser (e.g., `parsimonious` or `lark`) that understands Strudel’s mini-language.  Each pattern expands into a list of time-stamped events (which sample to trigger, which stream, which effects snapshot).
3. **Schedule events on the engine clock.**  Feed those events into the existing stream controllers by calling `set_crossfade`, `set_volume`, or `load_file` at the right beats.  A 16th-note scheduler driven by Qt’s timer is sufficient for a first pass.
4. **Provide friendly feedback.**  Highlight the active beat inside the scratchpad, and surface errors (such as typos) in a toast message so non-programmers know what went wrong.

If you want to experiment before the full integration lands, visit [https://strudel.tidalcycles.org/](https://strudel.tidalcycles.org/) and try the interactive tutorials.  Anything you create there can later inform the patterns we support in Ambiance.

## 2. SuperCollider exploration

SuperCollider (SC) is a powerful synthesis server used by TidalCycles, FoxDot, and Sonic Pi.  Integrating SC with Ambiance opens access to thousands of synth definitions without rewriting them in Python.  Here’s how a phased approach could look:

1. **Proof of concept:** Use `python-osc` to send `/s_new` messages from Ambiance to a local SuperCollider server.  Map a single stream’s tone/noise controls to an SC synth definition so the UI sliders drive SC in real time.
2. **Preset bridge:** Bundle a handful of SC `.scd` synthdefs (pads, plucks, drones) and expose them in the stream “Tone” module as extra wave choices.  Users can preview them with one click.
3. **Pattern handoff:** Once Strudel-style patterns exist, translate each event into SC OSC messages.  That keeps timing tight while Ambiance still handles file playback and effect automation.
4. **Packaging:** Document the setup so beginners just install SuperCollider, run `s.boot;`, and click “Connect to SC” inside Ambiance.  Provide a fallback (pure pyo) so nothing breaks if SC is unavailable.

Recommended resources for learning SuperCollider:

- **Awesome SuperCollider:** curated learning links — <https://github.com/madskjeldgaard/awesome-supercollider>
- **Official SuperCollider repo:** the language and server sources — <https://github.com/supercollider/supercollider>
- **Practical intro:** the “Getting Started” section of the SC help browser (within the app) walks you through playing your first synth in minutes.

## 3. Quick wins for newcomers today

Even before pattern or SC integration lands, you can explore synthesis with the tools already in Ambiance:

- **Tone module:** enable it, choose “sine,” and slide the “beat” control to hear binaural beating.  The “Preset” menu picks musical frequency offsets for you.
- **Noise module:** switch between white, pink, and brown noise to sculpt texture.  The “Tilt” slider quickly darkens or brightens the noise.
- **FX & Space:** mix in delay, distortion, and reverb to shape the raw tone/noise into pads or atmospheres.

Try stacking two streams: one playing an audio file and the other using the tone/noise generators for a drone underneath.  Small adjustments to crossfade, pan, and EQ go a long way.

By pacing the roadmap this way we keep the door open for deep integrations (Strudel and SuperCollider) while making sure today’s UI feels inviting for anyone new to synthesis.
