# Optional Bambu Studio P2S AMS Combo workflow

`vibecad_stage_for_bambu` selects its contract from the resolved profile id. `bambu-p2s` is the single-nozzle P2S adapter. `bambu-x2d` remains the dual-tool adapter. A generic FDM profile is refused.

## Encoded contract

| Fact | Value | Source |
|---|---|---|
| Build volume | 256 × 256 × 256 mm | [P2S specifications](https://bambulab.com/en/p2s/specs) |
| Included nozzle | 0.4 mm hardened steel | same |
| Supported nozzles | 0.2, 0.4, 0.6, 0.8 mm | same |
| Max nozzle / bed | 300 °C / 110 °C | same |
| Toolhead | one nozzle | Bambu Studio preset `Bambu Lab P2S 0.4 nozzle` (`extruder_offset` `0X0`) |
| Printable area | corner origin `0x0` to `256x256` | parent preset `fdm_bbl_3dp_001_common`, not overridden by the P2S 0.4 preset |
| Bed exclusion | none | P2S 0.4 preset sets `bed_exclude_area` to `[]` |
| Plate center used here | 128, 128, 0 mm | midpoint of that printable square |
| Combo AMS slots | 4 | one AMS 2 Pro in the Combo |
| Maximum slots | 20 | [P2S FAQ](https://wiki.bambulab.com/en/p2s/manual/p2s-faq): 4 AMS 2 Pro + 4 AMS HT |
| Studio process hint | `0.20mm Standard @BBL P2S` | P2S 0.4 preset `default_print_profile` |

`min_layer_height_mm` 0.08 and `max_layer_height_mm` 0.32 on the bundled profile are this plugin's existing 0.4 mm check band, the same numbers as `bambu-x2d`. They are not a Bambu firmware limit.

Studio's `machine_max_speed_x` of 1000 mm/s is a travel preset. The official toolhead maximum is 600 mm/s. This adapter does not enforce either speed.

## What the adapter writes

Named STL fallbacks, `exports/bambu-assemble-list.json` centered at 128, 128, 0, and `exports/bambu-handoff.json` with `bambu_contract` and `p2s_contract`.

It does not send a print, infer a live AMS route, or claim that `slicer-handoff.3mf` is a Bambu-native project. A native archive is acceptable only after that Studio build's `--info` succeeds. This plugin does not run that command.

## Slot and nozzle rules

- Every solid's `tool` is `0` or omitted. A second tool index is rejected.
- With `ams_slot_capacity` omitted, slots must be 1–4.
- Set `ams_slot_capacity` from 1 to 20 only when more AMS units are actually connected.
- TPU 85A and TPU 90A are external-spool materials on P2S. An AMS slot number does not mean the AMS can feed them.
