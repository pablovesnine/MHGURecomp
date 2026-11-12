# Settings menu

Open the host settings panel with **F1** or **Minus + Plus** (Back/Select + Start). You can navigate with a mouse, keyboard or controller. **Insert** opens Forge separately.

## Tabs

Use L/R to cycle tabs, or click a tab label.

| Tab | What you can change |
| --- | --- |
| Display | Window mode, display and render resolution, aspect ratio, field of view and HUD anchor. |
| Graphics & Audio | Volume, background mute, FPS, VSync, anti-aliasing, draw distance and FSR. |
| Controls | Face-button mapping, background input, combo input window, mouse sensitivity and keyboard/mouse keybinds. |
| Network | Host port, search hosts, hub server, matchmaking key, hub check, direct connections (0.15.3) and Discord presence. |
| Misc | Hub rules, experimental lag compensation (0.16.0), monster HP scaling and per-quest overrides. |
| Mods | Enable and order installed mods, review file conflicts, and open Forge in 0.15.0. |
| Cheats | Toggle cheats and add a cheat. |
| Menu Options | Language, theme, scale, panel placement, host confirmation button, button icons, save folder, exit policy, bonus content, Restart and Exit game. |

Mods load from top to bottom, so a later mod wins unless you choose a different result for a conflict. Save the order, then restart. Cheat toggles apply on Save without a restart. Turning a cheat off undoes its code changes, but not values it already changed, such as money or items. In 0.14.3, close and reopen the settings menu to rescan new, changed or removed cheat files, then Save your selection. Earlier packages need a restart for new files. Cheats entered through **Add a cheat** work immediately.

In 0.15.0, **Mods > Open the Forge menu** opens plugin settings over the paused host panel. It is disabled if no plugin title or ImGui render entry point is available. Cancel, the configured Forge menu key (Insert by default), or **Minus + Plus** (Start + Back) closes Forge and returns to the underlying settings panel when one is open. F1 also returns from Forge to that panel. Forge keeps its own confirm/cancel mapping. Release held buttons before returning to settings or gameplay.

## Navigation and help

- Use the D-pad or left stick to move between rows, and left/right to adjust values. Confirm opens choices on rows with a dropdown arrow.
- Adjust numeric values directly. On the frame-rate row, Confirm offers 30, 60, 90, 120, 150 and 240 FPS, while left/right adjusts by one FPS.
- Text rows open an editor with an on-screen controller keyboard. You can also type on a physical keyboard and use Ctrl+A, Ctrl+V and Enter. If the input is invalid, the editor stays open and explains the problem.
- Back or Escape cancels the current editor or confirmation before leaving the main panel. F1 or the button combination that opened the panel works the same way. Returning from a subview restores the row and scroll position you left.
- Use the **Save** or **Reset this tab** row. There are no face-button shortcuts for saving or discarding changes. Confirmation dialogs select Cancel by default.

The fixed help box describes the selected row or the row under your mouse, including defaults where available. Most help comes from the default INI comments, with translated text where available. The guide at the bottom shows the current navigation, Confirm and Back buttons. Options scroll above the help box and guide.

In Menu Options, you can choose English/Spanish, change the theme and set the interface scale from 50–200%. Use **Detach menu** to drag or resize the panel, or **Move menu** to position it with a controller. **Attach menu** returns it to its normal position.

## Saving and restarting

Changes stay in the draft until you choose **Save**. If you close the panel with unsaved changes, it offers Cancel, Save and close, or Discard and close. **Reset this tab** changes only the draft, so you still need to Save. Saving settings does not save game progress.

Live settings apply on Save, including volume, FPS, FOV, anti-aliasing, VSync, mouse sensitivity, face mapping and background input. Language, symbols, theme and interface scale preview immediately, but Save makes them permanent. An asterisk marks settings that need a restart. After saving, the status shows a pending restart if those values differ from the running configuration.

Upstream 0.14.3 also makes small-monster synchronization, monster HP rules, village-in-hub rules and bonus-content enablement live. HP factors apply when HP is assigned, not retroactively to every living monster. From 0.15.4, changed factors affect the next large monster's HP assignment and part HP at its next refill, not all current values immediately. Disabling village quests while browsing their menu takes effect when you return to the rank/star menu. Bonus content is checked on the next qualifying save-file open. These changes do not replace save backups or device testing.

The game saves the INI file atomically. If a write fails, it keeps the previous file and your draft so you can correct the problem. It preserves comments, unknown keys, aliases, unchanged value spellings and unchanged environment overrides. Mod order and cheat state are saved separately, so check any reported error before assuming everything was saved.

