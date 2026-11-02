# Settings menu

Open the host settings panel with **F1** or **Minus + Plus** (Back/Select + Start). **Insert** opens Forge separately. Mouse, keyboard and controller navigation are supported.

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
| Menu Options | Language, theme, scale, panel placement, host confirmation button, button icons, exit policy, Updates, bonus content, Restart and Exit game. |

Mods load from top to bottom; a later mod wins unless a conflict choice overrides it. Save the order, then restart. Cheat toggles apply on Save without restarting. Turning a cheat off undoes its code changes, not values it already changed, such as money or items. Newly added cheat files appear after restarting; cheats added through **Add a cheat** work immediately.

## Navigation and help

- D-pad or left stick moves between rows; left/right adjusts values. Confirm opens choices on rows with a dropdown arrow.
- Numeric values adjust directly. Confirm on the frame-rate row offers 30, 60, 90, 120, 150 and 240 FPS; left/right still adjusts by one FPS.
- Text rows open an editor with a controller keyboard. Physical typing, Ctrl+A, Ctrl+V and Enter also work. Invalid input stays open with an explanation.
- Back or Escape cancels the current editor or confirmation before leaving the main panel. F1 or the opening chord follows the same route. Returning from a subview restores its originating row and scroll position.
- Activate the **Save** or **Reset this tab** row; there are no face-button save/discard shortcuts. Confirmation dialogs select Cancel by default.

The pinned help box describes the focused or mouse-pointed row, including defaults where available. Most help comes from the default INI comments; translated text is used when available. The bottom guide shows the current navigation, Confirm and Back buttons. Options scroll above the help and guide.

Menu Options offers English/Spanish, themes and interface scale from 50–200%. Use **Detach menu** to drag/resize the panel, or **Move menu** with a controller; **Attach menu** restores its normal placement.

## Saving and restarting

Changes are drafts until **Save**. Closing with unsaved changes offers Cancel, Save and close, or Discard and close. **Reset this tab** changes the draft only; Save is still required. Settings operations do not save game progress.

Live settings, such as volume, FPS, FOV, anti-aliasing, VSync, mouse sensitivity, face mapping and background input, apply on Save. Language, symbols, theme and interface scale preview immediately and persist on Save. An asterisk marks restart-only settings; the saved status indicates a pending restart when those values differ from the running configuration.

INI saves are atomic: a failed configuration write keeps the previous file and the draft available for correction. Comments, unknown keys, aliases and unchanged value spellings are preserved, as are unchanged environment overrides. Mod order and cheat state are saved separately; check any reported error before assuming that all changes were saved.

**Restart** explicitly confirms, saves settings, then restarts. **Exit game** offers Save and exit or Exit without saving if changes or uncommitted text are pending. Disabling Confirm exit skips the ordinary exit confirmation only when there are no pending changes.

The inherited **Updates** option is retained for configuration compatibility. I do not build or ship a binary updater; this option does not download or install updates.

## Host confirmation button

In **Menu Options > Confirm button (recomp)**, choose Original, Bottom button or Right button. Save applies the policy immediately and persists `MenuConfirm = Original|South|East` under `[Controls]`. This host-menu policy is independent of Face buttons and Button icons. The guide follows the saved policy; held buttons must be released after a policy change and before returning from an overlay to gameplay.

This setting affects only host settings navigation and confirmations. It does **not** remap confirmation in the original game's menus or combat; Forge retains its own mapping. Button icons change the host menu's symbols, not the game's prompts.

## FSR

**Graphics & Audio** exposes all six `[Upscaler]` fields: FSR, quality, sharpness, object motion, reactive mask and animated surfaces. Enable FSR in the draft to expose its other controls. All six are restart-only and participate in Save, unsaved-change checks and Reset this tab.

While FSR is active in the running configuration, it keeps MSAA at 1 (off) and FXAA off, even after saving unrelated settings or staging FSR Off for the next restart. The AA rows show **Off (FSR)** while the draft also has FSR enabled. Stored AA preferences are retained for use after FSR is disabled and the game restarts.

For installation and troubleshooting, see [ARM64 device requirements](BUILD-LINUX-ARM64.md).
