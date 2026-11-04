# Settings menu

Open the host settings panel with **F1** or **Minus + Plus** (Back/Select + Start). You can navigate with a mouse, keyboard or controller. **Insert** opens Forge separately.

## Tabs

Use L/R to cycle tabs, or click a tab label.

| Tab | What you can change |
| --- | --- |
| Display | Window mode, display and render resolution, aspect ratio, field of view and HUD anchor. |
| Graphics & Audio | Volume, background mute, FPS, VSync, anti-aliasing, draw distance and FSR. |
| Controls | Face-button mapping, background input, combo input window, mouse sensitivity and keyboard/mouse keybinds. |
| Network | Host port, search hosts, hub server, matchmaking key, hub check and Discord presence. |
| Misc | Hub rules, monster HP scaling and per-quest overrides. |
| Mods | Enable and order installed mods, and review file conflicts. |
| Cheats | Toggle cheats and add a cheat. |
| Menu Options | Language, theme, scale, panel placement, host confirmation button, button icons, save folder, exit policy, Updates, bonus content, Restart and Exit game. |

Mods load from top to bottom, so a later mod wins unless you choose a different result for a conflict. Save the order, then restart. Cheat toggles apply on Save without a restart. Turning a cheat off undoes its code changes, but not values it already changed, such as money or items. New cheat files appear after a restart, while cheats entered through **Add a cheat** work immediately.

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

The game saves the INI file atomically. If a write fails, it keeps the previous file and your draft so you can correct the problem. It preserves comments, unknown keys, aliases, unchanged value spellings and unchanged environment overrides. Mod order and cheat state are saved separately, so check any reported error before assuming everything was saved.

**Restart** asks for confirmation, saves settings and restarts the game. If you have pending changes or text you have not committed, **Exit game** offers Save and exit or Exit without saving. Turning off Confirm exit skips the normal exit confirmation only when there are no pending changes.

The inherited **Updates** option remains for configuration compatibility, but I do not build or ship a binary updater. It does not download or install updates, despite what the old INI help says. Follow [manual updates](../README.md#manual-updates) instead.

## Host confirmation button

In **Menu Options > Confirm button (recomp)**, choose Original, Bottom button or Right button. Save applies your choice immediately and stores `MenuConfirm = Original|South|East` under `[Controls]`. This choice is separate from Face buttons and Button icons, and the button guide follows it after saving. Release any held buttons after changing it and before returning from an overlay to gameplay.

This setting affects only host settings navigation and confirmations, **not** confirmation in the original game's menus or combat. Forge keeps its own mapping. Button icons change the host menu's symbols, not the game's prompts.

## Save folder

Upstream 0.14.0 adds **Menu Options > Save folder**. `[Application] SaveLocation` names the folder containing `save_0`, not the `save_0` directory itself. An empty value uses the normal user-data location.

1. Close the game and back up your saves.
2. Create the destination folder and copy the whole `save_0` directory into it.
3. Open settings and enter the absolute destination path, or select **Choose folder**.
4. Choose **Save and restart** to apply it.

The game does not move or synchronize saves. **Use the default folder** selects the normal location but leaves your other copy untouched. Invalid or unusable folders can fall back to the previous location, so check diagnostics before continuing. `MHGU_SAVE_DIR` overrides this setting. A custom folder must remain mounted and writable.

`MenuChord = Off` under `[Controls]` disables the Plus+Minus shortcut so the game or a cheat can use that combination. F1 still opens host settings.

## FSR

**Graphics & Audio** contains all six `[Upscaler]` fields: FSR, quality, sharpness, object motion, reactive mask and animated surfaces. Enable FSR in the draft to show the other controls. All six need a restart and work with Save, unsaved-change checks and Reset this tab.

This is FSR 3.1 temporal upscaling, not frame generation. Vulkan 1.2 alone is not enough, because the GPU also needs the FSR compute/storage capabilities that the renderer checks. If those checks fail, the log reports that FSR is disabled, though the image may still scale from the reduced render resolution. Object motion has separate GPU checks and can fall back to camera motion only.

While FSR is running, MSAA stays at 1 (off) and FXAA stays off. This also applies if you save unrelated settings or set FSR to Off for the next restart. The AA rows show **Off (FSR)** when FSR is also enabled in the draft. Your saved AA preferences return after you disable FSR and restart the game.

## Custom hub server

The ARM64 client supports the upstream hub protocol. Open the **Network** tab to configure it:

- **Hub server** maps to `[Multiplayer] Server`. Leave it empty for the built-in default, `morerokk-mhgurecomp-ldnserver.duckdns.org`. Enter a hostname or IPv4 address, optionally followed by `:port`, to use another compatible hub. The default hub port is **39510**, not the game's direct-host port. `Off` disables internet hub discovery and relay.
- **Matchmaking key** maps to `[Multiplayer] Key`. Leave it empty for public listings. Online players who want the same private-group listings must choose the same server and key. The key only separates listings, without guaranteeing authentication or encryption.
- **Check hub server** checks the draft server and key, then shows the response time and number of listed hubs. It neither saves those values nor proves that a complete multiplayer session will work.
- **Host port (TCP / UDP)** maps to `[Multiplayer] Port`, default **39500**. **Search hosts** maps to `[Multiplayer] Join`, a comma-separated list of direct hosts, each optionally using `host:port`. These are separate from the hub address and carry restart markers.

Leave your current game hub before changing servers or groups. After **Save**, **Server** and **Key** apply to the next search, join or connection to the hub server without a game restart. **Port** and **Join** do need a restart. If the hub is unreachable, LAN discovery and the direct hosts you configured remain available.

You can also close the game and edit `mhgurecomp.ini`. This example selects a custom hub and group. Replace the address with a server you can use:

```ini
[Multiplayer]
Server = hub.example.org:39510
Key = my-private-group
```

The hub relays internet connections, so players do not need to forward their own game ports. For direct internet play without a hub, the host must be reachable. Forward the host's chosen game port for TCP and UDP, then enter its public address in each joining player's **Search hosts** field. LAN discovery does not need an internet hub.

I do not include a dedicated hub server in this repository or ARM64 package. To run one separately, follow the [upstream 0.13.1 server instructions](https://github.com/morerokk/MHGURecomp/tree/b3746e800b7435dee696e44b84b054a642f600df/server). The server operator needs to make the chosen hub port reachable for TCP and UDP. That is separate from players forwarding game ports. The client and server protocols must be compatible. I have not tested a self-hosted server deployment on the ARM64 device.

For installation and troubleshooting, see [ARM64 device requirements](BUILD-LINUX-ARM64.md).