**Restart** asks for confirmation, saves settings and restarts the game. If you have pending changes or text you have not committed, **Exit game** offers Save and exit or Exit without saving. Turning off Confirm exit skips the normal exit confirmation only when there are no pending changes.

The legacy **Updates** INI key remains readable for compatibility, but I removed the inactive menu row. I do not build or ship a binary updater. It does not download or install updates. Follow [manual updates](../README.md#manual-updates) instead.

## Host confirmation button

In **Menu Options > Confirm button (recomp)**, choose Original, Bottom button or Right button. Save applies your choice immediately and stores `MenuConfirm = Original|South|East` under `[Controls]`. This choice is separate from Face buttons and Button icons, and the button guide follows it after saving. Release any held buttons after changing it and before returning from an overlay to gameplay.

This setting affects only host settings navigation and confirmations, **not** confirmation in the original game's menus or combat. Forge keeps its own mapping. Button icons change the host menu's symbols, not the game's prompts.

From 0.16.1, B at the title main menu requests exit; it is not remapped by MenuConfirm. The hook calls the original title update first and responds to a new B press only in that menu. An open overlay swallows the button until release. The host then exits immediately only when Confirm exit is Off and the settings draft is clean; otherwise it opens the normal exit/unsaved-settings flow. I test those gates synthetically, not on a physical controller.

## Save folder

Upstream 0.14.0 adds **Menu Options > Save folder**. `[Application] SaveLocation` names the folder containing `save_0`, not the `save_0` directory itself. An empty value uses the normal user-data location.

1. Close the game and back up your saves.
2. Create the destination folder and copy the whole `save_0` directory into it.
3. Open settings and enter the absolute destination path, or select **Choose folder**.
4. Choose **Save and restart** to apply it.

The game does not move or synchronize saves. **Use the default folder** selects the normal location but leaves your other copy untouched. Invalid or unusable folders can fall back to the previous location, so check diagnostics before continuing. `MHGU_SAVE_DIR` overrides this setting. A custom folder must remain mounted and writable.

`MenuChord = Off` under `[Controls]` disables the Plus+Minus shortcut so the game or a cheat can use that combination. F1 still opens host settings.

## FSR

**Graphics & Audio** contains all six `[Upscaler]` fields: FSR, quality, sharpness, object motion, reactive mask and animated surfaces. Enable FSR in the draft to show the other controls. In 0.14.3, Sharpness and reactive mask apply on Save while FSR is running. FSR enable, quality, object motion and animated surfaces still need a restart. Earlier packages require a restart for all six. The controls work with Save, unsaved-change checks and Reset this tab.

This is FSR 3.1 temporal upscaling, not frame generation. Vulkan 1.2 alone is not enough, because the GPU also needs the FSR compute/storage capabilities that the renderer checks. If those checks fail, the log reports that FSR is disabled, though the image may still scale from the reduced render resolution. Object motion has separate GPU checks and can fall back to camera motion only.

While FSR is running, MSAA stays at 1 (off) and FXAA stays off. This also applies if you save unrelated settings or set FSR to Off for the next restart. The AA rows show **Off (FSR)** when FSR is also enabled in the draft. Your saved AA preferences return after you disable FSR and restart the game.

## Loading indicator

Upstream 0.15.0 adds `[Performance] LoadingIndicator = On` for startup and shader-preparation feedback. It is INI-only, not a settings-panel row. Close the game before editing it, then restart for the change to apply. Set it to Off to disable the indicator. I have not validated startup rendering, FXAA output or GPU timings on the ARM64 device for this version.

In 0.15.2 the indicator also reports mod-file scanning and application. Archive comparisons can run in parallel; mods still layer in their configured order. I have not measured first-start speed on the device.

Village quests started from the Hub or Hunters' Pub can receive up to three extra Map items in the last empty supply-box slots in 0.15.0. Reserved delayed-delivery slots stay untouched. This does not validate real quest transitions, repeated game calls or multiplayer behavior on a device.

## Text and HDR

From 0.15.2, **Graphics & Audio** includes **Fix kerning** and **Bold text**. They apply on Save. Linux defaults are `FixKerning = On` and `BoldText = Off` in `[Graphics]`. If a font mod looks wrong, try **Fix kerning Off / Bold text On** to restore the game's placement and weight. Metrics are loaded once from the installed font, so restart after changing a font mod.

**HDR** is optional and defaults to Off. Enable HDR in the operating system/compositor first; the Vulkan surface must advertise an HDR10 or scRGB format. Auto prefers HDR10 and falls back to scRGB, or SDR if neither is offered. The renderer can also fall back to SDR if it cannot allocate the HDR composition image. Check the `[hdr]` log; the toggle alone does not prove HDR output.

Disable FSR and restart before trying HDR if FSR is running. The HDR startup path disables FSR, and Smooth gradients is not used with HDR. The panel exposes peak/game/UI brightness, gamma, exposure, colour grading, bloom and analysis; normal HDR settings are live, but the panel marks HDR as requiring a restart while FSR is running. I do not treat switching between the two during a session as validated.

`[HDR] UnclampedScene = On` and `HDRFormat = Auto` are INI-only. Close the game before editing them and restart. Use your display's measured/specification peak rather than assuming the default 1000 nits fits it. I have not tested HDR presentation, colour accuracy, analysis overlays or GPU compatibility on ARM64 hardware. Public font/archive fixtures do not validate game typography or rendering.

## Offline transitions, HP and mouse aiming

In 0.15.4, the offline fastload hooks shorten selected town, stream-stop and music-fade waits only outside a network session. I retain them enabled by default. Set the environment variable `MHGU_NO_FASTLOAD=1` before launch to opt out; it is not an INI key or a new menu row. I have not measured loading times on the device, and the hooks do not promise to remove every loading wait.

The existing monster HP factors now also scale part HP and the associated part thresholds, including the Village-in-Hub multiplier. A changed factor applies to part HP at its next refill, not to all accumulated part damage immediately. The part-table multiplier is capped at 16. This is not a separate setting and does not resolve the crossplay HP-scaling limitation below. I have not checked part breaks, staggers or multiplayer consistency in a real hunt.

Mouse input now also controls bow aiming. The hook handles the special aim modes separately from the normal camera, applies the existing mouse sensitivity and in-game inversion, and avoids consuming the same movement twice. I test bounded synthetic camera states and transitions, not physical mouse feel, weapon behavior or controller interoperability on the device.

The ImGui change treats a moving vertex-write cursor as a data pointer rather than a persistent mirrored object. The graphics change sends -1.0 in the front-face uniform and converts it to an integer mask in the shader. I check generated tables, pointer conversions and compiler contracts; these checks do not demonstrate that a particular plugin, HDR display or GPU renders correctly.

## Custom hub server

The ARM64 client supports the upstream hub protocol. Upstream 0.14.3 uses protocol 3 and cannot share a game hub with earlier recomp releases, even when the server and key match. I keep the desktop public matchmaking behavior rather than the mobile-only room. Open the **Network** tab to configure it:

- **Hub server** maps to `[Multiplayer] Server`. Leave it empty for the built-in default, `morerokk-mhgurecomp-ldnserver.duckdns.org`. Enter a hostname or IPv4 address, optionally followed by `:port`, to use another compatible hub. The default hub port is **39510**, not the game's direct-host port. `Off` disables internet hub discovery and relay.
- **Matchmaking key** maps to `[Multiplayer] Key`. Leave it empty for public listings. Online players who want the same private-group listings must choose the same server and key. The key only separates listings, without guaranteeing authentication or encryption.
- **Check hub server** checks the draft server and key, then shows the response time and number of listed hubs. It neither saves those values nor proves that a complete multiplayer session will work.
- **Host port (TCP / UDP)** maps to `[Multiplayer] Port`, default **39500**. **Search hosts** maps to `[Multiplayer] Join`, a comma-separated list of direct hosts, each optionally using `host:port`. These are separate from the hub address.

Leave your current game hub before changing servers or groups. After **Save**, **Server** and **Key** apply to the next search, join or connection to the hub server without a game restart. In 0.14.3, **Port** and **Join** also apply to the next host/search operation without restarting; they do not reconfigure an active hub or its sockets. Earlier packages require a restart for Port and Join. If the hub is unreachable, LAN discovery and the direct hosts you configured remain available.

You can also close the game and edit `mhgurecomp.ini`. This example selects a custom hub and group. Replace the address with a server you can use:

```ini
[Multiplayer]
Server = hub.example.org:39510
Key = my-private-group
```

The hub relays internet connections, so players do not need to forward their own game ports. For direct internet play without a hub, the host must be reachable. Forward the host's chosen game port for TCP and UDP, then enter its public address in each joining player's **Search hosts** field. LAN discovery does not need an internet hub.

I do not include a standalone dedicated hub-server product in this repository or ARM64 package. To run the native hub service separately, follow the [upstream 0.16.0 server instructions](https://github.com/morerokk/MHGURecomp/tree/dc26e6d9a22afbedc1138fd07e94f3e3c55efed3/server). That service is distinct from the optional embedded emulator servers in 0.15.1. The native server operator needs to make the chosen hub port reachable for TCP and UDP. That is separate from players forwarding game ports. The client and server protocols must be compatible. I have not tested a self-hosted server deployment on the ARM64 device.

### Direct connections

From 0.15.3, **Direct connections** in **Network** maps to `[Multiplayer] Direct`, default On. When both the host and a player opt in, a compatible native hub server can give each the other's public UDP address. Their clients try direct UDP and keep the relay ready as fallback. Off means new links do not request peer addresses or offer direct UDP. This is not encrypted transport.

I retain the upstream live setting, but each player link captures its value when it starts. **Save** changes the value for new links; it does not tear down or change active links. Leave and rejoin the game hub to apply Off to existing connections. `MHGU_LDN_DIRECT` is the environment override. Direct does not reconfigure emulator crossplay.

Older clients and hub servers can stay on the relay. A compatible server update is needed for address exchange; upstream announced a default-server redeploy for 8 November 2026 at 20:00 UTC, but I have not verified that deployment. The open-before-passcoded hub ordering is also a server-side change, not a client fix I can deploy here.

Direct UDP may fail behind symmetric NAT, CGNAT or a firewall. The client falls back to relayed UDP, then TCP when UDP is unavailable. I have not tested NAT traversal across real routers or measured a latency improvement. Public synthetic protocol tests are not a multiplayer or privacy audit of the deployed service.

I found one upstream recovery limit in a synthetic probe: after a direct-path outage, three acknowledgements ten seconds apart still accumulate and re-enable direct mode. The counter does not enforce the documented consecutive-answer behavior. I retain that code without claiming it prevents path flapping.

The Village change in this version releases demo-dependent spawn slots once a hunter reaches a matching event area during a Village quest in a session. I test the hook's gates, one-shot release, between-quest reset and original-call ordering with synthetic memory, retaining the supply-box trace fix. I have not reproduced or resolved a softlock in a real hunt on the device.

### Lag compensation

From 0.16.0, **Misc > Lag compensation (experimental)** maps to `[Multiplayer] LagCompensation`, default On. **Save** publishes the setting live without restarting; cancelling a draft leaves it unchanged. `MHGU_LAGCOMP` is a numeric startup override, not a live environment switch. I retain the upstream default, not a claim that it is proven correct in a hunt.

The ordinary hit hook is active with the setting enabled and a network session up. In 0.16.0 it excludes emulator crossplay; from 0.16.1 it uses virtual UDP port 47318 during crossplay and the native auxiliary channel otherwise. Emulator peers need the matching Lag Compensation plugin. I use the built-in implementation on the recomp, which skips a Forge plugin with the exact display name Lag Compensation before its onInit callback, but after constructors and onLoad. This is not a plugin sandbox. A local hunter reports supported hits to the monster's simulation owner. That owner suppresses its local copy only while the reporting hunter has a fresh enabled Hello; bow/bowgun shots also require the shot capability. Old or disabled participants retain the original hit path. Supported shots are selected by exact projectile classes; this does not cover every weapon effect. The generated INI help is corrected in 0.16.1 to include bows/bowguns and the emulator plugin requirement.

I found a lifecycle gap with synthetic memory: queued reports can still apply after network loss because the owner-drain gate omits that condition. In 0.16.0, transition to crossplay also bypasses the ordinary activation gate; crossplay is intentionally active in 0.16.1, so that transition is no longer a failure of its activation policy. Disconnect and repeated initialization do not clear Hellos, capabilities or the queue. Expiry and queue bounds are not a session reset. Turning LagCompensation Off prevents the owner from applying matching queued reports, but it is not a general cleanup or security fix.

The receiver bounds message length, slot, monster ID and damage fields, but trusts the slot in the payload. From 0.16.1 it rejects messages claiming the local slot, which is not sender authentication. It does not authenticate the sender-slot relationship, deduplicate reports or enforce sequence order. Duplicates can apply twice; arrival order resolves equal-rank reactions. Some fields are not validated, and single-thread tests do not establish concurrent safety. I keep these upstream limitations visible rather than treating the option as replay protection or a multiplayer security boundary. I have not measured latency, validated damage/KO/part behavior, or tested real native/emulator interoperability.

## 0.16.0 controls, chat and Village quests

The item wheel now has a separate Prowler handler. I check its mode gates, queued-notch consumption, expiry and original-call ordering, not the game's pouch selection or physical wheel feel. Lenient ComboInputWindow also adjusts real presses and can wait up to one 30-FPS update for a third button at higher frame rates; Strict retains the original per-update behavior. The new generator hooks require regenerating the local game library from the licensed dump, not reusing an old generation stamp. I have not tested Better Inputs or weapon combos in-game.

Forge plugins can temporarily override a keybind row without replacing the player's saved INI keys. The keybind menu shows the mod's override, and the saved player keys return when the mod releases it. A first-key capture API includes mouse buttons and wheel events, even when an overlay consumes them. These are source/compiler and synthetic-helper contracts, not validation of a real plugin.

Chat still requests at most 120 codepoints and sends at most 119 UTF-8 text bytes plus NUL per game payload. The new code packs wider rows, up to five per payload, and can split one composition across messages. I test valid UTF-8 boundaries and name suppression on continuation rows, not font rendering or real network delivery. Separate sanitizer probes expose inherited hardening limits for malformed truncated UTF-8 and extreme integer wheel steps; ordinary input tests do not establish safety for arbitrary bytes or integers.

Village quest lists now reload after returning to the rank/star menu. Chinese game-language modes acquire the Village text archive for relevant quest lookups, with timeout, null and release handling. I preserve the bounded supply trace and spawn-demo hook in this protected file. Synthetic resource stubs do not validate the installed archive, translated game text or actual quest transitions.

The renderer also changes fragment-shader handling of zero multiplied by a reciprocal texture alpha, plus HUD grouping and preview anchoring. I check portable types and source/compiler contracts, not GPU output, HDR correctness or a performance improvement.

In 0.16.1, the generator also clamps a negative decoration free-slot count to zero before retaining the original halfword load. I check signed boundaries and instruction order. Regenerate the game library from my own MHGU 1.4.0 dump after this update; copying an old generation stamp does not apply the patch. I have not tested decoration selection in-game.

Two synthetic source probes retain known limits: a backward branch can miss reciprocal-alpha tracking learned later in the translator's single pass, and stacked HUD groups can update their matrices without updating the earlier group's scissor-prediction cache. These CPU-side inconsistencies are not proof of a visible defect in a particular game scene, and I have not fixed or validated them on hardware.

### Experimental emulator crossplay

Upstream 0.15.1 adds experimental Ryujinx-LDN and suyu-family room transports. They require matching MHGU 1.4.0 game versions, but I have not tested actual emulator interoperability. These are INI-only `[Multiplayer]` options, not new Network-tab controls. Close the game before editing them, then restart; do not assume the existing live native-server controls reconfigure these transports.

- `RyuServers`, `RyuHost` and `RyuPassphrase` default to empty. `RyuServers` lists servers to search, with TCP port 30456 by default; `RyuHost` selects where to create a hub. An empty passphrase means public lobbies.
- `RoomServer`, `RoomPassword` and `RoomName` default to empty, and `RoomHost` defaults to Off. A configured room uses UDP/ENet port 24872 by default. An empty name becomes MHGU Player.
- `RyuServe` and `RoomServe` default to Off. Enabling them starts the corresponding embedded server while local play is open. Their port settings are `RyuServePort` and `RoomServePort`; zero selects 30456 and 24872 respectively, not a random port. Embedded listeners bind all IPv4 interfaces, not just loopback.

I do not recommend exposing these embedded servers to the public Internet. They provide no encrypted transport. The embedded Ryu server's passphrase parsing differs from the client's, and joining a known lobby ID does not enforce all scan-time restrictions. Do not rely on a private passphrase or a reject setting as authentication. Use only trusted peers in a controlled, isolated environment.

Small-monster synchronization is suppressed in crossplay, but the claim that HP scaling is disabled is not implemented consistently: local non-unit HP factors can still apply. Leave HP factors at 1.0 when exploring this mode; that is a precaution, not a validation of multiplayer consistency. Repeated bridge teardown/restart and departed room members also have unresolved lifecycle limits. I have not tested real hubs, game packet translation or those lifecycle cases on ARM64.

For installation and troubleshooting, see [ARM64 device requirements](BUILD-LINUX-ARM64.md).
