# JUCE VST3 Hosting in Ambiance

The Noisetown UI now exposes a **Desktop Plugin UI Bridge** section that can
launch a native JUCE application whenever you need to see a plugin's real UI.
This document explains how that bridge works, why it must rely on an external
process, and how it relates to typical "VST rack" products.

## Why we cannot embed a VST3 UI in the browser

VST3 plugins ship native UIs rendered with platform specific toolkits (Win32,
CoreGraphics, Metal, etc.).  They expect to talk directly to an OS level window
with real-time access to GPU compositing and audio/MIDI devices.  A Python web
server – especially inside this restricted execution environment – lacks all of
those capabilities.  Even if we could run the plugin code, streaming its UI into
the browser would require a remote desktop style compositor plus low latency
audio forwarding.  That's exactly what commercial VST racks solve with large
native codebases.

To give you something usable today we bridge Ambiance to a standalone JUCE
application.  JUCE already contains all of the glue code required to host VST3
processors and to embed their editors in a desktop window.  By running it
outside the sandbox you retain the real-time responsiveness and hardware access
that plugins demand.

## Building the JUCE host

1. Ensure you have the JUCE sources available locally.  Point the
   `JUCE_ROOT` environment variable at the JUCE checkout (or supply it when
   configuring CMake).
2. Configure and build the host:

   ```bash
   cd cpp/juce_host
   cmake -B build -DCMAKE_BUILD_TYPE=Release -DJUCE_ROOT=/path/to/JUCE
   cmake --build build
   ```

   On Windows you can use the Visual Studio generator.  Make sure the JUCE path
   uses forward slashes (or doubled backslashes) so CMake does not treat
   sequences such as `\U` as escapes:

   ```powershell
   cmake -S . -B build -G "Visual Studio 17 2022" -A x64 -DJUCE_ROOT=C:/dev/JUCE-master
   cmake --build build --config Release
   ```

3. Optionally export the resulting binary for easier discovery.  JUCE's CMake
   helpers place artefacts inside a `_artefacts` folder by default.  On Visual
   Studio you'll find the executable at
   `build/JucePluginHost_artefacts/Release/JucePluginHost.exe`; single-config
   generators produce `build/JucePluginHost_artefacts/JucePluginHost`.  Point
   the variable at whichever path your toolchain produced:

   ```bash
   export JUCE_VST3_HOST="$(pwd)/build/JucePluginHost_artefacts/Release/JucePluginHost.exe"
   ```

   Replace `Release` with `Debug` (or the appropriate configuration) if you
   built a different flavour, and substitute the non-suffixed
   `JucePluginHost_artefacts/JucePluginHost` path when using a single-config
   generator such as Ninja or Makefiles.

On macOS the JUCE app bundle lives inside
`build/JucePluginHost_artefacts/JucePluginHost.app`.

### Loading different plugin packages

The host understands common VST packaging conventions:

* **Loose files** – point it at a `.vst3`, `.dll`, `.vst`, `.component`, or
  `.vstbundle` and the correct JUCE format loader is selected automatically.
* **Archives** – if you have a plugin zipped up (for example,
  `AwesomeSynth.vst3.zip`), pass the zip path on the command line.  The host
  extracts the archive to a temporary directory, locates the plugin bundle, and
  loads it before presenting the native editor.

Any temporary extraction directory is removed when you close the host window, so
you can keep archives around without manually unpacking them each time.

## Using the Desktop Plugin UI Bridge

* Start the Ambiance server (`python -m ambiance.server`).
* Open the Noisetown UI in your browser.
* Scroll to the **Plugin Rack** block and locate the **Desktop Plugin UI
  Bridge** section.
* Select a plugin in the library and press **Open in Desktop Host**.  The
  browser asks the backend to launch the JUCE application with that plugin.
* Interact with the plugin editor in the native window.  The audio streams
  through your OS level device, so you hear changes instantly.
* When you're done, use **Close Desktop Host** to terminate the JUCE process.

The bridge reports whether the host binary is missing, already running, or if
an error occurred.  That diagnostic flow should make it clear why the UI could
not open (e.g. the plugin path was invalid).

## How this compares to dedicated VST racks

Commercial racks (Gig Performer, Blue Cat PatchWork, etc.) are full desktop
applications.  They embed plugins, provide routing/mixing, expose automation,
and often include their own MIDI mappings.  Ambiance focuses on generative
rendering and web-based control, so we lean on the JUCE host for the pieces that
require real-time access to hardware.

Because the bridge lives out-of-process you can iterate on the JUCE host
independently: add MIDI keyboard capture, expose automation over OSC, or extend
it into a DAW-like interface.  The Python side remains responsible for library
management and routing, deferring to JUCE whenever the genuine plugin UI is
required.

