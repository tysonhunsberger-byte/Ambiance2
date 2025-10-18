# Carla integration on Windows

The Carla host ships with this repository under `Carla-main/`, but the Python
bridge expects a compiled runtime.  Windows users can either build Carla from
source with MSYS2 or reuse an existing binary release.  The integration shipped
with Ambiance automatically looks under `Carla-main/`, `%PROGRAMFILES%\Carla`,
and `%PROGRAMFILES(X86)%\Carla` to locate the runtime, and it adds the
necessary DLL directories to `PATH` at runtime.

## Option 1 – Build with MSYS2

1. Install [MSYS2](https://www.msys2.org/) and launch the *MSYS2 MinGW 64-bit*
   shell (or the *MSYS2 UCRT64* shell if you prefer the UCRT toolchain).  Git
   Bash does **not** ship with `make`, so make sure you are inside an MSYS2
   shell before continuing.
2. Install Carla's build dependencies, including `make` itself:

   ```bash
   pacman -S --needed \
       make git cmake \
       mingw-w64-x86_64-toolchain mingw-w64-x86_64-qt5 \
       mingw-w64-x86_64-pkg-config mingw-w64-x86_64-fftw \
       mingw-w64-x86_64-liblo mingw-w64-x86_64-ntldd-git \
       mingw-w64-x86_64-fluidsynth mingw-w64-x86_64-dlfcn
   ```

3. Inside the MSYS2 shell, change into the Carla source directory bundled with
   Ambiance and build the standalone library:

   ```bash
   cd /c/path/to/ambiance/Carla-main
   make win64
   ```

   The build produces `libcarla_standalone2.dll` under
   `Carla-main/build/win64/Release/` together with the dependency DLLs.

4. Export the build location so Ambiance can find it (Command Prompt syntax):

   ```bat
   set CARLA_ROOT=C:\path\to\ambiance\Carla-main
   ```

   PowerShell users can instead run:

   ```powershell
   $env:CARLA_ROOT = "C:\path\to\ambiance\Carla-main"
   ```

## Option 2 – Use a binary release

1. Download the latest **Carla Windows** archive from the
   [official releases](https://github.com/falkTX/Carla/releases).
2. Extract it somewhere under `C:\Program Files\Carla` (or
   `C:\Program Files (x86)\Carla`).
3. Launch Ambiance from the same shell session so it can discover the install.

The Ambiance Carla integration automatically injects the Carla DLL directories
into the current `PATH`, so no manual environment tweaks are required after the
first run.
