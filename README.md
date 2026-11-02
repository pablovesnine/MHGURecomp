# MHGU Recomp - Linux ARM64

Linux ARM64 adaptation of [morerokk/MHGURecomp](https://github.com/morerokk/MHGURecomp). Running the game requires your own complete **MHGU 1.4.0** dump.

## AI Usage Disclosure

This fork uses code adapted for Linux ARM64 with the assistance of an AI coding agent, porting the original x86_64 implementation from [morerokk/MHGURecomp](https://github.com/morerokk/MHGURecomp). All generated changes, build configurations, and tests were reviewed and verified for functionality on ARM64.

## What it adds over the Switch version

- Graphics settings (resolution, MSAA, FXAA, Supersampling, VSync)
- Any widescreen aspect ratio (16:10, 16:9 and and anything wider than that)
- Frame rate cap anywhere between 30-240 fps
    - Bugfixes for speed-related issues that emulators normally have when using higher FPS mods/codes
- Supports almost every controller under the sun
- Experimental KB+M controls
- Optional: small monsters are properly synced between players in multiplayer
- Optional: monster HP scaling by playercount
- Fast-forward unskippable cutscenes by pressing A
- Optional: village quests are playable in multiplayer (press L/R at the quest counter), with appropriately re-scaled monster HP
- Mod support. The vast majority of mods work by dropping them into the `mods` folder, including Forge mods. (see [Mods](#mods))
- Cheat codes in the same format as Ryujinx and Atmosphère, in the `cheats` folder (see [Cheats](#cheats))
- Ingame PC Settings menu overlay (F1 or `Plus`+`Minus` to open)
- Working online multiplayer servers, in public or with friends (use "Local Wireless" menu)
- Discord Rich Presence (optional)

## Download

I publish my ARM64 builds in [Releases](https://github.com/pablovesnine/MHGURecomp/releases/tag/0.13.1). Download a package and follow [Install](#install), cloning is not required. To build your own package instead, follow the steps on [Build](#build).

## Screenshots

I tested this release on **AYN Odin 3** with [ArmadaOS 20261010](https://github.com/armada-os/armada): running at **~120 FPS in Eco mode**, working online multiplayer, and morerokk's custom menu with all its features working.

![MHGU gameplay on AYN Odin 3](docs/screenshots/ayn-odin3-gameplay.jpg) ![Online multiplayer lobby list](docs/screenshots/ayn-odin3-online.jpg) ![morerokk's custom settings menu](docs/screenshots/ayn-odin3-menu.jpg)

## Settings

Everything is in `mhgurecomp.ini`, each setting is explained in the file itself. The settings menu changes them in
the game: **F1**, or **Minus + Plus** on a controller (Back + Start on an Xbox controller). Frame rate, FOV, draw distance,
anti-aliasing, VSync, controls and volume apply when you save; the settings marked * at the next start. Details:
[docs/SETTINGS_UI.md](docs/SETTINGS_UI.md). In short:

- `[Display]`: `Mode` (Borderless / Fullscreen / Windowed), `Resolution`, `RenderResolution` (the 3D resolution),
  `AspectRatio` (Auto follows the window: 16:10 and anything wider fill it, narrower gets 16:10 with bars), `FOV`
  (1.0 = the game's), `UIAnchor` (Center keeps the HUD in the middle 16:9 on an ultrawide screen, Edges spreads it
  to the sides)
- `[Anti-aliasing]`: `MSAA` (Off / 2x / 4x / 8x), `FXAA` (On / Off), `FXAAMode` (Original / 3_11: FXAA 3.11 in
  place of GU's FXAA, sharper textures; default Original)
- `[Upscaler]`: `FSR` (Off / On, default Off), `FSRQuality` (NativeAA / Quality / Balanced / Performance /
  UltraPerformance), `Sharpness`. FSR replaces MSAA and FXAA while it is on. Details: `docs/FSR-PORT.md`
- `[Graphics]`: `DrawDistance` (how far away people in the villages and the Hubs are still drawn: 1 = the game's,
  2 = twice as far, 0.5 = half, 0 = no limit; up to 10)
- `[Performance]`: `FPS` (30 to 240), `VSync` (On / Off; above your monitor's refresh rate, turn VSync off), `ShaderPrewarm`
  (On / Off: translate all of the game's shaders in the background at startup, so fewer things are drawn black the
  first time they appear; the first start takes about 20 s for it, during the logos, and the cache folder needs about
  340 MB). `pipelines.list` next to the exe lists the shader combinations the common areas use; with the prewarm on,
  they are prepared in the background as well, so entering those areas for the first time no longer shows surfaces
  briefly black. Only made with MSAA Off; the rest is still prepared the first time it is needed.
- `[Controls]`: `FaceButtons` (Position / Label), `MenuConfirm` (the settings menu's confirm button),
  `BackgroundInput` (On / Off: the controller keeps working while the game's window is in the background, such as
  with a wiki in front of it; default On), `ComboInputWindow` (Lenient / Strict: how long the game waits for a
  second button for inputs like the Hunting Horn's X+A; Lenient, the default, as long as at 30 fps at any frame
  rate, Strict a fixed number of frames, shorter the higher the frame rate)
- `[Mouse]`: `MouseSensitivity` (1 = default, 0.1 to 10)
- `[Multiplayer]`: `Port`, `Join` (addresses of hosts outside your LAN), `Server` (hub server for internet hubs:
  empty = the default, `Off` = none, or `host[:port]`), `Key` (matchmaking key: only players with the same key see
  each other's hubs; empty = public, on Android public among Android players only), `SyncSmallMonsters`,
  `ShareUrgentCredit` (default On: an Urgent quest someone else posted counts for you too when you clear it, if you
  have unlocked it yourself)
- `[Monster HP]`: HP factors for 1 to 4 hunters in Hub quests, and per-quest exceptions (default: all 1, the
  original game)
- `[Village Quests]`: `VillageQuestsInHub` (default On), `HubHP` (default 2.0: Village quests posted in the Hub
  multiply their monsters' HP by this first, then by the `[Monster HP]` factor)
- `[Discord]`: `RichPresence` (default On: your Discord profile shows where you are, the monsters you're hunting
  and the map, how many are in your hub or quest; Discord must be running on the same computer), `ShowHunter`
  (default On: your hunter's name, HR and weapon type too)
- `[Bonus Content]`: `BonusContent` (default On), see below
- `[Audio]`: `Volume` (0 to 100: the whole game), `MuteInBackground` (On / Off, default Off: no sound while the
  game's window is in the background)
- `[Application]`: `ConfirmExit` (ask before the window closes), and the settings menu's `Language` (English /
  Spanish), `ButtonIcons` (Xbox / Switch / PlayStation), `Theme` (Hunter, the default / Gold / Blue: the settings menu's colours) and
  `MenuScale` (50 to 200 percent), and `Updates` (Ask / Auto / Off: what `mhgurecomp-updater` does, see "Staying up
  to date"). With the mouse, drag the top of the settings menu (its tabs) to move it, and the grip at its bottom right
  corner to size it; Menu Options > Attach menu puts it back in place.

### Multiplayer

For more details please refer to [morerokk/MHGURecomp](https://github.com/morerokk/MHGURecomp).

Over LAN or a VLAN, this should work out of the box.

Over the internet, through a hub server: hubs you create are listed on it and Search Hubs shows the hubs listed there, no port forwarding needed. To play only with your friends, all of you enter the same matchmaking key ("Matchmaking key" in the settings menu, or `Key =` in the .ini); without a key your hubs are public. The hub server is set with `Server =` ("Hub server" in the settings menu). If the hub server can't be reached, a notice at the top of the screen says so (your hub is then only visible on your local network); "Check hub server" in the settings menu tests the server and key you entered. Changes to both apply without a restart.

Without a hub server, the host needs to forward the right port (39500 TCP/UDP by default), the client needs to configure the host's IP address in their .ini file. (`Join = xxx.xxx.xxx.xxx`)

Choose the "Local Wireless" multiplayer options, as this port pretends to be a local nearby Switch with a wireless connection. The online options are unavailable and are unnecessary.

### Bonus content

By default, the `bonus` subfolder in releases contains a savegame with all the free online content (event quests, item packs, palicoes), which will be copied into your savegame when the game starts the 2nd time.

If you don't want this, set `BonusContent = Off` or don't provide a savegame in the `bonus` subfolder. You can also provide your own savegame instead if you want. Note that this port will not attempt to copy bonus content if such bonus content already exists.

### Mods

To install a mod, put the mod folder in `mods\`. Remove the folder to uninstall said mod. Mods are layered over the game at startup.
- romfs mods (files that replace or add game data) are found inside the mod's folder, including the
  `atmosphere\contents\0100770008DD8000\romfs` layout.
- When several mods ship the same game archive (such as `resident_eng.arc`), only the entries each mod changed from the
  game's are applied, so mods that change different files in it work together. If two mods change the same entry,
  the one later in load order wins, and the log says so ("changes ..., which an earlier mod changed too"). Mods load in
  alphabetical order. To choose the order, make `mods\load_order.txt` with one mod folder name per line: then only
  the mods listed load, in that order. The merged archives are kept in `cache\arcmerge\`.
- The **Mods** tab of the settings menu does this without editing files: it lists the mod folders, turns each on or
  off, moves them up or down, and writes `mods\load_order.txt` when Save is pressed (restart to apply; mods you add
  later load too, after the listed ones, until you turn them off; a mod turned off keeps its place in the order). It also compares the mods and lists the ones that change the same game files (and which of
  the two is used), and can apply a suggested order, with the mods that change the most files first.
- exefs patches (`.pchtxt`, `.ips` / IPS32) are applied, to data and to code. The game's code is precompiled, so a
  function a patch changes runs in an interpreter instead (a little slower, only that function). A mod's own code
  modules (`exefs\subsdk1` and so on, as in the
  [MH4U Port](https://github.com/Scrimas/MH4U-port-to-MHGU)) are loaded and run in the interpreter too. The log says
  what was patched and loaded (`[mods]` lines).
- Forge plugins (`.nro` in `romfs\nativeNX\plugins\`) are loaded. Forge's own loader (the `exefs\subsdk9` that
  Forge and mods with Forge plugins include) is not needed and is passed over: the port runs the plugins itself. Forge's menu with the plugins' settings opens with
  Insert (or the key in Forge's own `config.ini`, if a mod includes Forge's files, which can also set `[log] level`);
  use the mouse, keyboard or controller in it. While it is open the game gets no controller input. Window positions
  are kept in `forge_imgui.ini`.
- You do not need any resolution, FPS cap or connection fix mods. These features are included with this port.

If you are newer to the game, I very strongly recommend the [Key Quest Markers](https://gamebanana.com/mods/727960) mod by PurplefinNeptuna. This marks out the Village and Hub quests you need to complete for the next tier directly in the quest menu, which means you no longer need a wiki to play the game.

**Good places to get mods:**

- [The MHGURecomp-Mods repo](https://github.com/Oddity-git/MHGURecomp-mods)
- [GameBanana](https://gamebanana.com/mods/games/17088)

### Cheats

Put `.txt` files with cheat codes in `cheats\`. Every cheat in them is on from the start, unless you turned it off. Codes made for Ryujinx or a
modded Switch work as they are, as long as they are for version 1.4.0. A file can hold any number of cheats, each
starting with its name in square brackets:

```
[Skill points x2]
04000000 000DFAB4 E1A00080
```

- Turn single cheats on and off in the settings menu (F1), on the Cheats tab: it takes effect when you press Save,
  without a restart, and is remembered in `cheats\_off.txt`. Turning off a cheat that changes the game's code puts
  the original code back; values a cheat already changed (money, items) stay as they are. Master codes (`{Name}`)
  are always on. Cheats added to the folder show up after a restart. Online, only use cheats when everyone in the
  lobby agrees to it.
- To turn off a file without deleting it, start its name with `_`.
- Cheats that change the game's code also work: the port runs each changed function in an interpreter. That
  function runs slower, which only matters for functions the game calls very often.
- `log.txt` lists the cheats it loaded, and any it couldn't read.
- `extras\cheats\` in the source has two cheats that double the skill points from armor, weapon and talisman
  decorations, and talismans (with Double Talisman, talisman points go x4). `Skill points x2` doubles negative
  points too; `Skill points x2 (positive only)` leaves them as they are. Use only one of the two.
- `Valor Sheathe original damage reduction` sets the damage you take in a Valor Sheathe evade back to the game's
  own values (70% less for Blademasters, 85% for Gunners), for mods that change it, such as GU Rebalanced (50% / 65%).
  The rest of the mod stays as it is. To pick other values, see `docs/research/valor-sheathe.md`.

## Build

Build on a **Linux x86-64 PC** with Git and working local Docker, the output is for **ARM64** only. For an x86-64 build, please refer to [morerokk/MHGURecomp](https://github.com/morerokk/MHGURecomp).

1. Check the prerequisites:

   ```bash
   git --version
   docker info
   ```

2. Clone this fork:

   ```bash
   git clone --branch master --single-branch https://github.com/pablovesnine/MHGURecomp.git
   cd MHGURecomp
   ```

3. Replace the example path with your dump directory, then build:

   ```bash
   GAME_DIR="/absolute/path/to/MHGU dump/"
   bash tools/build-linux-release.sh --game "$GAME_DIR" --jobs 2
   ```

   The dump must contain `exefs/main`, `exefs/sdk` and the complete `romfs/` from your own MHGU 1.4.0.

4. After a successful build, verify the package:

   ```bash
   (cd dist && sha256sum --check SHA256SUMS)
   ```

Output: `dist/LinuxARM64-MHGURecomp.<version>.tar.gz` and `dist/SHA256SUMS`. The version is the stable upstream release pinned in this checkout. Inspect it with `bash tools/upstream-version.sh`. Release builds need network access to verify upstream tags and full Git history.

## Install

Extract into a new directory on your ARM64 Linux device. Copy your dump's `exefs/` and `romfs/` into its `data/` directory, then run `./mhgurecomp`. Back up saves before testing an update. You can add `mhgurecomp` to Steam as a non-Steam game and it will launch into the game, at least in ArmadaOS.

## Maintenance

Published stable upstream releases are checked every six hours. Compatible releases enter `master` only after full ARM64 validation. Normal fork edits run quick checks; full Docker/QEMU validation is otherwise manual.

[Maintenance](docs/MAINTAINING.md) · [Device requirements and troubleshooting](docs/BUILD-LINUX-ARM64.md) · [Settings](docs/SETTINGS_UI.md)

## License

[MIT](LICENSE), with [third-party notices](THIRD_PARTY_NOTICES). Game files and recompiled game code are not covered by this license. Not affiliated with Capcom or Nintendo.
